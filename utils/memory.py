# utils/memory.py: now in SQLite!

import os
import json
import asyncio
import logging
import aiosqlite
import re
from datetime import datetime, timezone
from google.genai import types

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
                        "INSERT OR IGNORE INTO user_facts VALUES (?, ?, ?, ?, ?, ?)",
                        (str(guild_id), str(user_id), f['content'], f['importance'], ts, str(m_id))
                    )
                    count += 1
            await db.commit()
        
        os.rename(JSON_PATH, f"{JSON_PATH}.bak")
        return True, f"Migrated {count} facts successfully."
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False, str(e)