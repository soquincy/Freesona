# cogs/help.py: Help index
# Obviosly if you need help this is the cog to go to. Lolz.

import os
import discord
from typing import Optional
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

BOT_NAME = os.getenv("BOT_NAME", "Bot")

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='help', help='Shows help information for commands.')
    @app_commands.describe(command_name="The name of the command you want details for.")
    async def help_cmd(self, ctx, *, command_name: Optional[str] = None):
        await ctx.defer()

        prefix = self.bot.command_prefix
        if callable(prefix):
            prefix = prefix(self.bot, ctx.message)

        if not command_name:
            embed = discord.Embed(
                title=f"{BOT_NAME}'s Command List!",
                description=f"Use `{prefix}help <command_name>` for more details on a specific command.",
                color=discord.Color.random()
            )
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

            fun_cmds = []
            mod_cmds = []
            util_cmds = []
            media_cmds = []
            ai_cmds = []
            news_cmds = []

            for cmd in self.bot.commands:
                if cmd.hidden:
                    continue

                if cmd.name in ['hello', 'write', 'ask', 'today']:
                    fun_cmds.append(f"`{cmd.name}` - {cmd.help or 'No description'}")
                elif cmd.name in ['kick', 'purge', 'removetimeout', 'timeout', 'ban', 'unban']:
                    mod_cmds.append(f"`{cmd.name}` - {cmd.help or 'No description'}")
                elif cmd.name in ['math', 'search', 'help', 'ping']:
                    util_cmds.append(f"`{cmd.name}` - {cmd.help or 'No description'}")
                elif cmd.name in ['download', 'audio', 'separate']:
                    media_cmds.append(f"`{cmd.name}` - {cmd.help or 'No description'}")
                elif cmd.name in ['rss']:
                    news_cmds.append(f"`{cmd.name}` - {cmd.help or 'No description'}")
                elif cmd.name in [
                    'personalock', 'personaunlock', 'personasave',
                    'personaload', 'personalist', 'personadelete',
                    'debugpersona', 'setchannel', 'clearchannel', 'clearmemory',
                    'memorylist', 'memoryclear', 'chatmode', 'model', 'module',
                ]:
                    ai_cmds.append(f"`{cmd.name}` - {cmd.help or 'No description'}")

            if fun_cmds:
                embed.add_field(name="🎉 Fun & Info", value="\n".join(fun_cmds), inline=False)
            if media_cmds:
                embed.add_field(name="📥 Media", value="\n".join(media_cmds), inline=False)
            if mod_cmds:
                embed.add_field(name="🛡️ Moderation", value="\n".join(mod_cmds), inline=False)
            if util_cmds:
                embed.add_field(name="🔧 Utility", value="\n".join(util_cmds), inline=False)
            if news_cmds:
                embed.add_field(
                    name="📰 News",
                    value=(
                        "`/rss list` — List all feeds\n"
                        "`/rss latest <name>` — Fetch latest articles\n"
                        "`/rss add <name> <url>` — Add a feed *(Admin)*\n"
                        "`/rss remove <name>` — Remove a feed *(Admin)*\n"
                        "`/rss defaults` — View built-in feed status *(Admin)*\n"
                        "`/rss toggledefault <name>` — Enable/disable a built-in *(Admin)*\n"
                        "`/rss setchannel <#channel>` — Set auto-post channel *(Admin)*\n"
                        "`/rss clearchannel` — Stop auto-posting *(Admin)*"
                    ),
                    inline=False,
                )
            if ai_cmds:
                embed.add_field(
                    name="🤖 AI Persona",
                    value=(
                        "\n".join(ai_cmds)
                        + "\n`/setpersona` — Open persona editor (Owner only)"
                        + "\n`/autonomy on` `/autonomy off` `/autonomy frequency` — Autonomous mode (Admin only)"
                    ),
                    inline=False
                )

            embed.set_footer(text=f"Current prefix: {prefix}")
            await ctx.send(embed=embed)

        else:
            command = self.bot.get_command(command_name.lower())
            if command and not command.hidden:
                usage = f"`{prefix}{command.qualified_name}"
                params = []
                for name, param in command.params.items():
                    if name in ('self', 'ctx'):
                        continue
                    if param.kind == param.VAR_POSITIONAL:
                        params.append(f"<{name}...>")
                    elif param.default is param.empty:
                        params.append(f"<{name}>")
                    else:
                        params.append(f"[{name}]")
                usage += (" " + " ".join(params) if params else "") + "`"

                embed = discord.Embed(
                    title=f"Help: `{prefix}{command.name}`",
                    description=command.help or "No description provided.",
                    color=discord.Color.green()
                )
                embed.add_field(name="Usage", value=usage, inline=False)

                if command.aliases:
                    aliases = ", ".join([f"`{prefix}{a}`" for a in command.aliases])
                    embed.add_field(name="Aliases", value=aliases, inline=False)

                if command._buckets and command._buckets._cooldown:
                    cd = command._buckets._cooldown
                    embed.add_field(name="Cooldown", value=f"{cd.rate} time(s) per {cd.per:.0f} seconds", inline=False)

                perm_names = []
                checks = getattr(command.callback, '__commands_checks__', [])
                for check in checks:
                    if 'has_permissions' in str(check):
                        try:
                            required_perms = [p for p, v in check.__closure__[0].cell_contents.items() if v]
                            perm_names.extend(p.replace('_', ' ').title() for p in required_perms)
                        except Exception:
                            pass
                    elif 'is_owner' in str(check):
                        perm_names.append("Bot Owner")

                if perm_names:
                    embed.add_field(name="Permissions", value=", ".join(perm_names), inline=False)

                await ctx.send(embed=embed)
            else:
                await ctx.send(f"No command named `{command_name}` found. Try `{prefix}help` for the full list.")

async def setup(bot):
    await bot.add_cog(HelpCog(bot))