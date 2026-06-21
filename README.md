# Freesona - The Discord Bot You Customize

![Freesona Banner](assets/b_freesona-01.png)

Most AI Discord bots give you a product. Verba, MEE6, and every other hosted platform give you a personality someone else built, running on infrastructure you don't control, with a ceiling you'll eventually hit.

Freesona is different. It's a free, open alternative to hosted persona bots — with no ceiling. Fork it, drop in your API key, and get a self-hosted bot that can be a convincing AI character, a focused server utility, or both.

No credits. No voting. No "upgrade to unlock." Just a bot that does what you tell it.

→ [Features](docs/features.md) · [Commands](docs/commands.md) · [Discord](https://discord.gg/vXPRs2cHSE)

---

## What makes it worth forking

**The persona system is built to feel alive.** `/setpersona` opens a button-based editor for structured persona fields. Changes take effect immediately, no restart required.

**It remembers — short and long term.** Short-term: rolling per-channel context with automatic summarization. Long-term: facts about each user are extracted, scored by importance, and persisted to disk — injected automatically into future conversations.

**It knows who's talking.** Every message is prefixed with the speaker's display name before being sent to the model, so Gemini can distinguish between multiple users in the same channel.

**It won't double-reply.** A per-user debounce collapses rapid successive messages into one response.

**It can chime in on its own — intelligently.** Autonomous mode uses a confidence-scored intent evaluator, not random chance. Per-channel cooldowns prevent it from dominating a conversation.

**It handles more than text.** Attach images, PDFs, audio, video, or code files — all processed through Gemini's multimodal pipeline.

**It's built to be extended.** Logic lives in `utils/` — generation, memory, persona, intent, security, search, and config are all separate modules. See [utils/README.md](utils/README.md).

---

## Getting Started

```bash
git clone https://github.com/soquincy/Freesona.git
cd Freesona
pip install -r requirements.txt
```

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
# Discord + Gemini Model
BOT_TOKEN=YOUR_DISCORD_BOT_TOKEN
CHANNEL_ID=YOUR_LOG_CHANNEL_ID
GOOGLE_API_KEY=YOUR_GEMINI_API_KEY
MODEL_NAME=gemini-flash-lite-latest
BOT_NAME=Freesona

# Complimentary Tokens
LOGOKIT_TOKEN=YOUR_LOGOKIT_KEY_HERE # for logos in RSS

# Math Tokens
WOLFRAM_APPID_SHORT=YOUR_WOLFRAM_APPID_SHORT
WOLFRAM_APPID_LLM=YOUR_WOLFRAM_APPID_LLM

# Local
AI_PERSONA_FILE=persona.txt
AI_PERSONA_JSON_FILE=persona.json
AI_PERSONAS_FILE=personas.json
CONFIG_FILE_PATH=config.json
MEMORY_FILE_PATH=memory.db

# Cloud (Railway/Render — requires /data volume mount)
# AI_PERSONA_FILE=/data/persona.txt
# AI_PERSONA_JSON_FILE=/data/persona.json
# AI_PERSONAS_FILE=/data/personas.json
# CONFIG_FILE_PATH=/data/config.json
# MEMORY_FILE_PATH=/data/memory.json
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
| `config.json` | Prefix, conversation channel, autonomy settings |
| `persona.json` | Active persona fields |
| `personas.json` | Saved persona presets |
| `memory.db` | Long-term user facts, keyed by `guild_id:user_id` |

Short-term conversation memory is in-session only — cleared on restart or via `/clearmemory`.

---

## Runtime Controls

Admins can control optional modules without editing `main.py`:

```text
/module list
/module enable <name>
/module disable <name>
/module reload <name>
```

The bot owner can switch Gemini models without restarting:

```text
/model show
/model set <model>
/model reset
```

Conversation channel behavior can be narrowed with `/chatmode all`, `/chatmode mentions`, or `/chatmode smart`.

RSS/Atom feeds can be read and managed with:

```text
/rss list
/rss latest <feed>
/rss add <name> <url>
/rss remove <name>
```

---

## Acknowledgements

* [discord.py](https://discordpy.readthedocs.io/)
* [Google Gemini](https://ai.google.dev/)
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

### Medium-term

* [ ] Multi-provider support — swap AI providers without changing command code
* [ ] Message claiming system for multi-instance deployments
* [x] RSS monitors — post matching feed items into selected channels
* [ ] Optional generation logging — instance operators can enable local-only logs for abuse reporting and debugging; disabled by default, no data leaves the host

### Long-term

* [ ] Knowledge base — `/kbadd`, `/kblist`, `/kbdelete`
* [ ] Web dashboard via FastAPI — `fastapi_server.py` is already in the repo
