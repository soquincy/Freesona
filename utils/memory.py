# utils/memory.py: now in SQLite!

import os
import json
import asyncio
import logging
import aiosqlite
import re
from datetime import datetime, timezone
from google.genai import types

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger("FreesonaBot")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MEMORY_FILE_PATH = os.getenv("MEMORY_FILE_PATH", "./memory.db")
JSON_PATH = os.getenv("LEGACY_PATH", "./memory.json")

MAX_FACTS_PER_USER = 20
MIN_IMPORTANCE = 0.3

FACT_EXTRACT_PROMPT = (
    "You are a memory assistant. Given the following user message, determine if it reveals "
    "any fact worth remembering about the user. "
    "Respond with a JSON object: "
    '{"content": "<one concise fact>", "importance": <float 0.0-1.0>} '
    "or exactly: null"
)

# ---------------------------------------------------------------------------
# Short-term memory (in-session, per channel)
# ---------------------------------------------------------------------------

from collections import deque
from google.genai import types as _types

MEMORY_LIMIT   = 5
SUMMARY_PROMPT = "Summarize this conversation in 2-3 sentences, keeping key context only:"

channel_memory:  dict[int, deque] = {}
channel_summary: dict[int, str]   = {}


def get_memory(channel_id: int) -> deque:
    if channel_id not in channel_memory:
        channel_memory[channel_id] = deque(maxlen=MEMORY_LIMIT)
    return channel_memory[channel_id]


def memory_to_contents(channel_id: int) -> list:
    contents = []
    content_usernames: dict[int, str] = {}
    summary = channel_summary.get(channel_id)

    if summary:
        contents.append(_types.Content(
            role="user",
            parts=[_types.Part(text=f"[Conversation summary so far: {summary}]")]
        ))
        contents.append(_types.Content(
            role="model",
            parts=[_types.Part(text="Understood, I have context from earlier.")]
        ))

    for entry in get_memory(channel_id):
        last_idx  = len(contents) - 1
        last      = contents[last_idx] if contents else None
        api_role  = "model" if entry["role"] == "model" else "user"
        same_role = last is not None and last.role == api_role
        same_user = entry.get("username", "") == content_usernames.get(last_idx, "")

        if same_role and same_user and last is not None:
            merged_text = last.parts[0].text + f"\n{entry['text']}"
            contents[last_idx] = _types.Content(
                role=last.role,
                parts=[_types.Part(text=merged_text)]
            )
        else:
            contents.append(_types.Content(
                role=api_role,
                parts=[_types.Part(text=entry["text"])]
            ))
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
            contents=[_types.Content(role="user", parts=[_types.Part(text=prompt)])],
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
        "username": username,
    })


async def inject_user_memory(guild_id: int, user_id: int, display_name: str) -> str:
    """Async wrapper around get_user_facts_prompt for use in generation.py."""
    return await get_user_facts_prompt(guild_id, user_id, display_name)

# ---------------------------------------------------------------------------
# Database Core
# ---------------------------------------------------------------------------

async def init_db():
    """Initializes the SQLite database and creates the table."""
    async with aiosqlite.connect(MEMORY_FILE_PATH) as db:
        await db.execute('''
        CREATE TABLE IF NOT EXISTS user_facts (
            guild_id TEXT,
            user_id TEXT,
            content TEXT,
            importance REAL,
            timestamp TEXT,
            message_id TEXT,
            channel_id TEXT,
            PRIMARY KEY (message_id)
        )
    ''')
        # Indexing for faster lookups
        await db.execute("CREATE INDEX IF NOT EXISTS idx_user_guild ON user_facts (user_id, guild_id)")
        await db.commit()

async def get_user_facts_prompt(guild_id: int, user_id: int, display_name: str) -> str:
    """Returns a formatted string of facts for the LLM system prompt."""
    async with aiosqlite.connect(MEMORY_FILE_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT content FROM user_facts WHERE guild_id = ? AND user_id = ? ORDER BY importance DESC",
            (str(guild_id), str(user_id))
        ) as cursor:
            rows = await cursor.fetchall()
            if not rows:
                return ""
            
            lines = [f"- {row['content']}" for row in rows]
            return f"\n[Known facts about {display_name}]\n" + "\n".join(lines)

# ---------------------------------------------------------------------------
# Fact Extraction & Storage
# ---------------------------------------------------------------------------

async def extract_and_store_fact(message_content, display_name, guild_id, user_id, message_id, channel_id, client, model_name):
    if not message_content.strip():
        return

    prompt = f"{FACT_EXTRACT_PROMPT}\n\nUser message: {message_content}"
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])]
        )

        if not response or not response.text:
            return

        raw = response.text.strip()
        if raw.lower() == "null": 
            return

        # Clean JSON markdown blocks
        if "```" in raw:
            raw = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()

        parsed = json.loads(raw)
        content = parsed.get("content", "").strip()
        importance = float(parsed.get("importance", 0.0))

        if not content or importance < MIN_IMPORTANCE:
            return

        async with aiosqlite.connect(MEMORY_FILE_PATH) as db:
            # Insert new fact
            await db.execute(
                "INSERT OR IGNORE INTO user_facts VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(guild_id),
                    str(user_id),
                    content,
                    importance,
                    datetime.now(timezone.utc).isoformat(),
                    str(message_id),
                    str(channel_id)
                )
            )

            # Prune to keep only top 20
            await db.execute('''
                DELETE FROM user_facts 
                WHERE guild_id = ? AND user_id = ? AND message_id NOT IN (
                    SELECT message_id FROM user_facts 
                    WHERE guild_id = ? AND user_id = ? 
                    ORDER BY importance DESC LIMIT ?
                )
            ''', (str(guild_id), str(user_id), str(guild_id), str(user_id), MAX_FACTS_PER_USER))
            
            await db.commit()

    except Exception as e:
        logger.warning(f"Fact extraction failed: {e}")

# ---------------------------------------------------------------------------
# Migration Logic
# ---------------------------------------------------------------------------

async def run_migration():
    """Migrates data from memory.json to SQLite if the file exists."""
    if not os.path.exists(JSON_PATH):
        return False, "No JSON file found."

    try:
        async with aiosqlite.connect(MEMORY_FILE_PATH) as db:
            with open(JSON_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            count = 0
            for key, user_data in data.items():
                if ":" not in key: 
                    continue
                
                guild_id, user_id = key.split(':')
                
                for f in user_data.get('facts', []):
                    m_id = f.get('message_id', f"migrated_{count}_{user_id}")
                    ts = f.get('timestamp', datetime.now(timezone.utc).isoformat())
                    
                    await db.execute(
                        "INSERT OR IGNORE INTO user_facts VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (str(guild_id), str(user_id), f['content'], f['importance'], ts, str(m_id), "0")
                    )
                    count += 1
            await db.commit()
        
        os.rename(JSON_PATH, f"{JSON_PATH}.bak")
        return True, f"Migrated {count} facts successfully."
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False, str(e)