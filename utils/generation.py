# utils/generation.py: Core AI generation pipeline, response types, and message sender.

import os
import re
import asyncio
import logging
import time
import re
from dataclasses import dataclass, field
from typing import Optional

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
        # Join segments with double newlines to keep paragraph formatting
        return "\n\n".join(s.text for s in self.segments if s.text.strip())

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

def split_into_segments(text):
    """
    Splits text into segments while preserving paragraph breaks.
    """
    # Split by double newlines first to keep paragraph structure
    paragraphs = text.split('\n\n')
    all_segments = []
    for para in paragraphs:
        # Split each paragraph into sentences
        sentences = re.split(r'(?<=[.!?])\s+', para)
        all_segments.extend([s.strip() for s in sentences if s.strip()])
    return all_segments


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
    prompt: str,
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
    prompt = sanitize_prompt(prompt)

    contents = memory_to_contents(channel_id) if channel_id is not None else []

    user_text = f"{instruction_prefix}\n\n{prompt}".strip() if instruction_prefix else prompt
    display_text = f"{username}: {prompt}" if username else prompt

    # Inject long-term user memory into system prompt
    persona = current_persona if apply_persona else ""
    if apply_persona and guild_id and user_id:
        memory_block = inject_user_memory(guild_id, user_id, username)
        if memory_block:
            persona = f"{current_persona}\n\n{memory_block}"

    parts = []
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
        model_name = get_model_name()
        config = types.GenerateContentConfig(
            system_instruction=persona if apply_persona else None,
            max_output_tokens=1024,
        )
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=contents,
            config=config,
        )

        if not response or not response.text:
            raise MalformedResponseError("Empty response from model.")

        text = clean_text(response.text)

        if unsafe_output(text):
            logger.warning("Output blocked by safety filter.")
            return build_response("I can't respond to that.")

        if channel_id is not None:
            # Use display_text (username-prefixed) as the model-facing text so Gemini
            # can distinguish between speakers in a multi-user channel. display_text is
            # already formatted as "Username: <prompt>" in generate(). For model turns
            # we keep the same convention with BOT_NAME as the speaker prefix.
            push_memory(channel_id, "user", display_text, display_text,
                        client=client, model_name=model_name, username=username)
            push_memory(channel_id, "model", f"{BOT_NAME}: {text}", f"{BOT_NAME}: {text}",
                        client=client, model_name=model_name, username=BOT_NAME)

        # Fire fact extraction async — never blocks response
        if guild_id and user_id and message_id and channel_id and prompt.strip():
            asyncio.create_task(extract_and_store_fact(
                message_content=prompt,
                display_name=username,
                guild_id=guild_id,
                user_id=user_id,
                message_id=message_id,
                channel_id=channel_id,
                client=client,
                model_name=model_name,
            ))

        return build_response(text)

    except GenerationError:
        raise
    except Exception as e:
        classified = _classify_error(e)
        logger.error(f"Gemini error [{type(classified).__name__}]: {e}")
        raise classified from e


async def safe_generate(
    prompt: str,
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
