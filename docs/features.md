# Features

## Persona System

Freesona's persona is split into five structured fields edited through a button-based `/setpersona` panel — no restart required.

| Field | Edited via |
| :--- | :--- |
| Core Personality & Traits | `/setpersona` |
| Background & History | `/setpersona` |
| Beliefs, Likes & Dislikes | `/setpersona` |
| Language & Communication Style | `/setpersona` |
| System Instructions | `/setpersona` |

Changes take effect immediately. The assembled persona is injected as the system instruction on every generation call, assembled in XML-tagged blocks for clarity.

**Persona profiles** — save, load, list, and delete named presets with `/personasave`, `/personaload`, `/personalist`, `/personadelete`. Useful for switching between characters or server contexts.

**Persona lock** — `/personalock` prevents accidental overwrites. `/personaunlock` to re-enable editing.

**Legacy support** — if a `persona.txt` file exists and no `persona.json` is found, the bot falls back to it automatically. Existing installs don't break on upgrade.

**Debug** — `/debugpersona` shows the fully assembled persona, last prompt sent to the model, active provider and model, lock state, and autonomy status.

---

## Memory

### Short-term (per channel, server-side)

Conversation continuity is handled server-side via the Interactions API `previous_interaction_id`. Each response chain is tracked per channel; the bot passes the last interaction ID to continue the conversation without maintaining a local message log. Cleared per channel with `/clearmemory`.

### Long-term (per user, per guild, persisted)

After each user message, the bot runs a background fact extraction pass — asking the active model whether the message reveals anything worth remembering (name, job, location, interests, projects, relationships). Facts are scored by importance (0.0–1.0), deduplicated by message ID, and capped at 20 per user. Facts below 0.3 importance are dropped. The top facts are injected into the system prompt for future conversations with that user.

Stored in `memory.db`, keyed by `guild_id:user_id`. Survives restarts.

### User distinction

Every message payload includes the sender's display name before reaching the model. The bot can tell users apart in a multi-user channel — responses stay contextually accurate even when several people are talking at once.

---

## Multiple AI Providers

Freesona routes generation through a provider abstraction so the same commands can target different backends without changing command code. Supported providers:

