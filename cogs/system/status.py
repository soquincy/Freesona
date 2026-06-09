# cogs/status.py: Discord status modifier and changes text status every 5 mins to the servers it has joined (if multiple.)
# May add "watching X servers" or something like that if it only has one server or I could make it catch random quotes. Who knows.

import discord
from discord.ext import commands, tasks

class StatusCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.index = 0
        self.update_status.start()

    async def cog_unload(self):
        self.update_status.cancel()

    @tasks.loop(minutes=5)
    async def update_status(self):
        await self.bot.wait_until_ready()
        
        guilds = self.bot.guilds
        if not guilds:
            return

        # Ensure the index doesn't go out of bounds if the bot leaves a server
        if self.index >= len(guilds):
            self.index = 0

        server_name = guilds[self.index].name
        
        await self.bot.change_presence(
            status=discord.Status.dnd,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=server_name
            )
        )

        # Move to the next server for the next 5-minute update
        self.index += 1

    @update_status.before_loop
    async def before_update_status(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(StatusCog(bot))
