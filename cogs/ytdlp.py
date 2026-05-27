# cogs/ytdlp.py: yt-dlp video downloader

import asyncio
import logging
import os
import tempfile
import time

import discord
from discord import app_commands
from discord.ext import commands

from utils.security import is_public_http_url

log = logging.getLogger(__name__)

# Resolutions attempted in order from highest to lowest quality
_VIDEO_RESOLUTIONS = [1080, 720, 480]

# Target size for FFmpeg compression (slightly under the hard limit)
_COMPRESS_TARGET_MB = 9.5

# Subprocess timeout in seconds — prevents hung downloads from blocking indefinitely
_SUBPROCESS_TIMEOUT = 300


def _normalize_url(url: str) -> str:
    """Redirect music.youtube.com links to www.youtube.com."""
    return url.replace("music.youtube.com", "www.youtube.com")


def _clear_dir(directory: str) -> None:
    """Remove all files in a directory, ignoring errors."""
    for name in os.listdir(directory):
        try:
            os.remove(os.path.join(directory, name))
        except OSError:
            pass


def _find_file(directory: str, ext: str) -> str | None:
    """Return the first file with the given extension in a directory, or None."""
    for name in os.listdir(directory):
        if name.endswith(f".{ext}"):
            return os.path.join(directory, name)
    return None


async def _run(*cmd: str, timeout: int = _SUBPROCESS_TIMEOUT) -> int:
    """Run a subprocess and return its exit code. Raises TimeoutError on timeout."""
    proc = await asyncio.create_subprocess_exec(*cmd)
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    assert proc.returncode is not None  # guaranteed after wait()
    return proc.returncode


