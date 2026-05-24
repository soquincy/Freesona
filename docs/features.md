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

Changes take effect immediately. The assembled persona is injected as the Gemini system instruction on every generation call.

**Persona profiles** — save, load, list, and delete named presets with `/personasave`, `/personaload`, `/personalist`, `/personadelete`. Useful for switching between characters or server contexts.

**Persona lock** — `/personalock` prevents accidental overwrites. `/personaunlock` to re-enable editing.

**Legacy support** — if a `persona.txt` file exists and no `persona.json` is found, the bot falls back to it automatically. Existing installs don't break on upgrade.

**Debug** — `/debugpersona` shows the fully assembled persona, last prompt sent to the model, model name, lock state, and autonomy status.

---

## Memory

### Short-term (per channel, in-session)

The bot keeps a rolling window of the last 5 messages per channel. Older history is automatically summarized and injected as context, keeping the bot coherent across long exchanges without blowing up the context window. Cleared on restart or via `/clearmemory`.

### Long-term (per user, per guild, persisted)

After each user message, the bot runs a background fact extraction pass — asking Gemini whether the message reveals anything worth remembering (name, job, location, interests, projects, relationships). Facts are scored by importance (0.0–1.0), deduplicated by message ID, and capped at 20 per user. Facts below 0.3 importance are dropped. The top facts are injected into the system prompt for future conversations with that user.

Stored in `memory.json`, keyed by `guild_id:user_id`. Survives restarts.

### User distinction

Every message stored in short-term memory is prefixed with the sender's display name (`Username: <message>`). This means Gemini sees attributed turns and can tell users apart in a multi-user channel — responses stay contextually accurate even when several people are talking at once.

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
| Channel has existing memory | +0.10 |
| Short filler message (lol, ok, emoji-only) | −0.30 |
| Long monologue with no question and no mention | −0.20 |

Frequency thresholds: `low` = 0.70, `default` = 0.50, `high` = 0.35. A 120-second per-channel cooldown prevents it from dominating a conversation.

---

## Debounced Responses

A per-user debounce waits before generating a reply. Rapid successive messages from the same user — "wait" / "actually" / "never mind" — collapse into one prompt before the bot responds.

---

## Multimodal Input

Attach an image, PDF, audio file, video, or code file to any AI command or conversation message. The bot reads the attachment alongside the text prompt via Gemini's multimodal pipeline. Supported types include PNG, JPEG, WEBP, GIF, PDF, plain text, Markdown, CSV, MP3, WAV, MP4, and more.

---

## Web Search

`~search <query>` fetches live results via Google Custom Search and summarizes them using the active persona. Requires `GOOGLE_SEARCH_API_KEY` and `SEARCH_ENGINE_ID`.

---

## RSS News Feeds

`/rss latest <feed>` reads RSS/Atom feeds and posts the latest headlines. `/rss add`, `/rss remove`, and `/rss list` manage feed sources. Public wire-service RSS availability varies: AFPBB has a public RSS feed for limited personal/non-commercial use, Reuters public RSS has been discontinued, and Reuters/AP wire RSS generally requires client feeds or custom feed URLs.

---

## Audio Separation

`~separate` isolates vocals and instrumental from any audio using MVSEP's BS Roformer model (SDR vocals: 11.89, SDR instrum: 18.20). Accepts a file attachment, a direct audio URL, or any platform URL supported by yt-dlp. Output links are labeled as vocals/instrumental where MVSEP metadata allows it, with a two-stem fallback. Links are hosted by MVSEP and expire after some time. Free tier allows one job at a time. Requires `MVSEP_API_KEY`.

---

## Media Downloader

`~download <url>` downloads video at the best available resolution (1080p → 720p → 480p → compressed) and sends it directly in chat. `~audio <url>` extracts audio as MP3. Both use yt-dlp and ffmpeg. File size limit: 10 MB (Discord's free upload limit). Audio stream integrity is verified after every merge — silent merge failures that produce video-only files are caught and retried at a lower resolution.

---

## Math

`~math <equation>` queries Wolfram\|Alpha — Short Answer API first, LLM API as fallback. Results are formatted with bolded headers and a LaTeX-rendered image where applicable.

---

## Injection Detection

Prompt injection attempts (`"ignore previous instructions"`, `"jailbreak"`, `"developer mode"`, etc.) are caught by `utils/security.py` before reaching the model. The prompt is neutralized rather than silently dropped, and the output is also checked for injection artifacts in model responses.

---

## Hybrid Commands

Every command works as both a prefix command (`~write`) and a slash command (`/write`). The prefix is configurable per server and persists across restarts via `config.json`.
