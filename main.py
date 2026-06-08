# main.py: Main code that loads the cogs and makes the bot run. Also contains the prefix command and the on_ready event that sends a message to the specified channel when the bot starts up. The bot also starts a FastAPI server in the background for future webhooks and health checks.

import discord
from discord.ext import commands
from discord import abc
import os
import logging
import asyncio
import uvicorn
from fastapi_server import app
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

from utils.config import load_config, save_config
from utils.modules import CORE_EXTENSIONS, OPTIONAL_MODULES, load_enabled_modules

# --- Configuration & Persistence Setup ---
bot_token = os.getenv("BOT_TOKEN")
channel_id_str = os.getenv("CHANNEL_ID")

if not bot_token or not channel_id_str:
    raise ValueError("Missing BOT_TOKEN or CHANNEL_ID in environment variables")

try:
    CHANNEL_ID = int(channel_id_str)
except ValueError:
    raise ValueError("CHANNEL_ID must be an integer")

def get_prefix(bot, message):
    """Reads the prefix from the persistent JSON file."""
    return load_config().get("prefix", "~")

# --- Bot Class Definition ---
class Freesona(commands.Bot):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._legacy_notice_sent = False  # guard: only DM once per session

    async def setup_hook(self):
        config = load_config()
        enabled_modules = load_enabled_modules(config)
        extensions = CORE_EXTENSIONS + [
            ext for name, ext in OPTIONAL_MODULES.items()
            if enabled_modules.get(name, True)
        ]

        for ext in extensions:
            try:
                await self.load_extension(ext)
            except Exception as e:
                logger.error(f"Failed to load extension {ext}: {e}")

        await self.tree.sync()
        print(f"Synced slash commands for {self.user}")

    async def notify_owner_legacy(self, bot_name: str):
        """DM the bot owner about legacy persona.txt — called from genai cog."""
        if self._legacy_notice_sent:
            return
        self._legacy_notice_sent = True
        try:
            info = await self.application_info()
            owner = info.owner
            await owner.send(
                f"⚠️ **{bot_name} detected a legacy `persona.txt` file.**\n\n"
                f"The persona system now uses a structured `persona.json` format. "
                f"Your existing persona is still active, but to use the new structured editor, "
                f"you'll need to migrate your content into the new fields.\n\n"
                f"Use `/setpersona core` and `/setpersona style` to set up the new format. "
                f"Once saved, `persona.json` will take over and `persona.txt` can be removed.\n\n"
                f"You can also run `/debugpersona` to confirm your current state."
            )
        except Exception as e:
            logging.getLogger(__name__).warning(f"Could not DM owner for legacy persona notice: {e}")

# Initialize Bot
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.dm_messages = True
intents.guilds = True

bot = Freesona(command_prefix=get_prefix, intents=intents)
bot.remove_command('help')

logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(name)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Commands & Events ---
@bot.hybrid_command(name="prefix", description="Changes the bot prefix and saves it to config.json")
@commands.has_permissions(administrator=True)
async def change_prefix(ctx, new_prefix: str):
    try:
        config = load_config()
        config["prefix"] = new_prefix
        save_config(config)
        await ctx.send(f"Prefix updated to: `{new_prefix}`")
    except Exception as e:
        logger.error(f"Failed to save prefix: {e}")
        await ctx.send("Error saving prefix to persistent storage.")

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')

    channel = bot.get_channel(CHANNEL_ID)
    if isinstance(channel, abc.Messageable):
        bot_name = os.getenv("BOT_NAME", "Bot")
        try:
            current_p = get_prefix(bot, None)
            await channel.send(
                f"Heya! {bot_name} here! Current prefix is `{current_p}`. "
                "For fresh info, use `search <query>`."
            )
        except Exception as e:
            logger.warning(f"Failed to send startup message: {e}")

    # Trigger legacy persona DM if needed — deferred here so bot is fully ready
    try:
        from cogs.genai import LEGACY_DETECTED, BOT_NAME as GENAI_BOT_NAME
        if LEGACY_DETECTED:
            await bot.notify_owner_legacy(GENAI_BOT_NAME)
    except Exception as e:
        logger.warning(f"Legacy check failed: {e}")

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        cmd = ctx.command
        prefix = ctx.prefix
        embed = discord.Embed(
            title=f"Help: `{prefix}{cmd.name}`" + (f" (alias: `{prefix}{ctx.invoked_with}`)" if ctx.invoked_with != cmd.name else ""),
            description=cmd.help or "No description provided.",
            color=discord.Color.green()
        )
        if cmd.usage:
            embed.add_field(name="Usage", value=f"`{prefix}{cmd.name} {cmd.usage}`", inline=False)
        if cmd.aliases:
            embed.add_field(name="Aliases", value=", ".join(f"`{prefix}{a}`" for a in cmd.aliases), inline=False)
        await ctx.send(embed=embed)
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command.")
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send("I don't have permission to do that.")
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"Cooldown. Try again in {error.retry_after:.1f}s.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"Invalid argument: {error}")

# --- Background Tasks & Execution ---
async def start_http():
    config = uvicorn.Config(app, host="0.0.0.0", port=10000, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()

async def start_bot():
    await bot.start(str(bot_token))

async def main():
    await asyncio.gather(
        start_http(),
        start_bot()
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped.")
        