async def _run_capture(*cmd: str, timeout: int = _SUBPROCESS_TIMEOUT) -> tuple[int, str]:
    """Run a subprocess, capture stdout, and return (exit_code, stdout_text)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise
    assert proc.returncode is not None  # guaranteed after communicate()
    return proc.returncode, stdout.decode().strip()


class YtDlp(commands.Cog):
    LIMIT_BYTES = 10 * 1024 * 1024  # 10 MB Discord upload limit

    # ---------------------------------------------------------------------------
    # Cookies — two supported sources (both can coexist):
    #
    # 1. Local / dev:
    #    Set COOKIES_INSTAGRAM=cookies/instagram.txt (or any relative path).
    #
    # 2. Railway / secrets volume (/etc/secrets mount):
    #    Set COOKIES_INSTAGRAM=/etc/secrets/instagram.txt
    #    Then place the Netscape-format cookies file at that path in your volume.
    #
    # Variable naming: COOKIES_<PLATFORM> (uppercase), e.g.:
    #   COOKIES_INSTAGRAM=/etc/secrets/instagram.txt
    #   COOKIES_TIKTOK=/etc/secrets/tiktok.txt
    #   COOKIES_TWITTER=/etc/secrets/twitter.txt
    # ---------------------------------------------------------------------------

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _cookies_for(self, url: str) -> list[str]:
        """
        Return ['--cookies', '<path>'] if a COOKIES_<PLATFORM> env var is set,
        its file exists, and the platform name appears in the URL hostname.
        Otherwise return [] (no auth).
        """
        import re
        from urllib.parse import urlparse
        try:
            hostname = urlparse(url).hostname or ""
        except Exception:
            return []

        for key, path in os.environ.items():
            match = re.fullmatch(r"COOKIES_([A-Z0-9]+)", key)
            if not match:
                continue
            platform = match.group(1).lower()  # e.g. "instagram"
            if platform not in hostname:
                continue
            if not os.path.isfile(path):
                log.warning("Cookies file for %s not found at %s", platform, path)
                continue
            log.debug("Using cookies file %s for %s", path, url)
            return ["--cookies", path]

        return []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get_duration(self, path: str) -> float | None:
        """Return the duration of a media file in seconds, or None on failure."""
        _, output = await _run_capture(
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        )
        try:
            return float(output)
        except (ValueError, TypeError):
            log.warning("ffprobe could not determine duration for %s", path)
            return None

    async def _has_audio_stream(self, path: str) -> bool:
        """Return True if the file contains at least one audio stream."""
        _, output = await _run_capture(
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        )
        return bool(output)

    async def _compress_video(self, input_path: str) -> str | None:
        """
        Re-encode the video to fit within _COMPRESS_TARGET_MB using FFmpeg.
        Returns the path to the compressed file, or None if compression fails
        or the resulting bitrate would be unwatchably low.
        """
        duration = await self._get_duration(input_path)
        if duration is None:
            return None

        target_bits = _COMPRESS_TARGET_MB * 8 * 1024 * 1024
        video_bitrate = int(target_bits / duration) - 128_000  # reserve 128k for audio

        if video_bitrate < 100_000:
            log.warning("Calculated bitrate %d bps too low; skipping compression.", video_bitrate)
            return None

        output_path = input_path.replace(".mp4", "_compressed.mp4")
        code = await _run(
            "ffmpeg", "-y", "-i", input_path,
            "-b:v", str(video_bitrate),
            "-maxrate", str(video_bitrate),
            "-bufsize", str(video_bitrate * 2),
            "-vcodec", "libx264", "-preset", "veryfast",
            "-acodec", "aac", "-b:a", "128k",
            output_path,
        )

        if code != 0 or not os.path.exists(output_path):
            log.error("FFmpeg compression failed for %s (exit %d)", input_path, code)
            return None

        # Remove the uncompressed source to save temp-dir space
        try:
            os.remove(input_path)
        except OSError:
            pass

        return output_path

    async def _fetch_audio(self, url: str, tmp_dir: str) -> str | None:
        """Download audio and convert to MP3. Returns local path or None."""
        output_template = os.path.join(tmp_dir, "%(uploader)s – %(title)s.mp3")
        code = await _run(
            "yt-dlp", "-x",
            "--audio-format", "mp3",
            "--audio-quality", "5",
            "--no-playlist",
            *self._cookies_for(url),
            "-o", output_template,
            url,
        )
        if code != 0:
            log.error("yt-dlp audio download failed (exit %d) for %s", code, url)
            return None

        path = _find_file(tmp_dir, "mp3")
        if path is None:
            log.error("yt-dlp produced no MP3 file for %s", url)
        return path

    async def _fetch_video(self, url: str, tmp_dir: str) -> str | None:
        """
        Download video at the best resolution that fits within LIMIT_BYTES,
        trying resolutions from highest to lowest. Compresses at 480p as a
        last resort. Returns local path or None.
        """
        for height in _VIDEO_RESOLUTIONS:
            _clear_dir(tmp_dir)

            output_template = os.path.join(tmp_dir, "%(uploader)s – %(title)s.mp4")
            code = await _run(
                "yt-dlp",
                *self._cookies_for(url),
                "-f", (
                    f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]"
                    f"/bestvideo[height<={height}]+bestaudio"
                    f"/best[height<={height}]"
                ),
                "--merge-output-format", "mp4",
                "--audio-multistreams",
                "--postprocessor-args", "ffmpeg:-c:a aac",
                "--no-playlist",
                "-o", output_template,
                url,
            )

            path = _find_file(tmp_dir, "mp4")

            if code != 0 or path is None:
                log.warning("yt-dlp video download failed at %dp (exit %d)", height, code)
                continue

            if not await self._has_audio_stream(path):
                log.warning("Downloaded file has no audio stream at %dp; skipping.", height)
                continue

            size = os.path.getsize(path)
            if size <= self.LIMIT_BYTES:
                return path

            if height == _VIDEO_RESOLUTIONS[-1]:
                log.info("File too large at lowest resolution; attempting compression.")
                return await self._compress_video(path)

        return None

    # ------------------------------------------------------------------
    # Shared download handler
    # ------------------------------------------------------------------

    async def _handle_download(self, ctx: commands.Context, url: str, is_audio: bool) -> None:
        url = _normalize_url(url)
        if not is_public_http_url(url):
            await ctx.send("Please provide a public http(s) URL.")
            return

        kind = "Audio" if is_audio else "Video"
        start = time.perf_counter()

        async with ctx.typing():
            with tempfile.TemporaryDirectory() as tmp_dir:
                try:
                    if is_audio:
                        local_path = await self._fetch_audio(url, tmp_dir)
                    else:
                        local_path = await self._fetch_video(url, tmp_dir)
                except asyncio.TimeoutError:
                    await ctx.send(f"❌ **{kind} timed out.** The download took too long.")
                    return

                if not local_path or not os.path.exists(local_path):
                    await ctx.send(f"❌ **{kind} failed.** Content is unavailable or too large.")
                    return

                size_bytes = os.path.getsize(local_path)
                size_mb = size_bytes / (1024 * 1024)

                # Sanity check: compressed file may still exceed the limit
                if size_bytes > self.LIMIT_BYTES:
                    await ctx.send(f"⚠️ **{kind} ({size_mb:.1f} MB) exceeds the 10 MB limit.**")
                    return

                elapsed = time.perf_counter() - start
                await ctx.send(
                    content=f"✅ **{kind} Downloaded** • {elapsed:.2f}s • {size_mb:.1f} MB",
                    file=discord.File(local_path),
                )

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @commands.hybrid_command(
        name="download", aliases=["dl"],
        description="Download a video (1080p → 720p → 480p → compressed)",
    )
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def download_video(self, ctx: commands.Context, url: str) -> None:
        """Download a video at the best available resolution under 10 MB."""
        await self._handle_download(ctx, url, is_audio=False)

    @commands.hybrid_command(
        name="audio", aliases=["mp3"],
        description="Download a video as an MP3",
    )
    @app_commands.describe(url="URL of the video to extract audio from")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def download_audio(self, ctx: commands.Context, url: str) -> None:
        """Download and convert a video to MP3."""
        await self._handle_download(ctx, url, is_audio=True)

    @download_video.error
    @download_audio.error
    async def _dl_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Wait **{error.retry_after:.1f}s** before downloading again.",
                ephemeral=True,
                delete_after=10,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(YtDlp(bot))