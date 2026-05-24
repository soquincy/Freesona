# cogs/mvsep.py: MVSEP audio source separation (vocals/instrumental via BS Roformer)
# YES I make mashups and I need this shut up. You may disable this module with /module disable mvsep if you don't care about separating audio;
# But hey it's a fun party trick and it works surprisingly well for a free API.

# Current problem: no way to get progress updates or queue position; no way to cancel; links expire after some time; only one job at a time on free tier.
# But hey it works and it's free so I'm not complaining. My broke ass appreciates it.

import os
import asyncio
import logging
import tempfile
import aiohttp
import discord

from discord.ext import commands
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv

from pathlib import Path
from utils.security import is_public_http_url

load_dotenv()

MVSEP_API_KEY = os.getenv("MVSEP_API_KEY")
BOT_NAME      = os.getenv("BOT_NAME", "Bot")

# BS Roformer ver 2025.07 — SDR vocals: 11.89, SDR instrum: 18.20
SEP_TYPE  = 40
ADD_OPT1  = 81
OUT_FMT   = 0   # mp3 320kbps

POLL_INTERVAL = 10   # seconds between status checks
POLL_TIMEOUT  = 600  # 10 minutes max

# Statuses that mean the job is still running
IN_PROGRESS = {"waiting", "processing", "distributing", "merging"}

DIRECT_AUDIO_EXTS = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac")
YTDLP_DOMAINS = (
    "youtube.com",
    "youtu.be",
    "music.youtube.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "facebook.com",
    "fb.watch",
    "soundcloud.com",
    "spotify.com",
    "reddit.com",
    "vimeo.com",
    "bilibili.com",
    "twitch.tv",
)

logger = logging.getLogger("FreesonaBot")


def is_direct_audio_url(url: str) -> bool:
    lower = url.lower().split("?")[0]
    return any(lower.endswith(ext) for ext in DIRECT_AUDIO_EXTS)


def should_download_with_ytdlp(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in YTDLP_DOMAINS)


class MVSepCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot   = bot
        self._busy = False

    # ------------------------------------------------------------------
    # Submit job
    # ------------------------------------------------------------------

    async def _submit(
        self,
        session: aiohttp.ClientSession,
        *,
        file_path: Optional[str] = None,
        url: Optional[str] = None,
    ) -> dict:
        endpoint = "https://mvsep.com/api/separation/create"
        data = aiohttp.FormData()
        data.add_field("api_token",     MVSEP_API_KEY)
        data.add_field("sep_type",      str(SEP_TYPE))
        data.add_field("add_opt1",      str(ADD_OPT1))
        data.add_field("output_format", str(OUT_FMT))

        if file_path:
            assert file_path is not None
            with open(file_path, "rb") as audio_file:
                data.add_field(
                    "audiofile",
                    audio_file.read(),
                    filename=os.path.basename(file_path),
                    content_type="audio/mpeg",
                )
        elif url:
            assert url is not None
            data.add_field("url", url)
        else:
            raise ValueError("Need file_path or url.")

        async with session.post(endpoint, data=data) as resp:
            return await resp.json()

    # ------------------------------------------------------------------
    # Poll for result
    # Per docs: status is a TOP-LEVEL key, data holds extra info
    # Statuses: not_found | waiting | processing | done | failed |
    #           distributing | merging
    # ------------------------------------------------------------------

    async def _poll(self, session: aiohttp.ClientSession, job_hash: str) -> dict:
        endpoint = f"https://mvsep.com/api/separation/get?hash={job_hash}"
        elapsed  = 0

        while elapsed < POLL_TIMEOUT:
            await asyncio.sleep(POLL_INTERVAL)
            elapsed += POLL_INTERVAL

            async with session.get(endpoint) as resp:
                payload = await resp.json()

            # status is top-level per API docs
            status = payload.get("status", "unknown")

            if status == "done":
                return payload

            if status == "failed":
                reason = payload.get("data", {}).get("message", "No reason given.")
                raise RuntimeError(f"Separation failed: {reason}")

            if status == "not_found":
                raise RuntimeError("Job hash not found — it may have expired.")

            if status in IN_PROGRESS:
                # Log queue position if available
                queue_pos = payload.get("data", {}).get("current_order")
                if queue_pos:
                    logger.info(f"MVSEP job {job_hash} — status: {status}, queue position: {queue_pos}")
                continue

            # Unknown status — keep waiting
            logger.warning(f"MVSEP unknown status: {status}")

        raise TimeoutError("Job timed out after 10 minutes.")

    # ------------------------------------------------------------------
    # Input resolver: attachment > direct URL > yt-dlp: I'm starting to think that this dosen't support direct URLs. May fix this later.
    # ------------------------------------------------------------------

    async def _resolve_input(
        self,
        ctx,
        source: Optional[str],
        tmp_dir: str,
        slash_attachment: Optional[discord.Attachment] = None,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Returns (file_path, pass_url).
        file_path: local path to upload binary (or None)
        pass_url:  URL to pass directly to MVSEP (or None)

        Priority:
          1. slash_attachment (discord.Attachment from /separate)
          2. ctx.message.attachments (prefix ~separate)
          3. direct audio URL
          4. yt-dlp platform URL
        """
        # 1a. Slash command attachment — discord.Attachment type hint
        #     Per discord.py docs, discord.Attachment is the correct type
        #     for file parameters in slash/hybrid commands (2.0+)
        if slash_attachment is not None:
            dest = os.path.join(tmp_dir, slash_attachment.filename)
            await slash_attachment.save(Path(dest))
            return dest, None

        # 1b. Prefix command attachment via ctx.message
        if ctx.message.attachments:
            att  = ctx.message.attachments[0]
            dest = os.path.join(tmp_dir, att.filename)
            await att.save(dest)
            return dest, None

        if not source:
            return None, None
        if not is_public_http_url(source):
            raise RuntimeError("Please provide a public http(s) URL.")

        # 2. Plain direct audio URL — pass straight to MVSEP.
        if is_direct_audio_url(source):
            return None, source

        # 3. Platform/social URL — yt-dlp download then upload to MVSEP.
        from cogs.ytdlp import YtDlp
        ytdlp_cog = self.bot.get_cog("YtDlp")
        if ytdlp_cog is None or not isinstance(ytdlp_cog, YtDlp):
            raise RuntimeError("yt-dlp cog not loaded.")

        if should_download_with_ytdlp(source):
            local = await ytdlp_cog.fetch_ytdlp(ctx, source, is_audio=True, tmp_dir=tmp_dir)
            if not local:
                raise RuntimeError("yt-dlp failed to download audio.")
            return local, None

        # 4. Any other public URL — try yt-dlp as a fallback.
        local = await ytdlp_cog.fetch_ytdlp(ctx, source, is_audio=True, tmp_dir=tmp_dir)
        if not local:
            raise RuntimeError("yt-dlp failed to download audio.")
        return local, None

    # ------------------------------------------------------------------
    # Actual command
    # ------------------------------------------------------------------

    @commands.hybrid_command(
        name="separate",
        aliases=["sep", "stems"],
        help="Separate vocals and instrumental from audio. Attach a file or pass a URL."
    )
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def separate(self, ctx, url: Optional[str] = None, attachment: Optional[discord.Attachment] = None):
        if ctx.guild is None:
            await ctx.send("This command is server-only.")
            return

        if not MVSEP_API_KEY:
            await ctx.send("MVSEP API key not configured.")
            return

        if self._busy:
            await ctx.send(
                "⏳ A separation job is already running. "
                "Free tier only allows one at a time — try again when it finishes.",
                ephemeral=True if ctx.interaction else False,
            )
            return

        if not url and not ctx.message.attachments and not attachment:
            await ctx.send("Attach an audio file or pass a URL.")
            return

        await ctx.defer()
        self._busy    = True
        status_msg    = await ctx.send("⏳ Submitting to MVSEP...")

        try:
            async with aiohttp.ClientSession() as session:
                with tempfile.TemporaryDirectory() as tmp_dir:

                    # Resolve input
                    try:
                        file_path, pass_url = await self._resolve_input(ctx, url, tmp_dir, slash_attachment=attachment)
                    except RuntimeError as e:
                        await status_msg.edit(content=f"❌ {e}")
                        return

                    if not file_path and not pass_url:
                        await status_msg.edit(content="❌ No valid input found.")
                        return

                    # Submit
                    try:
                        result = await self._submit(session, file_path=file_path, url=pass_url)
                    except Exception as e:
                        await status_msg.edit(content=f"❌ Submission error: {e}")
                        return

                    if not result.get("success"):
                        msg = result.get("data", {}).get("message", "Unknown error.")
                        await status_msg.edit(content=f"❌ MVSEP rejected the job: {msg}")
                        return

                    job_hash = result["data"]["hash"]
                    await status_msg.edit(
                        content=f"✅ Job submitted. Polling every {POLL_INTERVAL}s... (`{job_hash}`)"
                    )

                    # Poll
                    try:
                        done = await self._poll(session, job_hash)
                    except (RuntimeError, TimeoutError) as e:
                        await status_msg.edit(content=f"❌ {e}")
                        return

            # Build result embed
            data_block = done.get("data", {})
            files_data = data_block.get("files", [])
            algo_desc  = data_block.get("algorithm_description", "BS Roformer ver 2025.07")

            embed = discord.Embed(
                title="Separation Complete",
                description=f"Model: {algo_desc}",
                color=discord.Color.green(),
            )

            for f in files_data:
                name = f.get("name", "stem")
                link = f.get("download_link") or f.get("link") or f.get("url", "")
                if link:
                    embed.add_field(name=name, value=f"[Download]({link})", inline=True)

            embed.set_footer(text="Links are hosted by MVSEP and expire after some time.")
            await status_msg.edit(content=None, embed=embed)

        finally:
            self._busy = False

    @separate.error
    async def separate_error(self, ctx, error):
        self._busy = False
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Wait **{error.retry_after:.1f}s**.", delete_after=10)
        else:
            logger.error(f"Separate error: {error}")
            await ctx.send(f"❌ Unexpected error: {error}")

# Oh well that was unintuitive...
async def setup(bot):
    await bot.add_cog(MVSepCog(bot))
