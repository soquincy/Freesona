# cogs/help.py: Help index
# Obviosly if you need help this is the cog to go to. Lolz.
# Buttons. Yay!

import logging
import os
import discord
from typing import Optional
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()

BOT_NAME = os.getenv("BOT_NAME", "Bot")
logger = logging.getLogger(__name__)


def _split_embed_text(text: str, limit: int = 1024) -> list[str]:
    """Split long help text into Discord-safe chunks."""
    lines = text.splitlines()
    chunks = []
    current = ""

    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            if current:
                chunks.append(current)
                current = line
            else:
                chunks.append(candidate[:limit])
                current = candidate[limit:]
                if current.startswith("\n"):
                    current = current[1:]
        else:
            current = candidate

    if current:
        chunks.append(current)

    return chunks or [text[:limit]]


class HelpView(discord.ui.View):
    def __init__(self, bot, ctx, categories, prefix):
        super().__init__(timeout=None)
        self.bot = bot
        self.ctx = ctx
        self.categories = categories
        self.prefix = prefix
        self.current_category = None
        self.page_index = 0

    async def update_help(self, interaction: discord.Interaction, category: str, page: int = 0):
        try:
            await interaction.response.defer()

            embed = discord.Embed(
                title=f"{category} Commands",
                description=f"Detailed help for {BOT_NAME}'s {category.lower()} features.",
                color=discord.Color.blue()
            )

            user = getattr(self.bot, "user", None)
            avatar = getattr(getattr(user, "display_avatar", None), "url", None)
            if avatar:
                embed.set_thumbnail(url=avatar)

            content = self.categories.get(category, "No commands found.")
            chunks = _split_embed_text(content)
            self.current_category = category
            self.page_index = max(0, min(page, len(chunks) - 1))

            embed.add_field(name="Commands", value=chunks[self.page_index], inline=False)
            if len(chunks) > 1:
                embed.set_footer(text=f"Page {self.page_index + 1}/{len(chunks)} • Use {self.prefix}help <command> for specifics.")
            else:
                embed.set_footer(text=f"Use {self.prefix}help <command> for specifics.")

            self.prev_button.disabled = self.page_index == 0
            self.next_button.disabled = self.page_index >= len(chunks) - 1

            message = interaction.message
            if message is not None:
                await message.edit(embed=embed, view=self)
            else:
                await interaction.followup.send(embed=embed, view=self)
        except Exception:
            logger.exception("Help button interaction failed for category %s", category)
            if not interaction.response.is_done():
                await interaction.response.send_message("The help panel could not be updated right now.", ephemeral=True)

    @discord.ui.button(label="AI & Persona", style=discord.ButtonStyle.primary, emoji="🤖")
    async def ai_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_help(interaction, "AI Persona")

    @discord.ui.button(label="Media", style=discord.ButtonStyle.secondary, emoji="📥")
    async def media_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_help(interaction, "Media")

    @discord.ui.button(label="News/RSS", style=discord.ButtonStyle.secondary, emoji="📰")
    async def news_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_help(interaction, "News")

    @discord.ui.button(label="Utility", style=discord.ButtonStyle.secondary, emoji="🔧")
    async def util_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_help(interaction, "Utility")

    @discord.ui.button(label="Fun", style=discord.ButtonStyle.success, emoji="🎲")
    async def fun_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_help(interaction, "Fun")

    @discord.ui.button(label="Moderation", style=discord.ButtonStyle.danger, emoji="🛡️")
    async def mod_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.update_help(interaction, "Moderation")

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_category and self.page_index > 0:
            await self.update_help(interaction, self.current_category, self.page_index - 1)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_category:
            content = self.categories.get(self.current_category, "")
            total_pages = len(_split_embed_text(content))
            if self.page_index < total_pages - 1:
                await self.update_help(interaction, self.current_category, self.page_index + 1)

