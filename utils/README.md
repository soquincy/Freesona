# utils/

Logic modules for Freesona. Cogs in `cogs/` are wiring only — all substantive logic lives here.

| Module | Responsibility |
| :--- | :--- |
| `generation.py` | Core generation pipeline — provider dispatch, rate limiting, response splitting, multimodal attachment handling, ChromaDB context injection |
| `providers.py` | Provider abstraction — routes generation to Gemini, OpenAI, Ollama, NVIDIA NIM, Azure AI Foundry, Groq, or OpenRouter |
| `memory.py` | Long-term per-user fact storage and injection; per-channel Interactions API ID tracking for server-side conversation continuity |
| `anniversaries_db.py` | Generic SQLite-backed anniversary entry system — insert, query, update, delete, duplicate detection, calendar sync metadata |
| `chroma.py` | ChromaDB client singleton and `query_knowledge()` for semantic retrieval during generation |
| `persona.py` | Persona data layer, XML assembly, modals, `/setpersona` panel |
| `intent.py` | Intent evaluator for autonomy — confidence scoring, signal detection, threshold mapping |
| `security.py` | Prompt injection detection, output sanitization, public URL validation |
| `search.py` | Web search via Gemini grounding with optional legacy Google Custom Search fallback |
| `roles.py` | Message role classification (`model`, `user`, `bot`, `webhook`) |
| `config.py` | Config I/O (`config.json`), embed footer helper, provider/model name resolution |
| `modules.py` | Cog module registry and enable/disable state helpers |
| `rss.py` | RSS/Atom feed parsing, feed config persistence, seen-link deduplication |
