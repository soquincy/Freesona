# utils/

Logic modules for Freesona. This currently includes utilities for `cogs/genai.py` and `cogs/news.py`.

| Module | Responsibility |
| :--- | :--- |
| `generation.py` | Gemini API calls, response types, rate limiting, split messaging, multimodal attachment handling |
| `memory.py` | Short-term channel memory with summarization; long-term per-user fact storage and injection |
| `persona.py` | Persona data layer, modals, `/setpersona` command group |
| `intent.py` | Intent evaluator for autonomy — confidence scoring, signal detection, threshold mapping |
| `security.py` | Injection detection, output sanitization |
| `search.py` | Web search using Gemini grounding with optional legacy Google Custom Search fallback |
| `config.py` | Config I/O (`config.json`), embed footer helper |
| `rss.py` | RSS Feed parsing for feeds |
