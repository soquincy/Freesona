# cogs/news.py: RSS/Atom news feed commands + auto-posting loop.

import os
import asyncio
import logging
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from urllib.parse import urlparse

from utils.config import load_config, save_config
from utils.rss import (
    load_rss_feeds, save_rss_feed, delete_rss_feed,
    parse_feed, load_seen_links, mark_links_seen,
    DEFAULT_RSS_FEEDS, RSS_DISABLED_KEY,
)
from utils.security import is_public_http_url

logger = logging.getLogger("FreesonaBot")

POLL_INTERVAL_MINUTES = 5
RSS_CHANNELS_KEY = "rss_channels"  # Dict of {guild_id: channel_id}

async def feed_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    current = current.lower()
    choices = []
    for name in sorted(load_rss_feeds()):
        if current in name:
            choices.append(app_commands.Choice(name=name, value=name))
    return choices[:25]

def get_logo_url(article_link: str) -> str:
    """Extracts base domain and returns LogoKit URL with environment-based token."""
    if not article_link:
        return ""
    
    token = os.getenv("LOGOKIT_TOKEN")
    if not token:
        logger.warning("LOGOKIT_TOKEN is missing from environment variables.")
        return ""

    # Clean the token of any potential surrounding quotes or whitespace common in VPS/Docker envs
    token = token.strip().strip("'\"")
    if not token:
        return ""

    try:
        hostname = urlparse(article_link).netloc.lower()
        # Strip port if present
        if ":" in hostname:
            hostname = hostname.split(":")[0]
            
        parts = hostname.split('.')
        if len(parts) < 2:
            return ""
            
        # Logic to handle second-level domains like .co.uk
        if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "edu", "ac"):
            domain = ".".join(parts[-3:])
        else:
            domain = ".".join(parts[-2:])
            
        return f"https://img.logokit.com/{domain}?token={token}"
    except Exception:
        return ""

class NewsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.poll_feeds.start()

    async def cog_unload(self):
        self.poll_feeds.cancel()

    def _build_news_embed(self, item, name: str):
        """Standardized embed builder with LogoKit footer icon."""
        logo_url = get_logo_url(item.link)
        
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
        
        if logo_url:
            embed.set_footer(text=footer_text, icon_url=logo_url)
        else:
            embed.set_footer(text=footer_text)
        return embed

    @tasks.loop(minutes=POLL_INTERVAL_MINUTES)
    async def poll_feeds(self):
        await self.bot.wait_until_ready()

        config = load_config()
        rss_channels = config.get(RSS_CHANNELS_KEY, {})
        if not rss_channels:
            return

        feeds = load_rss_feeds(config)
        seen = load_seen_links(config)
        new_links: list[str] = []

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
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
                        if not item.link:
                            continue
                            
                        # Resolve relative links using the feed's base URL
                        if not urlparse(item.link).netloc:
                            from urllib.parse import urljoin
                            item.link = urljoin(url, item.link)

                        if item.link in seen:
                            continue

                        embed = self._build_news_embed(item, name)

                        for guild_id_str, channel_id in rss_channels.items():
                            # Ensure channel_id is an int for get_channel
                            channel = self.bot.get_channel(int(channel_id))
                            if not isinstance(channel, discord.TextChannel):
                                continue

                            try:
                                await channel.send(embed=embed)
                            except discord.Forbidden:
                                logger.error(f"RSS: Permission denied in guild {guild_id_str}")
                                continue
                            except discord.HTTPException as e:
                                logger.warning(f"RSS: Failed to send item from {name}: {e}")
                                continue

                        new_links.append(item.link)
                        seen.add(item.link)
                        await asyncio.sleep(0.5)

                except Exception as e:
                    logger.warning(f"RSS poll error for {name}: {e}")
                    continue

        if new_links:
            mark_links_seen(new_links)
            logger.info(f"RSS: posted {len(new_links)} new article(s)")

    @poll_feeds.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

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

    @rss_group.command(name="setchannel", help="Set the channel for auto-posts (Admin only).")
    @commands.has_permissions(administrator=True)
    async def rss_setchannel(self, ctx, channel: discord.TextChannel):
        config = load_config()
        channels = config.setdefault(RSS_CHANNELS_KEY, {})
        channels[str(ctx.guild.id)] = channel.id
        save_config(config)
        await ctx.send(f"RSS articles will post to {channel.mention}.", ephemeral=True)

    @rss_group.command(name="clearchannel", help="Stop auto-posting RSS (Admin only).")
    @commands.has_permissions(administrator=True)
    async def rss_clearchannel(self, ctx):
        config = load_config()
        channels = config.get(RSS_CHANNELS_KEY, {})
        if str(ctx.guild.id) in channels:
            del channels[str(ctx.guild.id)]
            save_config(config)
            await ctx.send("RSS auto-posting disabled.", ephemeral=True)
        else:
            await ctx.send("No RSS channel configured.", ephemeral=True)

    @rss_group.command(name="list", help="List all configured RSS feeds.")
    async def rss_list(self, ctx):
        config = load_config()
        feeds = load_rss_feeds(config)
        channels = config.get(RSS_CHANNELS_KEY, {})
        channel_id = channels.get(str(ctx.guild.id))
        channel_mention = f"<#{channel_id}>" if channel_id else "*(not set)*"

        lines = [f"`{name}`: {url}" for name, url in sorted(feeds.items())]
        embed = discord.Embed(
            title="RSS Feeds",
            description="\n".join(lines)[:4096] or "No feeds configured.",
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"Auto-post channel: {channel_mention}")
        await ctx.send(embed=embed, ephemeral=True)

    @rss_group.command(name="latest", help="Show latest items from an RSS feed.")
    @app_commands.autocomplete(name=feed_autocomplete)
    async def rss_latest(self, ctx, name: str, limit: int = 5):
        feeds = load_rss_feeds()
        key = name.lower().strip()
        url = feeds.get(key)
        if not url:
            await ctx.send(f"Unknown RSS feed `{key}`.", ephemeral=True)
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
            for item in items:
                if item.link and not urlparse(item.link).netloc:
                    from urllib.parse import urljoin
                    item.link = urljoin(url, item.link)
        except Exception as e:
            await ctx.send(f"Could not read feed `{key}`: {e}")
            return

        if not items:
            await ctx.send(f"No items found.")
            return

        embeds = [self._build_news_embed(item, key) for item in items]
        await ctx.send(embeds=embeds)

    @rss_group.command(name="add", help="Add or update an RSS feed (Admin only).")
    @commands.has_permissions(administrator=True)
    async def rss_add(self, ctx, name: str, url: str):
        key = name.lower().strip()
        if not key.replace("-", "").replace("_", "").isalnum():
            await ctx.send("Invalid name format.", ephemeral=True)
            return
        if not is_public_http_url(url):
            await ctx.send("Invalid URL.", ephemeral=True)
            return
        save_rss_feed(key, url)
        await ctx.send(f"RSS feed `{key}` saved.", ephemeral=True)

    @rss_group.command(name="remove", help="Remove an RSS feed (Admin only).")
    @commands.has_permissions(administrator=True)
    @app_commands.autocomplete(name=feed_autocomplete)
    async def rss_remove(self, ctx, name: str):
        key = name.lower().strip()
        if delete_rss_feed(key):
            await ctx.send(f"RSS feed `{key}` removed.", ephemeral=True)
        else:
            await ctx.send(f"Feed `{key}` not found.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(NewsCog(bot))