# cogs/moderation/warns.py: Warning system with optional auto-thresholds.

import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import os
import secrets
import logging
from datetime import datetime, timezone
from utils.config import load_config, save_config
from cogs.moderation.core import parse_time_string

logger = logging.getLogger(__name__)

WARNINGS_DB = os.getenv("WARNINGS_FILE_PATH", "warnings.db")


async def init_db():
    async with aiosqlite.connect(WARNINGS_DB) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                warn_id     TEXT NOT NULL UNIQUE,
                guild_id    INTEGER NOT NULL,
                user_id     INTEGER NOT NULL,
                mod_id      INTEGER NOT NULL,
                reason      TEXT NOT NULL,
                timestamp   TEXT NOT NULL
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_guild_user ON warnings (guild_id, user_id)")
        await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_warn_id ON warnings (warn_id)")
        await db.commit()


async def get_warn_count(guild_id: int, user_id: int) -> int:
    async with aiosqlite.connect(WARNINGS_DB) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def resolve_user(ctx, user_input: str) -> discord.User | discord.Member | None:
    """
    Resolves a user from a mention, username, or raw ID.
    Returns a Member if in guild, User if resolvable via API, None if not found.
    """
    # Strip mention formatting if present
    cleaned = user_input.strip().lstrip('<@').rstrip('>').lstrip('!')

    # Try as integer ID first
    try:
        user_id = int(cleaned)
        member = ctx.guild.get_member(user_id)
        if member:
            return member
        return await ctx.bot.fetch_user(user_id)
    except ValueError:
        pass
    except discord.NotFound:
        return None

    # Try as Member by name/mention via converter
    try:
        return await commands.MemberConverter().convert(ctx, user_input)
    except commands.BadArgument:
        pass

    return None


async def apply_threshold(ctx, member: discord.Member, warn_count: int):
    config = load_config()
    thresholds = config.get("warn_thresholds", {})
    if not thresholds.get("enabled"):
        return

    rule = thresholds.get(str(warn_count))
    if not rule:
        return

    action = rule.get("action")

    try:
        if action == "timeout":
            duration_str = rule.get("duration", "1h")
            delta = parse_time_string(duration_str)
            if delta:
                await member.timeout(delta, reason=f"Auto-threshold: {warn_count} warnings")
                await ctx.send(
                    f"Auto-threshold reached ({warn_count} warns): "
                    f"{member.mention} timed out for {duration_str}."
                )
        elif action == "kick":
            await member.kick(reason=f"Auto-threshold: {warn_count} warnings")
            await ctx.send(
                f"Auto-threshold reached ({warn_count} warns): "
                f"{member.mention} has been kicked."
            )
        elif action == "ban":
            await ctx.guild.ban(member, reason=f"Auto-threshold: {warn_count} warnings")
            await ctx.send(
                f"Auto-threshold reached ({warn_count} warns): "
                f"{member.mention} has been banned."
            )
        else:
            logger.warning(f"Unknown warn_threshold action: {action}")
    except discord.Forbidden:
        await ctx.send(f"Auto-threshold triggered but I lack permissions to {action} {member.mention}.")
    except Exception as e:
        logger.error(f"Auto-threshold failed for {member} at {warn_count} warns: {e}")


def thresholds_to_text(thresholds: dict) -> str:
    rules = {k: v for k, v in thresholds.items() if k != "enabled"}
    lines = []
    for count, rule in sorted(rules.items(), key=lambda x: int(x[0])):
        action = rule.get("action", "")
        duration = rule.get("duration", "")
        if duration:
            lines.append(f"{count} {action} {duration}")
        else:
            lines.append(f"{count} {action}")
    return "\n".join(lines)


def text_to_thresholds(text: str, enabled: bool) -> dict | None:
    result: dict = {"enabled": enabled}
    valid_actions = {"timeout", "kick", "ban"}

    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            return None
        count, action = parts[0], parts[1].lower()
        if not count.isdigit():
            return None
        if action not in valid_actions:
            return None
        if action == "timeout":
            if len(parts) < 3:
                return None
            duration = parts[2]
            if not parse_time_string(duration):
                return None
            result[count] = {"action": action, "duration": duration}
        else:
            result[count] = {"action": action}

    return result


