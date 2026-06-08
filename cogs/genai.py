# cogs/genai.py: GenAI cog — wiring only. Logic lives in utils/. Well, the main point of this bot in general.
# You may disable this module with /module disable genai, though you will lose access to all AI features and commands.
# This cog is also responsible for the on_message event that triggers AI responses, so disabling it will also stop the bot from responding to messages in channels.
# Wolfram Alpha functionality is not affected by this and will still work if you disable this cog.
 
# This is a rewrite with the assistance of AI, to clean up the +1000 lines of the previous GenAI cog and split responsibilities more clearly.
# The goal is to have this cog only handle Discord events and commands, while all the AI logic, persona management, memory, and config handling lives in utils/.
# This should make the codebase easier to maintain and reason about, and allow for better separation of concerns.
# The new structure also makes it easier to add features like autonomy mode, persona profiles, and web search without cluttering the main cog file.

import asyncio
import logging
import time
import re
import urllib.parse
from typing import Literal, Optional

import discord
import aiosqlite
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import os

from utils.config import load_config, save_config, embed_footer, LAST_DEBUG, get_model_name
from utils.generation import (
    safe_generate, send_response, extract_attachments,
    ConversationResponse, build_response,
)
from utils.roles import resolve_message_role
from utils.memory import channel_memory, channel_summary, extract_and_store_fact, get_user_facts_prompt
from utils.intent import evaluate_intent, FREQUENCY_THRESHOLD, INTENT_IGNORE
from utils.persona import (
    PERSONA_DATA, CURRENT_PERSONA, PERSONA_LOCKED, LEGACY_DETECTED,
    open_persona_panel,
    assemble_persona, save_persona_json, default_persona_json,
    load_profiles, save_profiles,
)

load_dotenv()

BOT_NAME         = os.getenv("BOT_NAME", "Bot")
MEMORY_FILE_PATH = os.getenv("MEMORY_FILE_PATH", "./memory.db")

logger = logging.getLogger("FreesonaBot")

# Debounce + autonomy state
DEBOUNCE_SECONDS          = 1.2
AUTONOMY_COOLDOWN_SECONDS = 120
AUTONOMY_USER_COOLDOWN    = 60

_pending_responses: dict[int, asyncio.Task] = {}
_autonomy_cooldown: dict[int, float]        = {}
_autonomy_user_cooldown: dict[int, float]   = {}

CHAT_RESPONSE_MODES = {"all", "mentions", "smart"}


def should_respond_in_chat_channel(message: discord.Message, bot_user: discord.ClientUser | None, mode: str) -> bool:
    if mode == "all":
        return True

    is_mention = bot_user is not None and bot_user in message.mentions
    is_reply = (
        bot_user is not None
        and message.reference is not None
        and getattr(message.reference.resolved, "author", None) == bot_user
    )

    if mode == "mentions":
        return is_mention or is_reply
    if mode == "smart":
        return is_mention or is_reply or bool(message.attachments)
    return True


def clean_sources_block(sources_text: str, max_length: int = 1024) -> str:
    links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', sources_text)

    if not links:
        lines = [line.strip() for line in sources_text.split('\n') if line.strip()]
        return "\n".join(lines[:5])[:max_length]

    cleaned_links = []
    current_length = 0

    for text, url in links[:5]:
        if "grounding-api-redirect" in url:
            entry = f"• {text}"
        else:
            entry = f"• [{text}]({url})"

        if current_length + len(entry) + 1 > max_length:
            break

        cleaned_links.append(entry)
        current_length += len(entry) + 1

    return "\n".join(cleaned_links)


# (resolve_message_role has been moved to utils/roles.py)


