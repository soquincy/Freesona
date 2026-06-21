# cogs/fun/random.py - Fun commands that involve randomness, like picking a random member, flipping a coin, rolling a die, or picking from a list of choices.

import secrets

from discord.ext import commands


class RandomCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(
        name='randommember',
        help='Randomly selects a server member.'
    )
    @commands.has_permissions(mention_everyone=True)
    @commands.cooldown(1, 60, commands.BucketType.guild)
    async def random_member_cmd(self, ctx):
        members = [member for member in ctx.guild.members if not member.bot]

        if not members:
            await ctx.send("No eligible members found.")
            return

        selected = secrets.choice(members)

        await ctx.send(
            f"Randomly selected member: {selected.mention}"
        )

    @commands.hybrid_command(
        name='coinflip',
        help='Flips a coin.'
    )
    async def coinflip_cmd(self, ctx):
        result = secrets.choice(['Heads', 'Tails'])

        await ctx.send(f"🪙 {result}")

    @commands.hybrid_command(
        name='roll',
        help='Rolls a die.'
    )
    async def roll_cmd(self, ctx, sides: int = 6):
        if sides < 2:
            await ctx.send("Die must have at least 2 sides.")
            return

        result = secrets.randbelow(sides) + 1

        await ctx.send(f"🎲 Rolled: {result}")

    @commands.hybrid_command(
        name='pick',
        help='Randomly picks from choices separated by commas.'
    )
    async def pick_cmd(self, ctx, *, choices: str):
        items = [
            item.strip()
            for item in choices.split(',')
            if item.strip()
        ]

        if len(items) < 2:
            await ctx.send(
                "Provide at least 2 choices separated by commas."
            )
            return

        selected = secrets.choice(items)

        await ctx.send(f"Selected: **{selected}**")

async def setup(bot):
    await bot.add_cog(RandomCog(bot))