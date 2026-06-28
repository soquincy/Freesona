# Freesona - The Discord Bot You Customize

![Freesona Banner](assets/b_freesona-01.png)

Most AI Discord bots give you a product. Verba, MEE6, and every other hosted platform give you a personality someone else built, running on infrastructure you don't control, with a ceiling you'll eventually hit.

Freesona is different. It's a free, open alternative to hosted persona bots — with no ceiling. Fork it, drop in your API key, and get a self-hosted bot that can be a convincing AI character, a focused server utility, or both.

No credits. No voting. No "upgrade to unlock." Just a bot that does what you tell it.

Freesona is a **BYOK** (Bring Your Own Key) project — you provide your own API credentials, and everything runs on your infrastructure.

→ [Features](docs/features.md) · [Commands](docs/commands.md) · [Discord](https://discord.gg/vXPRs2cHSE)

---

## What makes it worth forking

**The persona system is built to feel alive.** `/setpersona` opens a button-based editor for structured persona fields. Changes take effect immediately, no restart required.

**It remembers people.** Facts about each user are extracted from conversation, scored by importance, and persisted to SQLite — injected automatically into future conversations. Conversation history itself is maintained server-side via the Interactions API, so context survives across messages without local storage overhead.

**It knows who's talking.** Messages are attributed to their sender by display name before reaching the model, so it can tell users apart in multi-user channels.

**It won't double-reply.** A per-user-per-channel debounce collapses rapid successive messages into one response.

**It can chime in on its own — intelligently.** Autonomous mode uses a confidence-scored intent evaluator, not random chance. Per-channel cooldowns prevent it from dominating a conversation.

**It handles more than text.** Attach images, PDFs, audio, video, or code files — all processed through the active provider's multimodal pipeline.

**It can target multiple AI backends.** The generation pipeline supports Gemini, OpenAI, Ollama, NVIDIA NIM, Azure AI Foundry, Groq, and OpenRouter through a shared provider abstraction. The same commands work across all of them.

**It has an optional local knowledge base.** ChromaDB-backed semantic retrieval is available for injecting relevant documents into generation context. Full `/kbadd`, `/kblist`, and `/kbdelete` commands are planned on top of this foundation.

**It's built to be extended.** Logic lives in `utils/` — generation, memory, persona, intent, security, search, config, provider routing, and ChromaDB are all separate modules. See [utils/README.md](utils/README.md).

---

## Getting Started

```bash
git clone https://github.com/soquincy/Freesona.git
cd Freesona
pip install -r requirements.txt
```

Note for Windows users: Python's `zoneinfo` may lack IANA time zone data on some Windows installs. Install `tzdata` in your environment so `/settimezone` (and other `ZoneInfo` lookups) work correctly:

```powershell
.venv\Scripts\pip.exe install tzdata
```

`tzdata` is included in `requirements.txt` so it will be installed with `pip install -r requirements.txt` on new setups.

Before pushing changes, run the local checks:

```bash
python scripts/check_project.py
```

On Windows PowerShell, you can also run:

```powershell
.\scripts\check.ps1
```

To make Git run the checks before pushes to `dev`, enable the included hook once:

```bash
git config core.hooksPath .githooks
```

Create a `.env` file:

```dotenv
# Discord
BOT_TOKEN=YOUR_DISCORD_BOT_TOKEN
CHANNEL_ID=YOUR_LOG_CHANNEL_ID
BOT_NAME=Freesona

# AI Provider
AI_PROVIDER=gemini          # gemini | openai | ollama | nim | azure | groq | openrouter
AI_PROVIDER_MODEL=          # override the default model for the chosen provider
MODEL_NAME=gemini-flash-lite-latest
GOOGLE_API_KEY=YOUR_GEMINI_API_KEY

# Provider API keys (set the one matching your AI_PROVIDER)
# OPENAI_API_KEY=
# OPENAI_BASE_URL=https://api.openai.com/v1/chat/completions
# OLLAMA_BASE_URL=http://localhost:11434/api/chat
# NVIDIA_API_KEY=
# NVIDIA_NIM_BASE_URL=https://integrate.api.nvidia.com/v1/chat/completions
# AZURE_AI_KEY=
# AZURE_AI_BASE_URL=        # your Azure AI Foundry endpoint
# GROQ_API_KEY=
# OPENROUTER_API_KEY=
# OPENROUTER_SITE_URL=
# OPENROUTER_SITE_NAME=Freesona

# Search (optional legacy fallback for /search)
GOOGLE_SEARCH_API_KEY=
SEARCH_ENGINE_ID=

# ChromaDB (optional — required for knowledge base retrieval)
CHROMA_COLLECTION=freesona
CHROMA_PERSIST_DIRECTORY=./.chroma

# Complimentary tokens
LOGOKIT_TOKEN=YOUR_LOGOKIT_KEY_HERE   # for source logos in RSS embeds
MVSEP_API_KEY=YOUR_MVSEP_API_KEY
MVSEP_WEBHOOK_URL=https://your-public-host.example.com/webhooks/mvsep
MVSEP_WEBHOOK_SEND_MAIL_ON_ERROR=false
WOLFRAM_APPID_SHORT=YOUR_WOLFRAM_APPID_SHORT
WOLFRAM_APPID_LLM=YOUR_WOLFRAM_APPID_LLM

# File paths (local)
AI_PERSONA_FILE=persona.txt
AI_PERSONA_JSON_FILE=persona.json
AI_PERSONAS_FILE=personas.json
AI_PERSONA=You are a helpful assistant.
CONFIG_FILE_PATH=config.json
MEMORY_FILE_PATH=memory.db
WARNINGS_FILE_PATH=warnings.db
ANNIVERSARIES_FILE_PATH=anniversaries.db

# File paths (cloud — Railway/Render, requires /data volume mount)
# AI_PERSONA_FILE=/data/persona.txt
# AI_PERSONA_JSON_FILE=/data/persona.json
# AI_PERSONAS_FILE=/data/personas.json
# CONFIG_FILE_PATH=/data/config.json
# MEMORY_FILE_PATH=/data/memory.db
# WARNINGS_FILE_PATH=/data/warnings.db
# ANNIVERSARIES_FILE_PATH=/data/anniversaries.db
```

| Environment | Path prefix | Notes |
| :--- | :--- | :--- |
| **Local** | `./` | Files saved in project folder |
| **Railway** | `/data/` | Requires volume mounted to `/data` |
| **Render** | `/data/` | Create files manually in environment page |

Without a persistent volume on cloud hosts, file changes won't survive a redeploy.

---

## Persistence & Storage

| File | What it stores |
| :--- | :--- |
| `config.json` | Prefix, conversation channel, autonomy settings, module states |
| `persona.json` | Active persona fields |
| `personas.json` | Saved persona presets |
| `memory.db` | Long-term user facts, keyed by `guild_id:user_id` |
| `warnings.db` | Per-guild moderation warnings with hex IDs and timestamps |
| `anniversaries.db` | User-claimed anniversary entries with optional calendar sync metadata |
| `.chroma/` | ChromaDB vector store for knowledge base retrieval (optional) |

Conversation history is maintained server-side via the Interactions API — no local per-channel message log. Clear it per-channel with `/clearmemory`.

---

## Runtime Controls

Admins can control optional modules without editing `main.py`:

```text
/module list
/module enable <name>
/module disable <name>
/module reload <name>
```

The bot owner can switch providers and models without restarting, sync global slash commands, and inspect the active config:

```text
/model show
/model set <model>
/model reset
/sync
/dumpconfig
```

Timezone and autonomy are also configurable at runtime:

```text
/settimezone <timezone>
/timezone
/autonomy on
/autonomy off
/autonomy frequency <low/default/high>
/chatmode all
/chatmode mentions
/chatmode smart
```

RSS/Atom feeds can be read and managed with:

```text
/rss list
/rss latest <feed>
/rss add <name> <url>
/rss remove <name>
/rss setchannel <#channel>
/rss clearchannel
```

---

## Acknowledgements

* [discord.py](https://discordpy.readthedocs.io/)
* [Google Gemini](https://ai.google.dev/)
* [OpenAI](https://platform.openai.com/)
* [Ollama](https://ollama.com/)
* [NVIDIA NIM](https://developer.nvidia.com/nim)
* [Azure AI Foundry](https://ai.azure.com/)
* [Groq](https://groq.com/)
* [OpenRouter](https://openrouter.ai/)
* [ChromaDB](https://www.trychroma.com/)
* [Wolfram\|Alpha](https://developer.wolframalpha.com/)
* [yt-dlp](https://github.com/yt-dlp/yt-dlp)
* [MVSEP](https://mvsep.com/)

---

## License

Licensed under the **MIT License**. See [LICENSE](LICENSE).

---

## Roadmap

### Short-term

* [x] Finish the cog folder migration and clean up stale imports
* [x] Fix help-panel interaction failures and make the help view resilient
* [x] Make `/botwhitelist` show the current whitelist entries directly
* [x] Migrate short-term memory from local rolling context to server-side Interactions API

### Medium-term

* [x] Multi-provider support — swap AI providers without changing command code (Gemini, OpenAI, Ollama, NVIDIA NIM, Azure AI Foundry, Groq, OpenRouter)
* [x] RSS monitors — post matching feed items into selected channels
* [x] Warning system — per-guild moderation warnings with hex IDs, auto-threshold actions, and DM notifications
* [x] Anniversary tracking — generic `anniversaries.db` backend for user-claimed date entries with optional calendar sync
* [ ] Full knowledge base commands — `/kbadd`, `/kblist`, `/kbdelete` on top of the existing ChromaDB retrieval layer
* [ ] Optional generation logging — local-only logs for abuse reporting and debugging; disabled by default, no data leaves the host

### Long-term

* [ ] Web dashboard via FastAPI — `fastapi_server.py` is already in the repo
* [ ] Message claiming system for multi-instance deployments