class GenAICog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.setpersona_command = app_commands.Command(
            name="setpersona",
            description="Open the persona editor (Owner only).",
            callback=open_persona_panel,
        )
        bot.tree.add_command(self.setpersona_command)

    async def cog_load(self):
        from utils.memory import init_db
        await init_db()

    async def cog_unload(self):
        self.bot.tree.remove_command("setpersona")
        for task in _pending_responses.values():
            task.cancel()
        _pending_responses.clear()

    # -------------------------------------------------------------------
    # on_message
    # -------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        WHITELIST_ID = 1482682376655208548

        if message.guild is None:
            return
        if message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return
        if getattr(message, "interaction_metadata", None):
            return

        prefix = await self.bot.get_prefix(message)
        prefixes = [prefix] if isinstance(prefix, str) else prefix
        if any(message.content.startswith(p) for p in prefixes):
            return

        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        bot_id = self.bot.user.id if self.bot.user else 0
        if message.author.id == bot_id:
            return  # Hard stop reprocessing own output

        config = load_config()
        whitelist = config.get("whitelist_bot_ids", [1482682376655208548])

        # Ingestion filter: Ignore external bots unless they are whitelisted or webhooks
        if message.author.bot and not message.webhook_id and message.author.id not in whitelist:
            return

        role = resolve_message_role(message, bot_id)

        # -------------------------------------------------------------------
        # Conversation channel
        # -------------------------------------------------------------------
        chat_channel_id = config.get("chat_channel_id")
        if chat_channel_id and message.channel.id == chat_channel_id:
            response_mode = config.get("conversation_response_mode", "all")
            if not should_respond_in_chat_channel(message, self.bot.user, response_mode):
                return

            user_id           = message.author.id
            channel_snapshot  = message.channel
            username_snapshot = message.author.display_name
            message_snapshot  = message
            guild_id_snapshot = message.guild.id

            # Create structured payload with role boundaries preserved
            payload = {
                "role": role,
                "author_id": user_id,
                "username": username_snapshot,
                "content": message.content,
                "reply": None
            }

            if message.reference and isinstance(message.reference.resolved, discord.Message):
                ref = message.reference.resolved
                payload["reply"] = {
                    "author": ref.author.display_name,
                    "author_id": ref.author.id,
                    "content": ref.content or "",
                    "is_bot": ref.author.bot,
                    "is_webhook": ref.webhook_id is not None,
                    "role": resolve_message_role(ref, bot_id)
                }

            if user_id in _pending_responses:
                _pending_responses[user_id].cancel()
                logger.debug(f"Debounce: cancelled pending task for user {user_id}")

            async def debounced_respond():
                try:
                    await asyncio.sleep(DEBOUNCE_SECONDS)
                    attachments = await extract_attachments(message_snapshot)
                    response = await safe_generate(
                        payload,
                        current_persona=CURRENT_PERSONA,
                        channel_id=channel_snapshot.id,
                        guild_id=guild_id_snapshot,
                        user_id=user_id,
                        message_id=message_snapshot.id,
                        username=username_snapshot,
                        attachments=attachments,
                    )
                    await send_response(response, channel_snapshot, reply_to=message_snapshot)
                except asyncio.CancelledError:
                    logger.debug(f"Debounce: task cancelled for user {user_id}")
                finally:
                    _pending_responses.pop(user_id, None)

            _pending_responses[user_id] = asyncio.create_task(debounced_respond())
            return

        # -------------------------------------------------------------------
        # Autonomy
        # -------------------------------------------------------------------
        autonomy_on = config.get("autonomy", False)

        # Only autonomy fires for user messages (not bot messages)
        if autonomy_on and role == "user":
            frequency    = config.get("autonomy_frequency", "default")
            threshold    = FREQUENCY_THRESHOLD.get(frequency, 0.50)
            now          = time.time()
            last_channel = _autonomy_cooldown.get(message.channel.id, 0)
            last_user    = _autonomy_user_cooldown.get(message.author.id, 0)

            channel_ready = now - last_channel > AUTONOMY_COOLDOWN_SECONDS
            user_ready    = now - last_user    > AUTONOMY_USER_COOLDOWN

            if channel_ready and user_ready:
                has_memory = message.channel.id in channel_memory
                intent     = evaluate_intent(message, self.bot.user, has_memory)

                if intent.intent != INTENT_IGNORE and intent.confidence >= threshold:
                    _autonomy_cooldown[message.channel.id]    = now
                    _autonomy_user_cooldown[message.author.id] = now
                    logger.info(
                        f"Autonomy firing | channel={message.channel.id} "
                        f"confidence={intent.confidence:.2f} intent={intent.intent} "
                        f"targets={intent.targets}"
                    )
                    
                    # Create structured payload for autonomy
                    payload = {
                        "role": role,
                        "author_id": message.author.id,
                        "username": message.author.display_name,
                        "content": message.content,
                        "reply": None
                    }
                    
                    if message.reference and isinstance(message.reference.resolved, discord.Message):
                        ref = message.reference.resolved
                        payload["reply"] = {
                            "author": ref.author.display_name,
                            "author_id": ref.author.id,
                            "content": ref.content or "",
                            "is_bot": ref.author.bot,
                            "is_webhook": ref.webhook_id is not None,
                            "role": resolve_message_role(ref, bot_id)
                        }
                    
                    attachments = await extract_attachments(message)
                    response = await safe_generate(
                        payload,
                        current_persona=CURRENT_PERSONA,
                        channel_id=message.channel.id,
                        guild_id=message.guild.id,
                        user_id=message.author.id,
                        message_id=message.id,
                        username=message.author.display_name,
                        attachments=attachments,
                    )
                    await send_response(response, message.channel)

    # -------------------------------------------------------------------
    # ~write
    # -------------------------------------------------------------------
    @commands.hybrid_command(name='write', aliases=['w'], help='Ask the AI to write or create something.')
    async def write_cmd(self, ctx, *, query: str):
        if ctx.guild is None:
            await ctx.send("AI commands are not available in DMs.")
            return
        await ctx.defer()
        attachments = await extract_attachments(ctx.message)
        response = await safe_generate(
            query,
            current_persona=CURRENT_PERSONA,
            instruction_prefix=(
                "Return plain text only. "
                "Use double newlines between paragraphs. "
                "Do NOT use markdown, symbols, or headings. "
                "Each idea must be separated clearly."
            ),
            apply_persona=True,
            attachments=attachments,
        )
        embed = discord.Embed(
            title=f"{BOT_NAME} says...",
            description=response.first_text(),
            color=discord.Color.green()
        )
        embed.set_footer(text=embed_footer(ctx.author.display_name, query))
        await ctx.send(embed=embed)

    # -------------------------------------------------------------------
    # ~ask
    # -------------------------------------------------------------------
    @commands.hybrid_command(name='ask', aliases=['a'], help='Ask the AI a question.')
    async def ask_cmd(self, ctx, *, query: str):
        if ctx.guild is None:
            await ctx.send("AI commands are not available in DMs.")
            return
        attachments = await extract_attachments(ctx.message)
        response = await safe_generate(
            query,
            current_persona=CURRENT_PERSONA,
            instruction_prefix=(
                "Write in clean paragraphs. "
                "Use newline breaks between sections. "
                "Do NOT use markdown headings like ###."
            ),
            username=ctx.author.display_name,
            attachments=attachments,
        )
        embed = discord.Embed(
            title=f"{BOT_NAME} answers...",
            description=response.first_text(),
            color=discord.Color.blue()
        )
        embed.set_footer(text=embed_footer(ctx.author.display_name, query))
        await ctx.send(embed=embed)

    # -------------------------------------------------------------------
    # ~search
    # -------------------------------------------------------------------
    @commands.hybrid_command(name='search', aliases=['s'], help='Search the web and summarize with AI.')
    async def search_cmd(self, ctx, *, query: str):
        if ctx.guild is None:
            await ctx.send("AI commands are not available in DMs.")
            return

        await ctx.defer()
        from utils.search import web_search

        result = await web_search(query)

        if result.has_sources:
            text = result.text[:4096]
        else:
            response = await safe_generate(
                f"Summarize these search results:\n\n{result.text}",
                current_persona=CURRENT_PERSONA,
                apply_persona=False,
                instruction_prefix=(
                    "Write in natural, flowing paragraphs. "
                    "Do not use bullet points or one-sentence sections. "
                    "Use **Bold Text** only for key terms. "
                    "Do not use markdown headers (#)."
                )
            )
            text = response.first_text()[:4096]

        embed = discord.Embed(
            title=f"Search: {query}",
            description=text or "No results found.",
            color=discord.Color.blue()
        )

        if result.has_sources:
            sources_text = clean_sources_block(result.sources_block(max=5))
            embed.add_field(name="Sources", value=sources_text, inline=False)
        else:
            url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            embed.add_field(name="Full results", value=url, inline=False)

        embed.set_footer(text=embed_footer(ctx.author.display_name, query))
        await ctx.send(embed=embed)

    # -------------------------------------------------------------------
    # Persona lock / unlock
    # -------------------------------------------------------------------
    @commands.hybrid_command(name='personalock', aliases=['plock'], help='Lock the persona to prevent changes (Owner only).')
    @commands.is_owner()
    async def persona_lock(self, ctx):
        import utils.persona as p
        p.PERSONA_LOCKED = True
        await ctx.send("Persona locked.", ephemeral=True if ctx.interaction else False)

    @commands.hybrid_command(name='personaunlock', aliases=['pulock'], help='Unlock the persona (Owner only).')
    @commands.is_owner()
    async def persona_unlock(self, ctx):
        import utils.persona as p
        p.PERSONA_LOCKED = False
        await ctx.send("Persona unlocked.", ephemeral=True if ctx.interaction else False)

    # -------------------------------------------------------------------
    # Persona profiles
    # -------------------------------------------------------------------
    @commands.hybrid_command(name='personasave', aliases=['psave'], help='Save current persona as a named profile (Owner only).')
    @commands.is_owner()
    async def persona_save(self, ctx, name: str):
        profiles = load_profiles()
        profiles[name.lower()] = PERSONA_DATA.copy()
        save_profiles(profiles)
        await ctx.send(f"Saved persona as `{name.lower()}`.", ephemeral=True if ctx.interaction else False)

    @commands.hybrid_command(name='personaload', aliases=['pload'], help='Load a saved persona profile (Owner only).')
    @commands.is_owner()
    async def persona_load(self, ctx, name: str):
        import utils.persona as p
        if p.PERSONA_LOCKED:
            await ctx.send("Persona is locked.", ephemeral=True if ctx.interaction else False)
            return
        profiles = load_profiles()
        key = name.lower()
        if key not in profiles:
            await ctx.send(f"No profile named `{key}`. Use `/personalist` to see saved profiles.")
            return
        loaded = profiles[key]
        if isinstance(loaded, str):
            p.CURRENT_PERSONA = loaded
            p.PERSONA_DATA = default_persona_json()
        else:
            p.PERSONA_DATA = loaded
            p.CURRENT_PERSONA = assemble_persona(p.PERSONA_DATA)
        save_persona_json(p.PERSONA_DATA)
        await ctx.send(f"Loaded persona `{key}`.", ephemeral=True if ctx.interaction else False)

    @commands.hybrid_command(name='personalist', aliases=['plist'], help='List saved persona profiles.')
    @commands.is_owner()
    async def persona_list(self, ctx):
        profiles = load_profiles()
        if not profiles:
            await ctx.send("No saved profiles yet.")
            return
        names = "\n".join(f"- `{k}`" for k in profiles)
        await ctx.send(names, ephemeral=True if ctx.interaction else False)

    @commands.hybrid_command(name='personadelete', aliases=['pdel'], help='Delete a saved persona profile (Owner only).')
    @commands.is_owner()
    async def persona_delete(self, ctx, name: str):
        profiles = load_profiles()
        key = name.lower()
        if key not in profiles:
            await ctx.send(f"No profile named `{key}`.")
            return
        del profiles[key]
        save_profiles(profiles)
        await ctx.send(f"Deleted profile `{key}`.", ephemeral=True if ctx.interaction else False)

    # -------------------------------------------------------------------
    # /setchannel + /clearchannel
    # -------------------------------------------------------------------
    @commands.hybrid_command(name='setchannel', aliases=['sc'], help='Set the AI conversation channel (Admin only).')
    @commands.has_permissions(administrator=True)
    async def set_channel(self, ctx, channel: discord.TextChannel):
        config = load_config()
        config["chat_channel_id"] = channel.id
        save_config(config)
        await ctx.send(f"Conversation channel set to {channel.mention}.")

    @commands.hybrid_command(name='clearchannel', aliases=['cc'], help='Remove the AI conversation channel (Admin only).')
    @commands.has_permissions(administrator=True)
    async def clear_channel(self, ctx):
        config = load_config()
        config.pop("chat_channel_id", None)
        save_config(config)
        await ctx.send("Conversation channel cleared.")

    # -------------------------------------------------------------------
    # /debugpersona
    # -------------------------------------------------------------------
    @commands.hybrid_command(name='debugpersona', aliases=['pdeb'], help='Show active persona and last prompt (Owner only).')
    @commands.is_owner()
    async def debug_persona(self, ctx):
        import utils.persona as p
        last   = LAST_DEBUG.get(ctx.channel.id, "*(no prompt sent in this channel yet)*")
        locked = "Yes" if p.PERSONA_LOCKED else "No"
        legacy = "Yes — migrate via `/setpersona`" if p.LEGACY_DETECTED else "No"
        config = load_config()
        autonomy_status = "On" if config.get("autonomy", False) else "Off"
        autonomy_freq   = config.get("autonomy_frequency", "default")
        response_mode   = config.get("conversation_response_mode", "all")
        embed = discord.Embed(title="Persona Debug", color=discord.Color.yellow())
        embed.add_field(name="Locked",      value=locked,  inline=True)
        embed.add_field(name="Model",       value=get_model_name(), inline=True)
        embed.add_field(name="Legacy Mode", value=legacy,  inline=True)
        embed.add_field(name="Autonomy",    value=f"{autonomy_status} ({autonomy_freq})", inline=True)
        embed.add_field(name="Chat Mode",   value=response_mode, inline=True)
        embed.add_field(name="Assembled Persona",          value=f"```{p.CURRENT_PERSONA[:900]}```", inline=False)
        embed.add_field(name="Last Prompt (this channel)", value=f"```{last[:900]}```",              inline=False)
        await ctx.send(embed=embed, ephemeral=True if ctx.interaction else False)

    # -------------------------------------------------------------------
    # /clearmemory (short-term)
    # -------------------------------------------------------------------
    @commands.hybrid_command(name='clearmemory', aliases=['smcl'], help='Clear conversation memory for this channel (Admin only).')
    @commands.has_permissions(administrator=True)
    async def clear_memory(self, ctx):
        channel_memory.pop(ctx.channel.id, None)
        channel_summary.pop(ctx.channel.id, None)
        await ctx.send("Short-term channel memory cleared.")

    # -------------------------------------------------------------------
    # /memorylist (long-term SQLite)
    # -------------------------------------------------------------------
    @commands.hybrid_command(name='memorylist', aliases=['meml'], help='List long-term memory facts for a user.')
    @app_commands.describe(user="The user whose memory to list (defaults to you).")
    async def memory_list(self, ctx, user: Optional[discord.User] = None):
        if ctx.guild is None:
            await ctx.send("Memory commands are server-only.")
            return

        target_user = user or ctx.author
        member = ctx.guild.get_member(ctx.author.id) if ctx.guild else None
        is_admin = bool(member and (member.guild_permissions.administrator or member.guild_permissions.manage_guild))

        if target_user.id != ctx.author.id and not is_admin:
            await ctx.send("❌ You can only view your own memory.", ephemeral=True)
            return

        async with aiosqlite.connect(MEMORY_FILE_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT content, importance FROM user_facts WHERE guild_id = ? AND user_id = ? ORDER BY importance DESC",
                (str(ctx.guild.id), str(target_user.id))
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            await ctx.send(f"No long-term memory facts stored for {target_user.mention}.", ephemeral=True)
            return

        lines = [f"{i}. [{r['importance']:.2f}] {r['content']}" for i, r in enumerate(rows, 1)]
        embed = discord.Embed(
            title=f"Memory: {target_user.display_name}",
            description="\n".join(lines)[:4096],
            color=discord.Color.purple(),
        )
        await ctx.send(embed=embed, ephemeral=True)

    # -------------------------------------------------------------------
    # /memoryclear
    # -------------------------------------------------------------------
    @commands.hybrid_command(
        name='memoryclear',
        aliases=['memcl'],
        help='Clear long-term facts. Users can clear their own; Admins can clear anyone.'
    )
    @app_commands.describe(user="The user whose memory to clear (defaults to you).")
    async def memory_clear_user(self, ctx, user: Optional[discord.User] = None):
        if ctx.guild is None:
            return await ctx.send("Memory commands are server-only.")

        target_user = user or ctx.author
        member = ctx.guild.get_member(ctx.author.id) if ctx.guild else None
        is_admin = bool(member and (member.guild_permissions.administrator or member.guild_permissions.manage_guild))

        if target_user.id != ctx.author.id and not is_admin:
            await ctx.send("❌ You can only clear your own memory.", ephemeral=True)
            return

        async with aiosqlite.connect(MEMORY_FILE_PATH) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM user_facts WHERE guild_id = ? AND user_id = ?",
                (str(ctx.guild.id), str(target_user.id))
            ) as cursor:
                row = await cursor.fetchone()
                count = row[0] if row else 0

            if count > 0:
                await db.execute(
                    "DELETE FROM user_facts WHERE guild_id = ? AND user_id = ?",
                    (str(ctx.guild.id), str(target_user.id))
                )
                await db.commit()
                if target_user.id == ctx.author.id:
                    msg = f"✅ I have forgotten {count} facts about you in this server."
                else:
                    msg = f"✅ Cleared {count} facts for {target_user.mention}."
                await ctx.send(msg, ephemeral=True)
            else:
                await ctx.send(f"No facts found for {target_user.display_name}.", ephemeral=True)

    # -------------------------------------------------------------------
    # /memorydelete
    # -------------------------------------------------------------------
    @commands.hybrid_command(name='memorydelete', aliases=['memdel'], help='Delete a specific memory fact by its list number.')
    @app_commands.describe(index="The list number of the fact to delete.", user="The user whose memory to delete (defaults to you).")
    async def memory_delete_index(self, ctx, index: int, user: Optional[discord.User] = None):
        if ctx.guild is None:
            return

        target_user = user or ctx.author
        member = ctx.guild.get_member(ctx.author.id) if ctx.guild else None
        is_admin = bool(member and (member.guild_permissions.administrator or member.guild_permissions.manage_guild))

        if target_user.id != ctx.author.id and not is_admin:
            await ctx.send("❌ You can only delete your own memory facts.", ephemeral=True)
            return

        async with aiosqlite.connect(MEMORY_FILE_PATH) as db:
            db.row_factory = aiosqlite.Row

            async with db.execute(
                "SELECT message_id, content FROM user_facts WHERE guild_id = ? AND user_id = ? ORDER BY importance DESC",
                (str(ctx.guild.id), str(target_user.id))
            ) as cursor:
                rows: list = list(await cursor.fetchall())

            if not rows or index < 1 or index > len(rows):
                await ctx.send(f"Invalid number. Use `/memorylist` to see the {len(rows)} stored facts.", ephemeral=True)
                return

        target_fact = rows[index - 1]
        async with aiosqlite.connect(MEMORY_FILE_PATH) as db:
            await db.execute("DELETE FROM user_facts WHERE message_id = ?", (target_fact['message_id'],))
            await db.commit()

        await ctx.send(f"✅ Deleted fact #{index} for {target_user.display_name}: *{target_fact['content'][:50]}...*", ephemeral=True)

    # -------------------------------------------------------------------
    # /migrate
    # -------------------------------------------------------------------
    @commands.hybrid_command(name='migrate', help='Migrate JSON memory to SQLite (Admin only).')
    @commands.has_permissions(administrator=True)
    async def migrate_memory(self, ctx):
        await ctx.defer(ephemeral=True)
        from utils.memory import run_migration
        success, message = await run_migration()
        await ctx.send(f"{'✅' if success else '❌'} {message}", ephemeral=True)

    # -------------------------------------------------------------------
    # /chatmode
    # -------------------------------------------------------------------
    @commands.hybrid_command(name='chatmode', help='Set conversation channel response mode (Admin only).')
    @app_commands.describe(mode="Mode can be `all`, `mentions`, or `smart`.")
    @commands.has_permissions(administrator=True)
    async def chat_mode(self, ctx, mode: str):
        mode = mode.lower().strip()
        if mode not in CHAT_RESPONSE_MODES:
            await ctx.send("Mode must be `all`, `mentions`, or `smart`.", ephemeral=True if ctx.interaction else False)
            return
        config = load_config()
        config["conversation_response_mode"] = mode
        save_config(config)
        descriptions = {
            "all":      "respond to every message in the conversation channel",
            "mentions": "respond only to bot mentions or replies",
            "smart":    "respond to bot mentions, replies, or attachments",
        }
        await ctx.send(
            f"Conversation response mode set to `{mode}`: {descriptions[mode]}.",
            ephemeral=True if ctx.interaction else False,
        )

    # -------------------------------------------------------------------
    # /autonomy
    # -------------------------------------------------------------------
    @app_commands.command(name="autonomy", description="Configure autonomy mode settings (Admin only).")
    @app_commands.describe(
        action="on / off / frequency",
        frequency="low / default / high — only used when action is 'frequency'"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def autonomy_cmd(
        self,
        interaction: discord.Interaction,
        action: str,
        frequency: Optional[str] = None,
    ):
        config = load_config()
        action = action.lower().strip()

        if action == "on":
            config["autonomy"] = True
            save_config(config)
            await interaction.response.send_message("Autonomy mode enabled.", ephemeral=True)
        elif action == "off":
            config["autonomy"] = False
            save_config(config)
            await interaction.response.send_message("Autonomy mode disabled.", ephemeral=True)
        elif action == "frequency":
            if frequency not in ("low", "default", "high"):
                await interaction.response.send_message(
                    "Frequency must be `low`, `default`, or `high`.", ephemeral=True
                )
                return
            config["autonomy_frequency"] = frequency
            save_config(config)
            await interaction.response.send_message(
                f"Autonomy frequency set to `{frequency}`.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "Unknown action. Use `on`, `off`, or `frequency`.", ephemeral=True
            )

    # -------------------------------------------------------------------
    # /botwhitelist add / remove / list
    # -------------------------------------------------------------------
    @commands.hybrid_group(name='botwhitelist', aliases=['bw'], help='Manage whitelisted bot IDs (Admin only).')
    @commands.has_permissions(administrator=True)
    async def whitelist_group(self, ctx):
        if ctx.invoked_subcommand is None:
            config = load_config()
            whitelist = config.get("whitelist_bot_ids", [1482682376655208548])
            if not whitelist:
                await ctx.send("No bots are whitelisted.", ephemeral=True if ctx.interaction else False)
                return
            lines = "\n".join(f"- `{bot_id}`" for bot_id in whitelist)
            await ctx.send(f"Whitelisted bots:\n{lines}", ephemeral=True if ctx.interaction else False)

    @whitelist_group.command(name='add', help='Add a bot ID to the whitelist.')
    async def whitelist_add(self, ctx, bot_id: int):
        config = load_config()
        whitelist = config.get("whitelist_bot_ids", [1482682376655208548])
        if bot_id in whitelist:
            await ctx.send(f"Bot `{bot_id}` is already whitelisted.", ephemeral=True if ctx.interaction else False)
            return
        whitelist.append(bot_id)
        config["whitelist_bot_ids"] = whitelist
        save_config(config)
        await ctx.send(f"Successfully added bot `{bot_id}` to the whitelist.", ephemeral=True if ctx.interaction else False)

    @whitelist_group.command(name='remove', help='Remove a bot ID from the whitelist.')
    async def whitelist_remove(self, ctx, bot_id: int):
        config = load_config()
        whitelist = config.get("whitelist_bot_ids", [1482682376655208548])
        if bot_id not in whitelist:
            await ctx.send(f"Bot `{bot_id}` is not in the whitelist.", ephemeral=True if ctx.interaction else False)
            return
        whitelist.remove(bot_id)
        config["whitelist_bot_ids"] = whitelist
        save_config(config)
        await ctx.send(f"Successfully removed bot `{bot_id}` from the whitelist.", ephemeral=True if ctx.interaction else False)


async def setup(bot):
    await bot.add_cog(GenAICog(bot))