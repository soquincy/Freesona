# utils/search.py: Web search via Gemini grounding tool.
# CSE (Google Custom Search) has been removed — it is being discontinued

import asyncio
import logging
import os
from dataclasses import dataclass, field

from google import genai
from google.genai import types

logger = logging.getLogger("FreesonaBot")

# ---------------------------------------------------------------------------
# Gemini grounding client config
# ---------------------------------------------------------------------------

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

PRIMARY_MODEL   = "gemini-2.5-flash-lite"
SECONDARY_MODEL = "gemini-flash-lite-latest"

MAX_RETRIES_PER_MODEL = 2          # retries within a single model before moving on
RETRY_BASE_DELAY_SEC  = 1.5        # backoff base; attempt N waits N * base seconds

TRANSIENT_MARKERS = ("503", "UNAVAILABLE", "OVERLOADED", "RESOURCE_EXHAUSTED")

# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    text:    str = ""
    sources: list[dict] = field(default_factory=list)  # [{"title": ..., "uri": ...}]
    failed:  bool = False
    model_used: str | None = None

    @property
    def has_sources(self) -> bool:
        return bool(self.sources)

    def sources_block(self, max: int = 5) -> str:
        lines = []
        for i, s in enumerate(self.sources[:max], 1):
            title = s.get("title", "Source")
            uri   = s.get("uri", "")
            lines.append(f"{i}. [{title}]({uri})" if uri else f"{i}. {title}")
        return "\n".join(lines)


def _is_transient(exc: Exception) -> bool:
    msg = str(exc)
    return any(marker in msg for marker in TRANSIENT_MARKERS)


# ---------------------------------------------------------------------------
# Single grounded call against a given model, with retry/backoff
# ---------------------------------------------------------------------------

async def _grounded_call(query: str, model: str, max_retries: int) -> SearchResult:
    client = genai.Client(api_key=GOOGLE_API_KEY)
    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(
        tools=[grounding_tool],
        max_output_tokens=1024,
    )

    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=query,
                config=config,
            )
            text = response.text or ""

            sources: list[dict] = []
            try:
                candidates = getattr(response, "candidates", None) or []
                chunks = None
                if candidates:
                    grounding_metadata = getattr(candidates[0], "grounding_metadata", None)
                    chunks = getattr(grounding_metadata, "grounding_chunks", None)
                for chunk in (chunks or []):
                    web = getattr(chunk, "web", None)
                    if web:
                        sources.append({
                            "title": getattr(web, "title", ""),
                            "uri":   getattr(web, "uri", ""),
                        })
            except Exception:
                sources = []

            if not text.strip():
                # Empty response isn't necessarily transient, but it's not
                # usable either — treat as a failed attempt and let the
                # caller decide whether to escalate to the next model.
                raise ValueError(f"Empty response text from model {model}")

            return SearchResult(text=text, sources=sources, model_used=model)

        except Exception as e:
            last_exc = e
            if _is_transient(e) and attempt < max_retries:
                delay = RETRY_BASE_DELAY_SEC * (attempt + 1)
                logger.warning(
                    f"[{model}] transient search error (attempt {attempt + 1}/"
                    f"{max_retries + 1}), retrying in {delay:.1f}s: {e}"
                )
                await asyncio.sleep(delay)
                continue
            # Non-transient, or out of retries — stop trying this model.
            logger.warning(f"[{model}] search attempt failed: {e}")
            break

    raise last_exc if last_exc else RuntimeError(f"Unknown failure for model {model}")


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def web_search(query: str) -> SearchResult:
    """
    Returns a SearchResult with .text (AI-synthesized, grounded answer) and
    .sources (list of {"title", "uri"} dicts).

    Tries PRIMARY_MODEL with retries, then escalates to SECONDARY_MODEL
    with retries. If both fail, returns a SearchResult with failed=True
    and empty text/sources — callers MUST check .failed before using
    .text as context for any downstream generation call.
    """
    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY not set — search unavailable.")
        return SearchResult(failed=True)

    for model in (PRIMARY_MODEL, SECONDARY_MODEL):
        try:
            result = await _grounded_call(query, model, MAX_RETRIES_PER_MODEL)
            logger.info(
                f"Search succeeded via {model} ({len(result.sources)} sources)"
            )
            return result
        except Exception as e:
            logger.warning(f"Model {model} exhausted retries, escalating: {e}")
            continue

    logger.error(f"All grounding models failed for query: {query!r}")
    return SearchResult(failed=True)