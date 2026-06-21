# Adapted from the Python Discord bot project
# https://github.com/python-discord/bot
# Copyright (c) 2018 Python Discord
# Licensed under the MIT License

# cogs/ping.py: Ping command

import time
import aiohttp
import discord

from discord.ext import commands

ROUND_LATENCY = 3


class PingCog(commands.Cog):
    """Shows latency and API status."""

    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(
        name="ping",
        help="Shows the bot latency and Discord API latency."
    )
    async def ping(self, ctx):
        await ctx.defer()

        # Message processing latency
        bot_ping = (
            discord.utils.utcnow() - ctx.message.created_at
        ).total_seconds() * 1000

        # Discord websocket latency
        discord_ping = self.bot.latency * 1000

        # Optional internet/API test
        api_status = "Unknown"

        try:
            start = time.perf_counter()

            async with aiohttp.ClientSession() as session:
                async with session.get("https://discord.com/api/v10/gateway") as response:
                    end = time.perf_counter()

                    if response.status == 200:
                        api_status = f"Online ({(end - start) * 1000:.{ROUND_LATENCY}f} ms)"
                    else:
                        api_status = f"HTTP {response.status}"

        except Exception as e:
            api_status = f"Error: {type(e).__name__}"

        embed = discord.Embed(
            title="🏓 Pong!",
            color=discord.Color.green()
        )

        embed.add_field(
            name="Bot Response",
            value=f"{bot_ping:.{ROUND_LATENCY}f} ms",
            inline=False
        )

        embed.add_field(
            name="Discord Gateway",
            value=f"{discord_ping:.{ROUND_LATENCY}f} ms",
            inline=False
        )

        embed.add_field(
            name="API Status",
            value=api_status,
            inline=False
        )

        embed.set_footer(text=f"Requested by {ctx.author}")

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(PingCog(bot))