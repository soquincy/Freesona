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

    @commands.hybrid_command(name='ban', help='Bans a member from the server.', usage='<member> [reason]')
    @app_commands.describe(member="The user to ban.", reason="Why are they being banned?")
    @commands.has_permissions(ban_members=True)
    @commands.bot_has_permissions(ban_members=True)
    async def ban_cmd(self, ctx, member: discord.User, *, reason: str = "No reason provided"):
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

        try:
            await ctx.guild.ban(member, reason=f"Banned by {ctx.author}: {reason}")
            note = "" if dm_sent else " *(couldn't DM user)*"
            await ctx.send(f"**{member}** has been banned. Reason: {reason}{note}")
        except discord.Forbidden:
            await ctx.send("I don't have permission to ban this user.")

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

async def setup(bot):
    await bot.add_cog(ModerationCog(bot))