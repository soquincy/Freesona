# utils/generation.py: Core AI generation pipeline, response types, and message sender.

import os
import re
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Union, Dict, Any

import discord
from dotenv import load_dotenv
from google import genai
from google.genai import types

from utils.memory import memory_to_contents, push_memory, inject_user_memory, extract_and_store_fact
from utils.security import sanitize_prompt, unsafe_output
from utils.config import LAST_DEBUG, get_model_name

load_dotenv()

logger = logging.getLogger("FreesonaBot")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
BOT_NAME       = os.getenv("BOT_NAME", "Bot")

# Split messaging
SPLIT_MIN_LENGTH     = 280
SPLIT_DELAY_BASE     = 1.2
SPLIT_DELAY_PER_CHAR = 0.012
SPLIT_DELAY_MAX      = 3.5

# Rate limiter
RATE_LIMIT       = 5
call_timestamps: list[float] = []

if not GOOGLE_API_KEY:
    raise EnvironmentError("GOOGLE_API_KEY missing.")

client = genai.Client(api_key=GOOGLE_API_KEY)

# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------

@dataclass
class MessageSegment:
    text: str
    delay: float = SPLIT_DELAY_BASE
    typing: bool = True
    attachment: Optional[str] = None

@dataclass
class ConversationResponse:
    segments: list[MessageSegment] = field(default_factory=list)
    reactions: list[str] = field(default_factory=list)
    suggested_gif: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return not self.segments

    def first_text(self) -> str:
        return " ".join(s.text for s in self.segments)

# ---------------------------------------------------------------------------
# Error classes
# ---------------------------------------------------------------------------

class GenerationError(Exception):
    pass

class TransientError(GenerationError):
    pass

class RateLimitError(GenerationError):
    pass

class MalformedResponseError(GenerationError):
    pass

class TimeoutGenerationError(GenerationError):
    pass

def _classify_error(e: Exception) -> GenerationError:
    msg = str(e).lower()
    if "429" in msg or "quota" in msg or "rate" in msg:
        return RateLimitError(str(e))
    if "timeout" in msg or "timed out" in msg:
        return TimeoutGenerationError(str(e))
    if "500" in msg or "503" in msg or "internal" in msg:
        return TransientError(str(e))
    return GenerationError(str(e))

_ERROR_MESSAGES: dict[type, str] = {
    RateLimitError:         "I'm a little overwhelmed right now — give me a moment.",
    TimeoutGenerationError: "That took too long. Try again?",
    TransientError:         "Something hiccupped on my end. Try again in a bit.",
    MalformedResponseError: "I got confused by that one. Try rephrasing?",
    GenerationError:        "Something went wrong. Try again.",
}

def _user_facing_error(e: GenerationError) -> str:
    return _ERROR_MESSAGES.get(type(e), _ERROR_MESSAGES[GenerationError])

# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

async def rate_limit():
    global call_timestamps
    now = time.time()
    call_timestamps = [t for t in call_timestamps if now - t < 60]
    if len(call_timestamps) >= RATE_LIMIT:
        wait_time = 60 - (now - call_timestamps[0])
        await asyncio.sleep(wait_time)
    call_timestamps.append(time.time())

# ---------------------------------------------------------------------------
# Text splitter + response builder
# ---------------------------------------------------------------------------

def split_into_segments(text: str) -> list[str]:
    if len(text) < SPLIT_MIN_LENGTH:
        return [text]

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if len(paragraphs) <= 1:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        chunks: list[str] = []
        current = ""
        for s in sentences:
            if len(current) + len(s) > 220 and current:
                chunks.append(current.strip())
                current = s
            else:
                current = (current + " " + s).strip() if current else s
        if current:
            chunks.append(current.strip())
        return chunks if len(chunks) > 1 else [text]

    return paragraphs