class ThresholdModal(discord.ui.Modal, title="Edit Warn Thresholds"):
    rules = discord.ui.TextInput(
        label="Rules (warn_count action [duration])",
        style=discord.TextStyle.paragraph,
        placeholder="3 timeout 1h\n5 kick\n7 ban",
        required=False,
    )
    enabled = discord.ui.TextInput(
        label="Enabled? (yes / no)",
        style=discord.TextStyle.short,
        placeholder="yes",
        max_length=3,
    )

    def __init__(self, current_thresholds: dict):
        super().__init__()
        self.rules.default = thresholds_to_text(current_thresholds)
        self.enabled.default = "yes" if current_thresholds.get("enabled", True) else "no"

    async def on_submit(self, interaction: discord.Interaction):
        is_enabled = self.enabled.value.strip().lower() in ("yes", "y", "true", "1")
        parsed = text_to_thresholds(self.rules.value, is_enabled)

        if parsed is None:
            await interaction.response.send_message(
                "Invalid format. Each line must be: `<count> <action> [duration]`\n"
                "Valid actions: `timeout` (requires duration e.g. `1h`), `kick`, `ban`.",
                ephemeral=True
            )
            return

        config = load_config()
        config["warn_thresholds"] = parsed
        save_config(config)

        if not parsed.get("enabled"):
            summary = "Warn thresholds saved but **disabled**."
        elif len(parsed) <= 1:
            summary = "Warn thresholds **enabled** with no rules set."
        else:
            rules = {k: v for k, v in parsed.items() if k != "enabled"}
            lines = []
            for count, rule in sorted(rules.items(), key=lambda x: int(x[0])):
                action = rule.get("action")
                duration = rule.get("duration", "")
                lines.append(f"`{count} warns` → {action} {duration}".strip())
            summary = "Warn thresholds updated:\n" + "\n".join(lines)

        await interaction.response.send_message(summary, ephemeral=True)


class WarnsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        await init_db()

    @commands.hybrid_command(name='warn', help='Issues a warning to a member.', usage='<member|id> [reason]')
    @app_commands.describe(member="The member to warn (mention, username, or ID).", reason="Reason for the warning.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def warn_cmd(self, ctx, member: str, *, reason: str = "No reason provided"):
        await ctx.defer()

        user = await resolve_user(ctx, member)
        if not user:
            await ctx.send("User not found.")
            return

        # warn requires the user to be in the server for role hierarchy check
        guild_member = ctx.guild.get_member(user.id)
        if not guild_member:
            await ctx.send("That user isn't in this server. You can only warn members.")
            return

        if guild_member == ctx.author:
            await ctx.send("You can't warn yourself.")
            return
        if guild_member.bot:
            await ctx.send("You can't warn a bot.")
            return
        if guild_member.top_role >= ctx.author.top_role and ctx.guild.owner != ctx.author:
            await ctx.send("You can't warn someone with a role higher than or equal to yours.")
            return

        warn_id = secrets.token_hex(4)
        timestamp = datetime.now(timezone.utc).isoformat()

        async with aiosqlite.connect(WARNINGS_DB) as db:
            await db.execute(
                "INSERT INTO warnings (warn_id, guild_id, user_id, mod_id, reason, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (warn_id, ctx.guild.id, guild_member.id, ctx.author.id, reason, timestamp)
            )
            await db.commit()

        warn_count = await get_warn_count(ctx.guild.id, guild_member.id)

        dm_embed = discord.Embed(title="You have been warned", color=discord.Color.yellow())
        dm_embed.add_field(name="Server", value=ctx.guild.name, inline=False)
        dm_embed.add_field(name="Reason", value=reason, inline=False)
        dm_embed.set_footer(text=f"Warning ID: {warn_id} • You now have {warn_count} warning(s).")
        try:
            await guild_member.send(embed=dm_embed)
            dm_note = ""
        except (discord.Forbidden, discord.HTTPException):
            dm_note = " *(couldn't DM user)*"

        await ctx.send(
            f"**{guild_member}** has been warned ({warn_count} total). "
            f"Reason: {reason} • ID: `{warn_id}`{dm_note}"
        )

        await apply_threshold(ctx, guild_member, warn_count)

    @commands.hybrid_command(name='warns', help='Shows all warnings for a member.', usage='<member|id>')
    @app_commands.describe(member="The member to check warnings for (mention, username, or ID).")
    @commands.has_permissions(moderate_members=True)
    async def warns_cmd(self, ctx, member: str):
        await ctx.defer()

        user = await resolve_user(ctx, member)
        if not user:
            await ctx.send("User not found.")
            return

        async with aiosqlite.connect(WARNINGS_DB) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT warn_id, mod_id, reason, timestamp FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY timestamp ASC",
                (ctx.guild.id, user.id)
            ) as cursor:
                rows = list(await cursor.fetchall())

        if not rows:
            await ctx.send(f"**{user}** has no warnings.")
            return

        embed = discord.Embed(
            title=f"Warnings for {user}",
            color=discord.Color.orange()
        )
        avatar = user.display_avatar.url if hasattr(user, 'display_avatar') else user.avatar.url if user.avatar else None
        if avatar:
            embed.set_thumbnail(url=avatar)

        for row in rows:
            mod = ctx.guild.get_member(row["mod_id"])
            mod_name = str(mod) if mod else f"<unknown mod {row['mod_id']}>"
            ts = datetime.fromisoformat(row["timestamp"]).strftime("%Y-%m-%d %H:%M UTC")
            embed.add_field(
                name=f"`{row['warn_id']}` — {ts}",
                value=f"**Reason:** {row['reason']}\n**By:** {mod_name}",
                inline=False
            )

        embed.set_footer(text=f"{len(rows)} warning(s) total.")
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='delwarn', help='Deletes a warning by its ID.', usage='<warn_id>')
    @app_commands.describe(warn_id="The warning ID to delete (get it from /warns).")
    @commands.has_permissions(moderate_members=True)
    async def delwarn_cmd(self, ctx, warn_id: str):
        await ctx.defer()

        async with aiosqlite.connect(WARNINGS_DB) as db:
            async with db.execute(
                "SELECT warn_id, user_id FROM warnings WHERE warn_id = ? AND guild_id = ?",
                (warn_id.lower(), ctx.guild.id)
            ) as cursor:
                row = await cursor.fetchone()

            if not row:
                await ctx.send(f"No warning with ID `{warn_id}` found in this server.")
                return

            await db.execute("DELETE FROM warnings WHERE warn_id = ?", (warn_id.lower(),))
            await db.commit()

        member = ctx.guild.get_member(row[1])
        member_str = str(member) if member else f"<user {row[1]}>"
        await ctx.send(f"Warning `{warn_id}` for **{member_str}** has been deleted.")

    @commands.hybrid_command(name='clearwarns', help="Clears all warnings for a member.", usage='<member|id>')
    @app_commands.describe(member="The member to clear all warnings for (mention, username, or ID).")
    @commands.has_permissions(moderate_members=True)
    async def clearwarns_cmd(self, ctx, member: str):
        await ctx.defer()

        user = await resolve_user(ctx, member)
        if not user:
            await ctx.send("User not found.")
            return

        async with aiosqlite.connect(WARNINGS_DB) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ?",
                (ctx.guild.id, user.id)
            ) as cursor:
                row = await cursor.fetchone()
                count = row[0] if row else 0

            if count == 0:
                await ctx.send(f"**{user}** has no warnings to clear.")
                return

            await db.execute(
                "DELETE FROM warnings WHERE guild_id = ? AND user_id = ?",
                (ctx.guild.id, user.id)
            )
            await db.commit()

        await ctx.send(f"Cleared {count} warning(s) for **{user}**.")

    @commands.hybrid_command(name='warnthresholds', aliases=['wt'], help='View or edit auto-punishment thresholds for warnings.', usage='')
    @commands.has_permissions(administrator=True)
    async def warnthresholds_cmd(self, ctx):
        config = load_config()
        current = config.get("warn_thresholds", {"enabled": False})

        if ctx.interaction:
            await ctx.interaction.response.send_modal(ThresholdModal(current))
        else:
            enabled = current.get("enabled", False)
            rules = {k: v for k, v in current.items() if k != "enabled"}
            if not rules:
                await ctx.send(
                    f"Warn thresholds are currently **{'enabled' if enabled else 'disabled'}** with no rules set.\n"
                    "Use `/warnthresholds` (slash command) to edit via modal."
                )
                return
            lines = []
            for count, rule in sorted(rules.items(), key=lambda x: int(x[0])):
                action = rule.get("action")
                duration = rule.get("duration", "")
                lines.append(f"`{count} warns` → {action} {duration}".strip())
            await ctx.send(
                f"Warn thresholds **{'enabled' if enabled else 'disabled'}**:\n" +
                "\n".join(lines) +
                "\n\nUse `/warnthresholds` (slash command) to edit via modal."
            )


async def setup(bot):
    await bot.add_cog(WarnsCog(bot))