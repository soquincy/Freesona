# utils/

Logic modules for Freesona. The cog (`cogs/genai.py`) handles Discord events and commands only — all AI logic, memory, persona management, and config live here.

| Module | Responsibility |
| :--- | :--- |
| `generation.py` | Gemini API calls, response types, rate limiting, split messaging, multimodal attachment handling |
| `memory.py` | Short-term channel memory with summarization; long-term per-user fact storage and injection |
| `persona.py` | Persona data layer, modals, `/setpersona` command group |
| `intent.py` | Intent evaluator for autonomy — confidence scoring, signal detection, threshold mapping |
| `security.py` | Injection detection, output sanitization |
| `search.py` | Google Custom Search integration |
| `config.py` | Config I/O (`config.json`), embed footer helper |
