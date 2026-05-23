# utils/memory.py: Conversation memory and long-term user memory.
# Short-term: per-channel rolling context window with automatic summarization.
# Long-term: per-user, per-guild fact storage persisted to disk with importance scoring.

import os
import json
import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from google.genai import types

logger = logging.getLogger("FreesonaBot")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

MEMORY_LIMIT   = 5
SUMMARY_PROMPT = "Summarize this conversation in 2-3 sentences, keeping key context only:"

MEMORY_FILE_PATH     = os.getenv("MEMORY_FILE_PATH", "./memory.json")
MAX_FACTS_PER_USER   = 20
MIN_IMPORTANCE       = 0.3   # facts below this are dropped on next write

FACT_EXTRACT_PROMPT = (
    "You are a memory assistant. Given the following user message, determine if it reveals "
    "any fact worth remembering about the user (their name, job, location, interests, preferences, "
    "relationships, ongoing projects, or anything personally significant). "
    "If yes, respond with a JSON object exactly like this: "
    '{"content": "<one concise fact>", "importance": <float 0.0-1.0>} '
    "where importance reflects how useful this fact is for future conversations. "
    "If there is nothing worth remembering, respond with exactly: null"
)

# ---------------------------------------------------------------------------
# Short-term memory (in-session, per channel)
# ---------------------------------------------------------------------------

channel_memory:  dict[int, deque] = {}
channel_summary: dict[int, str]   = {}


def get_memory(channel_id: int) -> deque:
    if channel_id not in channel_memory:
        channel_memory[channel_id] = deque(maxlen=MEMORY_LIMIT)
    return channel_memory[channel_id]


def memory_to_contents(channel_id: int) -> list:
    contents = []
    # Tracks the username per content index — avoids monkey-patching types.Content
    content_usernames: dict[int, str] = {}

    summary = channel_summary.get(channel_id)

    if summary:
        contents.append(types.Content(
            role="user",
            parts=[types.Part(text=f"[Conversation summary so far: {summary}]")]
        ))
        contents.append(types.Content(
            role="model",
            parts=[types.Part(text="Understood, I have context from earlier.")]
        ))

    for entry in get_memory(channel_id):
        last_idx  = len(contents) - 1
        last      = contents[last_idx] if contents else None
        same_role = last is not None and last.role == entry["role"]
        same_user = entry.get("username", "") == content_usernames.get(last_idx, "")

        if same_role and same_user:
            assert last is not None  # guaranteed by same_role check above
            last.parts[0].text += f"\n{entry['text']}"
        else:
            turn = types.Content(
                role=entry["role"],
                parts=[types.Part(text=entry["text"])]
            )
            contents.append(turn)
            content_usernames[len(contents) - 1] = entry.get("username", "")

    return contents


async def maybe_summarize(channel_id: int, client, model_name: str):
    mem = get_memory(channel_id)
    if len(mem) < MEMORY_LIMIT:
        return
    oldest = list(mem)[:MEMORY_LIMIT // 2]
    block  = "\n".join(e["display"] for e in oldest)
    prompt = f"{SUMMARY_PROMPT}\n\n{block}"
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(max_output_tokens=200)
        )
        if response and response.text:
            prev = channel_summary.get(channel_id, "")
            channel_summary[channel_id] = (prev + " " + response.text.strip()).strip()
    except Exception as e:
        logger.warning(f"Summary failed: {e}")


def push_memory(channel_id: int, role: str, text: str, display: str = "", *, client=None, model_name: str = "", username: str = ""):
    if client and model_name:
        asyncio.create_task(maybe_summarize(channel_id, client, model_name))
    get_memory(channel_id).append({
        "role":     role,
        "text":     text,
        "display":  display or text,
        "username": username,  # tracked to prevent cross-user turn merging
    })

# ---------------------------------------------------------------------------
# Long-term memory — data structures
# ---------------------------------------------------------------------------

