# cogs/news.py: RSS/Atom news feed commands + auto-posting loop.

import asyncio
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.config import load_config, save_config
from utils.rss import (
    load_rss_feeds, save_rss_feed, delete_rss_feed,
    parse_feed, load_seen_links, mark_links_seen,
    DEFAULT_RSS_FEEDS, RSS_DISABLED_KEY,
)
from utils.security import is_public_http_url

logger = logging.getLogger("FreesonaBot")

POLL_INTERVAL_MINUTES = 15
RSS_CHANNEL_KEY       = "rss_channel_id"


async def feed_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current = current.lower()
    choices = []
    for name in sorted(load_rss_feeds()):
        if current in name:
            choices.append(app_commands.Choice(name=name, value=name))
    return choices[:25]


class NewsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.poll_feeds.start()

    async def cog_unload(self):
        self.poll_feeds.cancel()

    # -------------------------------------------------------------------
    # Background polling loop
    # -------------------------------------------------------------------

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def poll_feeds(self):
        await self.bot.wait_until_ready()

        config     = load_config()
        channel_id = config.get(RSS_CHANNEL_KEY)
        if not channel_id:
            return

        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        feeds    = load_rss_feeds(config)
        seen     = load_seen_links(config)
        new_links: list[str] = []

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=12)
        ) as session:
            for name, url in feeds.items():
                try:
                    async with session.get(
                        url, headers={"User-Agent": "FreesonaBot/1.0"}
                    ) as resp:
                        if resp.status >= 400:
                            logger.warning(f"RSS poll: {name} returned HTTP {resp.status}")
                            continue
                        xml_text = await resp.text()

                    items = parse_feed(xml_text, limit=10)

                    for item in items:
                        if not item.link or item.link in seen:
                            continue

                        embed = discord.Embed(
                            title=item.title[:256],
                            url=item.link,
                            color=discord.Color.blurple(),
                        )
                        if item.author:
                            embed.set_author(name=item.author[:256])
                        if item.summary:
                            embed.description = item.summary[:400]
                        if item.image_url:
                            embed.set_image(url=item.image_url)

                        footer_text = name
                        if item.published:
                            footer_text += f"  •  {item.published}"
                        embed.set_footer(text=footer_text)

                        try:
                            await channel.send(embed=embed)
                        except discord.Forbidden:
                            logger.error(f"RSS: missing send permission in channel {channel_id}")
                            return
                        except discord.HTTPException as e:
                            logger.warning(f"RSS: failed to send item from {name}: {e}")
                            continue

                        new_links.append(item.link)
                        seen.add(item.link)
                        await asyncio.sleep(0.5)  # avoid rate-limiting on burst posts

                except Exception as e:
                    logger.warning(f"RSS poll error for {name}: {e}")
                    continue

        if new_links:
            mark_links_seen(new_links)
            logger.info(f"RSS: posted {len(new_links)} new article(s)")

    @poll_feeds.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    # -------------------------------------------------------------------
    # /rss group
    # -------------------------------------------------------------------

    @commands.hybrid_group(
        name="rss",
        invoke_without_command=True,
        help="Read and manage RSS news feeds.",
    )
    async def rss_group(self, ctx):
        await ctx.send(
            "Use `/rss list`, `/rss latest`, `/rss add`, `/rss remove`, "
            "`/rss setchannel`, or `/rss clearchannel`.",
            ephemeral=True if ctx.interaction else False,
        )

    @rss_group.command(name="setchannel", help="Set the channel for auto-posted RSS articles (Admin only).")
    @commands.has_permissions(administrator=True)
    async def rss_setchannel(self, ctx, channel: discord.TextChannel):
        config = load_config()
        config[RSS_CHANNEL_KEY] = channel.id
        save_config(config)
        await ctx.send(
            f"RSS articles will be posted to {channel.mention} every {POLL_INTERVAL_MINUTES} minutes.",
            ephemeral=True if ctx.interaction else False,
        )

    @rss_group.command(name="clearchannel", help="Stop auto-posting RSS articles (Admin only).")
    @commands.has_permissions(administrator=True)
    async def rss_clearchannel(self, ctx):
        config = load_config()
        config.pop(RSS_CHANNEL_KEY, None)
        save_config(config)
        await ctx.send("RSS auto-posting disabled.", ephemeral=True if ctx.interaction else False)

    @rss_group.command(name="list", help="List all configured RSS feeds.")
    async def rss_list(self, ctx):
        config  = load_config()
        feeds   = load_rss_feeds(config)
        channel_id = config.get(RSS_CHANNEL_KEY)
        channel_mention = f"<#{channel_id}>" if channel_id else "*(not set — use `/rss setchannel`)*"

        lines = [f"`{name}`: {url}" for name, url in sorted(feeds.items())]
        embed = discord.Embed(
            title="RSS Feeds",
            description="\n".join(lines)[:4096] or "No feeds configured.",
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"Auto-post channel: {channel_mention}")
        await ctx.send(embed=embed, ephemeral=True if ctx.interaction else False)

    @rss_group.command(name="latest", help="Show latest items from an RSS feed.")
    @app_commands.autocomplete(name=feed_autocomplete)
    async def rss_latest(self, ctx, name: str, limit: int = 5):
        feeds = load_rss_feeds()
        key   = name.lower().strip()
        url   = feeds.get(key)
        if not url:
            await ctx.send(
                f"Unknown RSS feed `{key}`. Use `/rss list`.",
                ephemeral=True if ctx.interaction else False,
            )
            return

        limit = max(1, min(limit, 10))
        await ctx.defer(ephemeral=False)

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=12)
            ) as session:
                async with session.get(
                    url, headers={"User-Agent": "FreesonaBot/1.0"}
                ) as resp:
                    if resp.status >= 400:
                        await ctx.send(f"Feed returned HTTP {resp.status}.")
                        return
                    xml_text = await resp.text()
            items = parse_feed(xml_text, limit=limit)
        except Exception as e:
            await ctx.send(f"Could not read feed `{key}`: {e}")
            return

        if not items:
            await ctx.send(f"No items found in `{key}`.")
            return

        # Discord permits sending an array of up to 10 embeds in one message.
        # This renders images and bylines neatly for every item.
        embeds = []
        for item in items:
            embed = discord.Embed(
                title=item.title[:256],
                url=item.link,
                color=discord.Color.blue(),
            )
            if item.author:
                embed.set_author(name=item.author[:256])
            if item.summary:
                embed.description = item.summary[:400]
            if item.image_url:
                embed.set_image(url=item.image_url)

            footer_text = key
            if item.published:
                footer_text += f"  •  {item.published}"
            embed.set_footer(text=footer_text)
            embeds.append(embed)

        await ctx.send(embeds=embeds)

    @rss_group.command(name="add", help="Add or update an RSS feed (Admin only).")
    @commands.has_permissions(administrator=True)
    async def rss_add(self, ctx, name: str, url: str):
        key = name.lower().strip()
        if not key.replace("-", "").replace("_", "").isalnum():
            await ctx.send(
                "Feed name must use letters, numbers, dashes, or underscores.",
                ephemeral=True if ctx.interaction else False,
            )
            return
        if not is_public_http_url(url):
            await ctx.send(
                "Feed URL must be a public http(s) URL.",
                ephemeral=True if ctx.interaction else False,
            )
            return
        save_rss_feed(key, url)
        await ctx.send(f"RSS feed `{key}` saved.", ephemeral=True if ctx.interaction else False)

    @rss_group.command(name="remove", help="Remove an RSS feed (Admin only). Built-in feeds can also be removed.")
    @commands.has_permissions(administrator=True)
    @app_commands.autocomplete(name=feed_autocomplete)
    async def rss_remove(self, ctx, name: str):
        key = name.lower().strip()
        if delete_rss_feed(key):
            await ctx.send(f"RSS feed `{key}` removed.", ephemeral=True if ctx.interaction else False)
        else:
            await ctx.send(f"No feed named `{key}` found.", ephemeral=True if ctx.interaction else False)

    @rss_group.command(name="defaults", help="Toggle built-in RSS feeds on or off (Admin only).")
    @commands.has_permissions(administrator=True)
    async def rss_defaults(self, ctx):
        config   = load_config()
        disabled = set(config.get(RSS_DISABLED_KEY, []))

        lines = []
        for name in sorted(DEFAULT_RSS_FEEDS):
            status = "🔴 off" if name in disabled else "🟢 on"
            lines.append(f"`{name}` — {status}")

        embed = discord.Embed(
            title="Built-in RSS Feeds",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Use /rss remove <name> to disable · /rss add <name> <url> to re-enable")
        await ctx.send(embed=embed, ephemeral=True if ctx.interaction else False)

    @rss_group.command(name="toggledefault", help="Enable or disable a built-in RSS feed (Admin only).")
    @commands.has_permissions(administrator=True)
    @app_commands.describe(name="The built-in feed to toggle.")
    async def rss_toggledefault(self, ctx, name: str):
        key = name.lower().strip()
        if key not in DEFAULT_RSS_FEEDS:
            await ctx.send(
                f"`{key}` is not a built-in feed. Use `/rss defaults` to see the list.",
                ephemeral=True if ctx.interaction else False,
            )
            return

        config   = load_config()
        disabled: list = config.setdefault(RSS_DISABLED_KEY, [])

        if key in disabled:
            disabled.remove(key)
            save_config(config)
            await ctx.send(f"✅ Built-in feed `{key}` **enabled**.", ephemeral=True if ctx.interaction else False)
        else:
            disabled.append(key)
            save_config(config)
            await ctx.send(f"🔴 Built-in feed `{key}` **disabled**.", ephemeral=True if ctx.interaction else False)


async def setup(bot):
    await bot.add_cog(NewsCog(bot))