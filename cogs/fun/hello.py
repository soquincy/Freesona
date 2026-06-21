# cogs/fun/hello.py: Simple response and sample logic for future commands.
# This is for my sanity and to make sure the bot is responding to commands properly.
# It also serves as a template for future commands, so I don't have to keep writing the same boilerplate code over and over again.

from discord.ext import commands

class HelloCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='hello', help='Says hello back!')
    async def hello_cmd(self, ctx):
        await ctx.send(f"Hello {ctx.author.mention}!")

async def setup(bot):
    await bot.add_cog(HelloCog(bot))