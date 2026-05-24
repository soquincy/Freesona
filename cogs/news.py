# cogs/news.py: RSS/Atom news feed commands.

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from utils.rss import load_rss_feeds, save_rss_feed, delete_rss_feed, parse_feed
from utils.security import is_public_http_url


async def feed_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    current = current.lower()
    choices = []
    for name in sorted(load_rss_feeds()):
        if current in name:
            choices.append(app_commands.Choice(name=name, value=name))
    return choices[:25]


class NewsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_group(name="rss", invoke_without_command=True, help="Read and manage RSS news feeds.")
    async def rss_group(self, ctx):
        await ctx.send("Use `/rss list`, `/rss latest`, `/rss add`, or `/rss remove`.", ephemeral=True if ctx.interaction else False)

    @rss_group.command(name="list", help="List configured RSS feeds.")
    async def rss_list(self, ctx):
        feeds = load_rss_feeds()
        lines = [f"`{name}`: {url}" for name, url in sorted(feeds.items())]
        embed = discord.Embed(
            title="RSS Feeds",
            description="\n".join(lines)[:4096] or "No feeds configured.",
            color=discord.Color.blue(),
        )
        await ctx.send(embed=embed, ephemeral=True if ctx.interaction else False)

    @rss_group.command(name="latest", help="Show latest items from an RSS feed.")
    @app_commands.autocomplete(name=feed_autocomplete)
    async def rss_latest(self, ctx, name: str, limit: int = 5):
        feeds = load_rss_feeds()
        key = name.lower().strip()
        url = feeds.get(key)
        if not url:
            await ctx.send(f"Unknown RSS feed `{key}`. Use `/rss list`.", ephemeral=True if ctx.interaction else False)
            return

        limit = max(1, min(limit, 10))
        await ctx.defer(ephemeral=False)

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
                async with session.get(url, headers={"User-Agent": "FreesonaBot/1.0"}) as resp:
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

        embed = discord.Embed(title=f"Latest: {key}", url=url, color=discord.Color.blue())
        for item in items:
            value_parts = []
            if item.published:
                value_parts.append(item.published)
            if item.summary:
                value_parts.append(item.summary[:220])
            if item.link:
                value_parts.append(item.link)
            embed.add_field(name=item.title[:256], value="\n".join(value_parts)[:1024] or item.link, inline=False)
        await ctx.send(embed=embed)

    @rss_group.command(name="add", help="Add or update an RSS feed (Admin only).")
    @commands.has_permissions(administrator=True)
    async def rss_add(self, ctx, name: str, url: str):
        key = name.lower().strip()
        if not key.replace("-", "").replace("_", "").isalnum():
            await ctx.send("Feed name must use letters, numbers, dashes, or underscores.", ephemeral=True if ctx.interaction else False)
            return
        if not is_public_http_url(url):
            await ctx.send("Feed URL must be a public http(s) URL.", ephemeral=True if ctx.interaction else False)
            return
        save_rss_feed(key, url)
        await ctx.send(f"RSS feed `{key}` saved.", ephemeral=True if ctx.interaction else False)

    @rss_group.command(name="remove", help="Remove a custom RSS feed (Admin only).")
    @commands.has_permissions(administrator=True)
    @app_commands.autocomplete(name=feed_autocomplete)
    async def rss_remove(self, ctx, name: str):
        key = name.lower().strip()
        if delete_rss_feed(key):
            await ctx.send(f"RSS feed `{key}` removed.", ephemeral=True if ctx.interaction else False)
        else:
            await ctx.send(f"`{key}` is a built-in or unknown feed.", ephemeral=True if ctx.interaction else False)


async def setup(bot):
    await bot.add_cog(NewsCog(bot))