class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='help', help='Shows help information for commands.')
    @app_commands.describe(command_name="The name of the command you want details for.")
    async def help_cmd(self, ctx, *, command_name: Optional[str] = None):
        prefix = self.bot.command_prefix
        if callable(prefix):
            prefix = prefix(self.bot, ctx.message)

        if not command_name:
            cats = {
                "Fun": [], "Moderation": [], "Utility": [],
                "Media": [], "AI Persona": [], "News": []
            }

            for cmd in self.bot.commands:
                if cmd.hidden:
                    continue

                entry = f"`{cmd.name}` - {cmd.help or 'No description'}"

                if cmd.name in ['hello', 'write', 'ask', 'randommember', 'coinflip', 'roll', 'pick']:
                    cats["Fun"].append(entry)
                elif cmd.name in ['kick', 'purge', 'removetimeout', 'timeout', 'ban', 'unban']:
                    cats["Moderation"].append(entry)
                elif cmd.name in ['math', 'search', 'help', 'ping']:
                    cats["Utility"].append(entry)
                elif cmd.name in ['download', 'audio', 'separate']:
                    cats["Media"].append(entry)
                elif cmd.name == 'rss':
                    cats["News"].append("`/rss list`, `/rss latest`, `/rss add`, `/rss setchannel`...")
                elif cmd.name in [
                    'personalock', 'personaunlock', 'personasave', 'personaload',
                    'personalist', 'personadelete', 'debugpersona', 'setchannel',
                    'clearchannel', 'clearmemory', 'memorylist', 'memorydelete',
                    'migrate', 'chatmode', 'botwhitelist', 'model', 'module'
                ]:
                    cats["AI Persona"].append(entry)

            formatted_cats = {k: "\n".join(v) if v else "None" for k, v in cats.items()}

            formatted_cats["AI Persona"] += (
                "\n`/setpersona` — Persona editor\n"
                "`/autonomy` — Auto-mode\n"
                "`/botwhitelist` — Manage bot whitelist"
            )
            formatted_cats["News"] = (
                "`/rss list` — List feeds\n`/rss latest <name>` — Fetch articles\n"
                "`/rss add <name> <url>` — Add feed\n`/rss setchannel <#ch>` — Auto-post"
            )

            embed = discord.Embed(
                title=f"{BOT_NAME} Help Menu",
                description=f"Click the buttons below to see commands.\n\n**Current Prefix:** `{prefix}`",
                color=discord.Color.blue()
            )
            embed.set_thumbnail(url=self.bot.user.display_avatar.url)

            view = HelpView(self.bot, ctx, formatted_cats, prefix)
            await ctx.send(embed=embed, view=view)

        else:
            search_name = command_name.lower().lstrip("/")
            command = self.bot.get_command(search_name)
            if command and not command.hidden:
                was_alias = search_name != command.name
                title = f"Help: `{prefix}{command.name}`"
                if was_alias:
                    title += f" (alias: `{prefix}{search_name}`)"

                embed = discord.Embed(
                    title=title,
                    description=command.help or "No description provided.",
                    color=discord.Color.green()
                )
                if command.usage:
                    embed.add_field(name="Usage", value=f"`{prefix}{command.name} {command.usage}`", inline=False)
                if command.aliases:
                    embed.add_field(name="Aliases", value=", ".join(f"`{prefix}{a}`" for a in command.aliases), inline=False)
                await ctx.send(embed=embed)
                return

            app_command = self.find_app_command(search_name)
            if app_command:
                embed = discord.Embed(
                    title=f"Help: `/{app_command.name}`",
                    description=app_command.description or "No description provided.",
                    color=discord.Color.green()
                )
                await ctx.send(embed=embed)
                return

            await ctx.send(f"No command named `{command_name}` found.")

    def find_app_command(self, name: str):
        name = name.lstrip("/").lower()
        tree = self.bot.tree
        walker = getattr(tree, "walk_commands", None)
        if walker is not None:
            for cmd in tree.walk_commands():
                if cmd.name == name:
                    return cmd
        commands_map = getattr(tree, "_commands", None)
        if isinstance(commands_map, dict):
            return commands_map.get(name)
        return None
async def setup(bot):
    await bot.add_cog(HelpCog(bot))