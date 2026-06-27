# cogs/ai/chroma.py: ChromaDB Cog for Discord bot to search a local knowledge base.
import discord
from discord.ext import commands

from utils.chroma import query_knowledge


class ChromaCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="kbsearch", help="Search the local knowledge base.")
    async def kbsearch(self, ctx, *, query: str):
        await ctx.defer(ephemeral=True)
        matches = query_knowledge(query, limit=5)
        if not matches:
            await ctx.send("No knowledge base matches found.", ephemeral=True)
            return
        lines = [f"- {item}" for item in matches]
        await ctx.send("\n".join(lines[:10]), ephemeral=True)


async def setup(bot):
    await bot.add_cog(ChromaCog(bot))