def build_response(text: str) -> ConversationResponse:
    segments_text = split_into_segments(text)
    segments = []
    for seg in segments_text:
        delay = min(
            SPLIT_DELAY_BASE + len(seg) * SPLIT_DELAY_PER_CHAR,
            SPLIT_DELAY_MAX
        )
        segments.append(MessageSegment(text=seg, delay=delay, typing=True))
    return ConversationResponse(segments=segments)


def clean_text(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_dot = cut.rfind('.')
    if last_dot > 1000:
        return cut[:last_dot + 1]
    return cut

# ---------------------------------------------------------------------------
# Multi-message sender
# ---------------------------------------------------------------------------

async def send_response(
    response: ConversationResponse,
    channel: discord.abc.Messageable,
    *,
    reply_to: Optional[discord.Message] = None,
) -> None:
    if not response.segments:
        return

    segments = [s for s in response.segments if s.text.strip()]
    if not segments:
        return

    for i, segment in enumerate(segments):
        if segment.typing and segment.delay > 0:
            async with channel.typing():
                await asyncio.sleep(segment.delay)

        if i == 0 and reply_to is not None:
            await reply_to.reply(segment.text)
        else:
            await channel.send(segment.text)

# ---------------------------------------------------------------------------
# Attachment helper
# ---------------------------------------------------------------------------

SUPPORTED_MIME_TYPES = {
    # Images
    "image/png", "image/jpeg", "image/webp", "image/gif", "image/heic", "image/heif",
    # Documents
    "application/pdf",
    "text/plain", "text/html", "text/css", "text/markdown", "text/csv",
    "text/xml", "text/rtf",
    "application/rtf",
    # Code
    "application/x-javascript", "text/javascript",
    "application/x-python", "text/x-python",
    # Audio
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/aiff",
    "audio/aac", "audio/ogg", "audio/flac", "audio/x-flac",
    # Video
    "video/mp4", "video/mpeg", "video/mov", "video/quicktime",
    "video/avi", "video/x-msvideo", "video/webm",
    "video/wmv", "video/x-ms-wmv", "video/3gpp",
}

async def extract_attachments(message: Optional[discord.Message]) -> list[tuple[bytes, str]]:
    """
    Extract all supported attachments (images + PDFs) from a message.
    Returns a list of (bytes, mime_type) tuples in attachment order.
    """
    if not message or not message.attachments:
        return []

    results = []
    for att in message.attachments:
        mime = att.content_type or ""
        # Strip parameters e.g. "image/png; charset=utf-8" -> "image/png"
        mime_base = mime.split(";")[0].strip()
        if mime_base not in SUPPORTED_MIME_TYPES:
            continue
        try:
            data = await att.read()
            results.append((data, mime_base))
        except Exception as e:
            logger.error(f"Failed to read attachment {att.filename}: {e}")

    return results

# ---------------------------------------------------------------------------
# Core generation
# ---------------------------------------------------------------------------

async def generate(
    prompt: Optional[Union[Dict[str, Any], str]],
    *,
    current_persona: str,
    channel_id: Optional[int] = None,
    guild_id: Optional[int] = None,
    user_id: Optional[int] = None,
    message_id: Optional[int] = None,
    apply_persona: bool = True,
    instruction_prefix: str = "",
    username: str = "",
    attachments: Optional[list[tuple[bytes, str]]] = None,
) -> ConversationResponse:
    await rate_limit()
    
    # Handle structured payload (dict) vs raw string
    if isinstance(prompt, dict):
        role = prompt.get("role", "user")
        text = prompt.get("content", "")
        reply = prompt.get("reply")
    else:
        role = "user"
        text = prompt or ""
        reply = None

    text = sanitize_prompt(text)
    user_message_text = text  # ← capture here, before text gets reassigned
    contents = memory_to_contents(channel_id) if channel_id is not None else []

    if reply:
        ref_role = reply.get("role", "user")
        api_role = "model" if ref_role == "model" else "user"
        # Clarify addressing rules to the model: always address the most recent message
        # (the one that triggered the bot) rather than the quoted message's author,
        # unless the user explicitly asks otherwise.
        clarification = (
            "When replying to a message that quotes or replies to another user's message, "
            "address the author of the most recent message (the one who triggered the bot). "
            "Do not attack, blame, or assume intent about the quoted message's author unless "
            "explicitly requested by the user."
        )
        contents.append(types.Content(role="system", parts=[types.Part(text=clarification)]))
        contents.append(types.Content(
            role=api_role,
            parts=[types.Part(
                text=f"[quoted from {reply['author']}]\n{reply['content']}"
            )]
        ))

    user_text = f"{instruction_prefix}\n\n{text}".strip() if instruction_prefix else text
    display_text = f"{username}: {text}" if username else text

    parts = []

    # Inject long-term user memory into system prompt
    persona = current_persona if apply_persona else ""
    if apply_persona and guild_id and user_id:
        memory_block = await inject_user_memory(guild_id, user_id, username)
        if memory_block:
            persona = f"{current_persona}\n\n{memory_block}"

    if user_text:
        parts.append(types.Part(text=user_text))
    for att_bytes, att_mime in (attachments or []):
        parts.append(types.Part.from_bytes(data=att_bytes, mime_type=att_mime))
    if not parts:
        parts.append(types.Part(text="Describe this."))

    contents.append(types.Content(role="user", parts=parts))

    if channel_id is not None:
        LAST_DEBUG[channel_id] = user_text

    try:
        config = types.GenerateContentConfig(
            system_instruction=persona if apply_persona else None,
            max_output_tokens=1024,
        )
        current_model = get_model_name()
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=current_model,
            contents=contents,
            config=config,
        )

        if not response or not response.text:
            raise MalformedResponseError("Empty response from model.")

        text = clean_text(response.text)
        text = re.sub(rf"^{re.escape(BOT_NAME)}\s*:\s*", "", text, flags=re.IGNORECASE).strip()

        if unsafe_output(text):
            logger.warning("Output blocked by safety filter.")
            return build_response("I can't respond to that.")

        if channel_id is not None and role in ("user", "webhook"):
            push_memory(channel_id, role, display_text, display_text,
                        client=client, model_name=current_model, username=username)
            push_memory(channel_id, "model", f"{BOT_NAME}: {text}", f"{BOT_NAME}: {text}",
                        client=client, model_name=current_model, username=BOT_NAME)

        # Fire fact extraction async — only for user messages (role="user")
        if guild_id and user_id and message_id and channel_id and user_message_text.strip() and role == "user":
            asyncio.create_task(extract_and_store_fact(
                message_content=user_message_text,
                display_name=username,
                guild_id=guild_id,
                user_id=user_id,
                message_id=message_id,
                channel_id=channel_id,
                client=client,
                model_name=current_model,
            ))

        return build_response(text)

    except GenerationError:
        raise
    except Exception as e:
        classified = _classify_error(e)
        logger.error(f"Gemini error [{type(classified).__name__}]: {e}")
        raise classified from e


async def safe_generate(
    prompt: Optional[Union[Dict[str, Any], str]],
    *,
    current_persona: str,
    attachments: Optional[list[tuple[bytes, str]]] = None,
    guild_id: Optional[int] = None,
    user_id: Optional[int] = None,
    message_id: Optional[int] = None,
    **kwargs,
) -> ConversationResponse:
    try:
        return await generate(
            prompt,
            current_persona=current_persona,
            attachments=attachments,
            guild_id=guild_id,
            user_id=user_id,
            message_id=message_id,
            **kwargs,
        )
    except GenerationError as e:
        msg = _user_facing_error(e)
        logger.warning(f"safe_generate swallowed error: {type(e).__name__}")
        return build_response(msg)
    except Exception as e:
        logger.error(f"safe_generate unexpected error: {e}")
        return build_response("Something went wrong. Try again.")