@dataclass
class UserFact:
    content:    str
    importance: float
    timestamp:  str
    message_id: str
    channel_id: str

    def to_dict(self) -> dict:
        return {
            "content":    self.content,
            "importance": self.importance,
            "timestamp":  self.timestamp,
            "message_id": self.message_id,
            "channel_id": self.channel_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UserFact":
        return cls(
            content=    d["content"],
            importance= d["importance"],
            timestamp=  d.get("timestamp", ""),
            message_id= d.get("message_id", ""),
            channel_id= d.get("channel_id", ""),
        )


@dataclass
class UserMemory:
    display_name: str
    facts: list[UserFact] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "display_name": self.display_name,
            "facts":        [f.to_dict() for f in self.facts],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "UserMemory":
        return cls(
            display_name=d.get("display_name", ""),
            facts=[UserFact.from_dict(f) for f in d.get("facts", [])],
        )

    def add_fact(self, fact: UserFact):
        # Deduplicate by message_id
        existing_ids = {f.message_id for f in self.facts}
        if fact.message_id in existing_ids:
            return

        self.facts.append(fact)

        # Drop facts below minimum importance
        self.facts = [f for f in self.facts if f.importance >= MIN_IMPORTANCE]

        # Cap at MAX_FACTS_PER_USER, dropping lowest importance first
        if len(self.facts) > MAX_FACTS_PER_USER:
            self.facts.sort(key=lambda f: f.importance, reverse=True)
            self.facts = self.facts[:MAX_FACTS_PER_USER]

    def to_prompt_block(self) -> str:
        if not self.facts:
            return ""
        sorted_facts = sorted(self.facts, key=lambda f: f.importance, reverse=True)
        lines = [f"- {f.content}" for f in sorted_facts]
        return f"[Known facts about {self.display_name}]\n" + "\n".join(lines)

# ---------------------------------------------------------------------------
# Long-term memory — I/O
# ---------------------------------------------------------------------------

def _make_key(guild_id: int, user_id: int) -> str:
    return f"{guild_id}:{user_id}"


# ---------------------------------------------------------------------------
# In-memory cache + async lock
# Prevents concurrent writes from clobbering each other and keeps
# file I/O off the main event loop.
# ---------------------------------------------------------------------------

_memory_cache: dict[str, dict] = {}
_cache_loaded: bool = False
_memory_lock: asyncio.Lock = asyncio.Lock()


def _load_cache_sync():
    """Load from disk into cache synchronously — only called once at startup."""
    global _memory_cache, _cache_loaded
    if os.path.exists(MEMORY_FILE_PATH):
        try:
            with open(MEMORY_FILE_PATH, "r", encoding="utf-8") as f:
                _memory_cache = json.load(f)
        except Exception as e:
            logger.error(f"Long-term memory load error: {e}")
            _memory_cache = {}
    _cache_loaded = True


def _ensure_cache_loaded():
    if not _cache_loaded:
        _load_cache_sync()


async def _flush_cache():
    """Write the in-memory cache to disk. Must be called under _memory_lock."""
    os.makedirs(
        os.path.dirname(MEMORY_FILE_PATH) if os.path.dirname(MEMORY_FILE_PATH) else ".",
        exist_ok=True
    )
    def _write():
        with open(MEMORY_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(_memory_cache, f, indent=2, ensure_ascii=False)

    await asyncio.to_thread(_write)


def load_user_memory(guild_id: int, user_id: int) -> Optional[UserMemory]:
    _ensure_cache_loaded()
    key = _make_key(guild_id, user_id)
    if key in _memory_cache:
        return UserMemory.from_dict(_memory_cache[key])
    return None


async def save_user_memory_async(guild_id: int, user_id: int, memory: UserMemory):
    """Async, atomic write — safe for concurrent callers."""
    _ensure_cache_loaded()
    key = _make_key(guild_id, user_id)
    async with _memory_lock:
        _memory_cache[key] = memory.to_dict()
        await _flush_cache()


def inject_user_memory(guild_id: int, user_id: int, display_name: str) -> str:
    """
    Returns a prompt block of known facts about the user.
    Returns empty string if no facts exist.
    Also schedules a display_name update if it changed.
    """
    mem = load_user_memory(guild_id, user_id)
    if mem is None:
        return ""

    if mem.display_name != display_name:
        mem.display_name = display_name
        asyncio.create_task(save_user_memory_async(guild_id, user_id, mem))

    return mem.to_prompt_block()

# ---------------------------------------------------------------------------
# Long-term memory — fact extraction (async, non-blocking)
# ---------------------------------------------------------------------------

async def extract_and_store_fact(
    message_content: str,
    display_name:    str,
    guild_id:        int,
    user_id:         int,
    message_id:      int,
    channel_id:      int,
    client,
    model_name:      str,
):
    """
    Runs after a user message is processed.
    Asks Gemini if the message contains a memorable fact.
    Stores it if yes, silently skips if no or on error.
    Non-blocking — always called via asyncio.create_task().
    """
    if not message_content.strip():
        return

    prompt = f"{FACT_EXTRACT_PROMPT}\n\nUser message: {message_content}"
    raw = ""  # initialized here so it's always bound in exception handlers

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(max_output_tokens=100)
        )

        if not response or not response.text:
            return

        raw = response.text.strip()

        if raw.lower() == "null" or not raw:
            return

        # Strip markdown code fences if model wrapped it
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        parsed = json.loads(raw)
        content    = parsed.get("content", "").strip()
        importance = float(parsed.get("importance", 0.0))

        if not content or importance < MIN_IMPORTANCE:
            return

        fact = UserFact(
            content=    content,
            importance= importance,
            timestamp=  datetime.now(timezone.utc).isoformat(),
            message_id= str(message_id),
            channel_id= str(channel_id),
        )

        mem = load_user_memory(guild_id, user_id)
        if mem is None:
            mem = UserMemory(display_name=display_name)

        mem.display_name = display_name  # always keep current
        mem.add_fact(fact)
        await save_user_memory_async(guild_id, user_id, mem)

        logger.info(
            f"Stored fact for {guild_id}:{user_id} "
            f"(importance={importance:.2f}): {content[:60]}"
        )

    except json.JSONDecodeError:
        logger.debug(f"Fact extraction returned non-JSON: {raw[:80] if raw else "(empty)"}")
    except Exception as e:
        logger.warning(f"Fact extraction failed: {e}")