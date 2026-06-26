# cogs/moderation/core.py: Moderation actions like ban, timeouts, kicks

import discord
from discord.ext import commands
from discord import app_commands
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

def parse_time_string(time_str: str) -> timedelta | None:
    units = {'s': 'seconds', 'm': 'minutes', 'h': 'hours', 'd': 'days'}
    try:
        amount = int(time_str[:-1])
        unit = time_str[-1].lower()
        if unit not in units:
            return None
        return timedelta(**{units[unit]: amount})
    except (ValueError, IndexError):
        return None

async def try_dm(user: discord.User | discord.Member, embed: discord.Embed) -> bool:
    try:
        await user.send(embed=embed)
        return True
    except (discord.Forbidden, discord.HTTPException):
        return False

class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command(name='kick', help='Kicks a member from the server.', usage='<member> [reason]')
    @app_commands.describe(member="The member to kick.", reason="Reason for the kick.")
    @commands.has_permissions(kick_members=True)
    @commands.bot_has_permissions(kick_members=True)
    async def kick_cmd(self, ctx, member: discord.Member, *, reason: str = "No reason provided"):
        await ctx.defer()

        if member == ctx.author:
            await ctx.send("You can't kick yourself.")
            return
        if member.top_role >= ctx.author.top_role and ctx.guild.owner != ctx.author:
            await ctx.send("You can't kick someone with a role higher than or equal to yours.")
            return

        dm_embed = discord.Embed(title="You have been kicked", color=discord.Color.orange())
        dm_embed.add_field(name="Server", value=ctx.guild.name, inline=False)
        dm_embed.add_field(name="Reason", value=reason, inline=False)
        dm_sent = await try_dm(member, dm_embed)

        try:
            await member.kick(reason=f"Kicked by {ctx.author}: {reason}")
            note = "" if dm_sent else " *(couldn't DM user)*"
            await ctx.send(f"**{member}** has been kicked. Reason: {reason}{note}")
        except discord.Forbidden:
            await ctx.send("I don't have permission to kick this member.")

    @commands.hybrid_command(name='purge', help='Deletes a specified number of messages (1-1000).', usage='<amount>')
    @app_commands.describe(amount="The number of messages to delete (1-1000).")
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def purge_cmd(self, ctx, amount: int):
        await ctx.defer(ephemeral=True)
        if 1 <= amount <= 1000:
            try:
                deleted = await ctx.channel.purge(limit=amount + 1)
                await ctx.send(f"Poof! Deleted {len(deleted) - 1} message(s).", delete_after=5)
            except Exception as e:
                logger.error(f"Failed to purge: {e}")
                await ctx.send("An error occurred while deleting messages.")
        else:
            await ctx.send("Please provide a number between 1 and 1000.")

    @commands.hybrid_command(name='ban', help='Bans a member from the server.', usage='<member> [delete_messages] [reason]')
    @app_commands.describe(
        member="The user to ban.",
        delete_messages="How far back to delete messages (e.g. 1d, 7d). Max 7d.",
        reason="Why are they being banned?"
    )
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban_cmd(self, ctx, member: discord.User, delete_messages: str = "0", *, reason: str = "No reason provided"):
        await ctx.defer()
        target = ctx.guild.get_member(member.id)

        if target:
            if target == ctx.author:
                await ctx.send("Why would you want to ban yourself?")
                return
            if target.top_role >= ctx.author.top_role and ctx.guild.owner != ctx.author:
                await ctx.send("You can't ban someone with a role higher than or equal to yours.")
                return

            dm_embed = discord.Embed(title="You have been banned", color=discord.Color.red())
            dm_embed.add_field(name="Server", value=ctx.guild.name, inline=False)
            dm_embed.add_field(name="Reason", value=reason, inline=False)
            dm_sent = await try_dm(target, dm_embed)
        else:
            dm_sent = False

        delta = parse_time_string(delete_messages) if delete_messages != "0" else timedelta(0)
        if delta is None or delta.total_seconds() > 604800:
            await ctx.send("Invalid delete duration. Max is 7d.")
            return
        delete_seconds = int(delta.total_seconds())

        try:
            await ctx.guild.ban(member, reason=f"Banned by {ctx.author}: {reason}", delete_message_seconds=delete_seconds)
            note = "" if dm_sent else " *(couldn't DM user)*"
            del_note = f", deleted messages from the past {delete_messages}" if delete_seconds else ""
            await ctx.send(f"**{member}** has been banned{del_note}. Reason: {reason}{note}")
        except discord.Forbidden:
            await ctx.send("I don't have permission to ban this user.")

    @commands.hybrid_command(name='softban', help='Bans and immediately unbans a member to purge their messages.', usage='<member> [delete_messages] [reason]')
    @app_commands.describe(
        member="The member to softban.",
        delete_messages="How far back to delete messages (e.g. 1d, 7d). Defaults to 7d.",
        reason="Reason for the softban."
    )
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def softban_cmd(self, ctx, member: discord.Member, delete_messages: str = "7d", *, reason: str = "No reason provided"):
        await ctx.defer()

        if member == ctx.author:
            await ctx.send("You can't softban yourself.")
            return
        if member.top_role >= ctx.author.top_role and ctx.guild.owner != ctx.author:
            await ctx.send("You can't softban someone with a role higher than or equal to yours.")
            return

        delta = parse_time_string(delete_messages)
        if delta is None or delta.total_seconds() > 604800:
            await ctx.send("Invalid delete duration. Max is 7d.")
            return
        delete_seconds = int(delta.total_seconds())

        dm_embed = discord.Embed(title="You have been softbanned", color=discord.Color.orange())
        dm_embed.add_field(name="Server", value=ctx.guild.name, inline=False)
        dm_embed.add_field(name="Reason", value=reason, inline=False)
        dm_embed.set_footer(text="A softban removes your recent messages but does not permanently ban you.")
        dm_sent = await try_dm(member, dm_embed)

        try:
            await ctx.guild.ban(member, reason=f"Softban by {ctx.author}: {reason}", delete_message_seconds=delete_seconds)
            await ctx.guild.unban(member, reason="Softban: automatic unban")
            note = "" if dm_sent else " *(couldn't DM user)*"
            await ctx.send(f"**{member}** has been softbanned (messages from past {delete_messages} deleted). Reason: {reason}{note}")
        except discord.Forbidden:
            await ctx.send("I don't have permission to ban this member.")
        except discord.HTTPException as e:
            logger.error(f"Softban failed for {member}: {e}")
            await ctx.send("Softban failed. The ban may have gone through without the unban -- check manually.")

    @commands.hybrid_command(name='unban', help='Unbans a user from the server.', usage='<user> [reason]')
    @app_commands.describe(user="The user to unban (ID or user#tag).", reason="Reason for the unban.")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def unban_cmd(self, ctx, user: discord.User, *, reason: str = "No reason provided"):
        await ctx.defer()

        try:
            await ctx.guild.unban(user, reason=f"Unbanned by {ctx.author}: {reason}")
            dm_embed = discord.Embed(title="You have been unbanned", color=discord.Color.green())
            dm_embed.add_field(name="Server", value=ctx.guild.name, inline=False)
            dm_embed.add_field(name="Reason", value=reason, inline=False)
            await try_dm(user, dm_embed)
            await ctx.send(f"**{user}** has been unbanned. Reason: {reason}")
        except discord.NotFound:
            await ctx.send("That user isn't banned.")
        except discord.Forbidden:
            await ctx.send("I don't have permission to unban this user.")

    @commands.hybrid_command(name='timeout', aliases=['to'], help='Times out a member.', usage='<member> <duration> [reason]')
    @app_commands.describe(
        member="The member to timeout.",
        length="Duration (e.g. 10m, 1h).",
        reason="Reason for timeout."
    )
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def timeout_cmd(self, ctx, member: discord.Member, length: str, *, reason: str = "No reason provided"):
        await ctx.defer()

        if member == ctx.author:
            await ctx.send("You seriously want to time out yourself?.")
            return

        delta = parse_time_string(length)
        if not delta:
            await ctx.send("Invalid format. Use `10s`, `5m`, `1h`, etc.")
            return

        try:
            await member.timeout(delta, reason=f"Timed out by {ctx.author}: {reason}")
            await ctx.send(f"{member.mention} has been timed out for {length}. Reason: {reason}")
        except discord.Forbidden:
            await ctx.send("I can't timeout that member.")

    @commands.hybrid_command(name='removetimeout', aliases=['rt', 'rto'], help='Removes a timeout from a member.', usage='<member>')
    @app_commands.describe(member="The member to remove timeout.")
    @commands.has_permissions(moderate_members=True)
    @commands.bot_has_permissions(moderate_members=True)
    async def untimeout_cmd(self, ctx, member: discord.Member):
        await ctx.defer()
        if not member.is_timed_out():
            await ctx.send("That user isn't timed out.")
            return

        await member.timeout(None, reason=f"Removed by {ctx.author}")
        await ctx.send(f"Removed timeout for {member.mention}.")

    @commands.hybrid_command(name='slowmode', help='Sets the slowmode delay for the current channel.', usage='<duration|off>')
    @app_commands.describe(delay="Delay between messages (e.g. 10s, 5m). Use 'off' to disable.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def slowmode_cmd(self, ctx, delay: str):
        await ctx.defer()

        if delay.lower() == "off":
            seconds = 0
        else:
            delta = parse_time_string(delay)
            if delta is None or delta.total_seconds() > 21600:
                await ctx.send("Invalid duration. Max is 6h.")
                return
            seconds = int(delta.total_seconds())

        try:
            await ctx.channel.edit(slowmode_delay=seconds)
            if seconds == 0:
                await ctx.send("Slowmode disabled.")
            else:
                await ctx.send(f"Slowmode set to {delay}.")
        except discord.Forbidden:
            await ctx.send("I don't have permission to edit this channel.")

    @commands.hybrid_command(name='lock', help='Locks the current channel, preventing members from sending messages.', usage='[reason]')
    @app_commands.describe(reason="Reason for locking the channel.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def lock_cmd(self, ctx, *, reason: str = "No reason provided"):
        await ctx.defer()
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        if overwrite.send_messages is False:
            await ctx.send("This channel is already locked.")
            return

        overwrite.send_messages = False
        try:
            await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Locked by {ctx.author}: {reason}")
            await ctx.send(f"Channel locked. Reason: {reason}")
        except discord.Forbidden:
            await ctx.send("I don't have permission to lock this channel.")

    @commands.hybrid_command(name='unlock', help='Unlocks the current channel.', usage='[reason]')
    @app_commands.describe(reason="Reason for unlocking the channel.")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def unlock_cmd(self, ctx, *, reason: str = "No reason provided"):
        await ctx.defer()
        overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
        if overwrite.send_messages is not False:
            await ctx.send("This channel isn't locked.")
            return

        overwrite.send_messages = None
        try:
            await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite, reason=f"Unlocked by {ctx.author}: {reason}")
            await ctx.send(f"Channel unlocked. Reason: {reason}")
        except discord.Forbidden:
            await ctx.send("I don't have permission to unlock this channel.")

async def setup(bot):
    await bot.add_cog(ModerationCog(bot))