| Provider | Key env var |
| :--- | :--- |
| Gemini (default) | `GOOGLE_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Ollama | `OLLAMA_BASE_URL` |
| NVIDIA NIM | `NVIDIA_API_KEY` |
| Azure AI Foundry | `AZURE_AI_KEY`, `AZURE_AI_BASE_URL` |
| Groq | `GROQ_API_KEY` |
| OpenRouter | `OPENROUTER_API_KEY` |

Set `AI_PROVIDER` and `AI_PROVIDER_MODEL` in `.env`, then add the matching credentials. `/model set` and `/model reset` change the active model at runtime without a restart. Note: conversation continuity via `previous_interaction_id` is Gemini-specific — non-Gemini providers handle each generation as a stateless call.

---

## ChromaDB Knowledge Base

An optional ChromaDB-backed retrieval layer is available for semantic lookups during generation. When enabled, relevant documents from the local vector store are injected into the system prompt context alongside user facts and the active persona.

Configure with `CHROMA_COLLECTION` and `CHROMA_PERSIST_DIRECTORY` in `.env`. The retrieval path is fully optional — if ChromaDB is not installed or the collection is empty, generation continues normally.

Full write/manage commands (`/kbadd`, `/kblist`, `/kbdelete`) are planned as the next step on top of this foundation.

---

## Anniversary Tracking

`utils/anniversaries_db.py` provides a generic SQLite-backed anniversary entry system. Each entry stores a title, subtitle, anniversary date, optional thumbnail and reference URL, and an optional calendar event ID for external calendar sync.

The database supports per-guild user entries, duplicate detection, date-based lookups, and queries for entries missing calendar sync or thumbnails. The full user-facing cog that drives claiming and announcements is a separate private implementation built on top of this shared layer.

---

## Autonomous Mode

When enabled, the bot can join an active conversation unprompted. It uses a confidence-scored intent evaluator (`utils/intent.py`) rather than a random dice roll:

| Signal | Score |
| :--- | :--- |
| Direct mention or reply to bot | +0.90 |
| Attachment present | +0.50 |
| Code block present | +0.40 |
| Semantic trigger word (what, how, explain, fix…) | +0.40 |
| Ends with question mark | +0.20 |
| Channel has existing conversation memory | +0.10 |
| Short filler message (lol, ok, emoji-only) | −0.30 |
| Long monologue with no question and no mention | −0.20 |

Frequency thresholds: `low` = 0.70, `default` = 0.50, `high` = 0.35. A 120-second per-channel cooldown prevents it from dominating a conversation. A separate 60-second per-user cooldown prevents repeated autonomous responses to the same user.

---

## Debounced Responses

A per-user-per-channel debounce waits before generating a reply. Rapid successive messages from the same user in the same channel — "wait" / "actually" / "never mind" — collapse into one prompt before the bot responds.

---

## Multimodal Input

Attach an image, PDF, audio file, video, or code file to any AI command or conversation message. The bot reads the attachment alongside the text prompt via the active provider's multimodal pipeline. Supported types include PNG, JPEG, WEBP, GIF, PDF, plain text, Markdown, CSV, MP3, WAV, MP4, and more. Non-Gemini providers receive text-only input; attachments are silently ignored on providers that don't support multimodal input.

---

## Web Search

`~search <query>` fetches results using Gemini grounding first. If grounding is unavailable, it falls back to legacy Google Custom Search. Requires `GOOGLE_API_KEY`; `GOOGLE_SEARCH_API_KEY` and `SEARCH_ENGINE_ID` are optional for the fallback path.

---

## RSS News Feeds

`/rss latest <feed>` reads RSS/Atom feeds and posts the latest headlines. `/rss add`, `/rss remove`, and `/rss list` manage feed sources. Default feeds include BBC World, BBC Tech, NPR News, and Al Jazeera. Auto-posting polls every 5 minutes and sends new articles to the configured channel. Source logos are fetched via LogoKit if `LOGOKIT_TOKEN` is set.

---

## Audio Separation

`~separate` isolates vocals and instrumental from any audio using MVSEP's BS Roformer model (SDR vocals: 11.89, SDR instrum: 18.20). Accepts a file attachment, a direct audio URL, or any platform URL supported by yt-dlp. Output links are labeled as Vocals/Instrumental where MVSEP metadata allows it. Links are hosted by MVSEP and expire after some time. Free tier allows one job at a time. Webhook-based completion is supported when `MVSEP_WEBHOOK_URL` is configured; falls back to polling every 10 seconds otherwise. Requires `MVSEP_API_KEY`.

---

## Media Downloader

`~download <url>` downloads video at the best available resolution (1080p → 720p → 480p → compressed) and sends it directly in chat. `~audio <url>` extracts audio as MP3. Both use yt-dlp and ffmpeg. File size limit: 10 MB (Discord's free upload limit). Audio stream integrity is verified after every merge — silent merge failures that produce video-only files are caught and retried at a lower resolution. Per-user cooldown: 30 seconds.

---

## Warning System

`~warn <member> [reason]` issues a warning with a unique hex ID, DMs the member, and optionally triggers auto-threshold actions. Thresholds are configurable per server via `/warnthresholds` and support `timeout`, `kick`, and `ban` actions at specified warn counts. Warning history is stored in `warnings.db` per guild.

---

## Math

`~math <equation>` queries Wolfram\|Alpha — Short Answer API first, LLM API as fallback. Results are formatted with bolded headers and a LaTeX-rendered image where applicable.

---

## Injection Detection

Prompt injection attempts (`"ignore previous instructions"`, `"jailbreak"`, `"developer mode"`, etc.) are caught by `utils/security.py` before reaching the model. The prompt is neutralized rather than silently dropped, and the output is also checked for injection artifacts in model responses.

---

## Hybrid Commands

Every command works as both a prefix command (`~write`) and a slash command (`/write`). The prefix is configurable per server and persists across restarts via `config.json`.
