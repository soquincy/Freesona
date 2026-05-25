# utils/search.py: Web search via Gemini grounding tool (primary) with
# Google Custom Search as legacy fallback if configured.

import asyncio
import logging
import os
from dataclasses import dataclass, field

import aiohttp
from google import genai
from google.genai import types

logger = logging.getLogger("FreesonaBot")

# ---------------------------------------------------------------------------
# Legacy fallback — Google Custom Search (existing engine only, deprecated 2027)
# ---------------------------------------------------------------------------

GOOGLE_SEARCH_API_KEY = os.getenv("GOOGLE_SEARCH_API_KEY")
SEARCH_ENGINE_ID      = os.getenv("SEARCH_ENGINE_ID")

# ---------------------------------------------------------------------------
# Gemini grounding client (reuses the same API key as generation.py)
# ---------------------------------------------------------------------------

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
SEARCH_MODEL   = "gemini-flash-lite-latest"
# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    text:    str
    sources: list[dict] = field(default_factory=list)  # [{"title": ..., "uri": ...}]

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

# ---------------------------------------------------------------------------
# Primary: Gemini grounding
# ---------------------------------------------------------------------------

async def _gemini_grounded_search(query: str) -> SearchResult:
    if not GOOGLE_API_KEY:
        raise EnvironmentError("GOOGLE_API_KEY not set.")

    client = genai.Client(api_key=GOOGLE_API_KEY)

    grounding_tool = types.Tool(google_search=types.GoogleSearch())
    config = types.GenerateContentConfig(
        tools=[grounding_tool],
        max_output_tokens=1024,
    )

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=SEARCH_MODEL,
        contents=query,
        config=config,
    )

    text = response.text or ""

    # Extract sources from groundingMetadata (defensive: attributes may be None)
    sources: list[dict] = []
    try:
        candidates = getattr(response, "candidates", None) or []
        if not candidates:
            chunks = None
        else:
            candidate0 = candidates[0]
            grounding_metadata = getattr(candidate0, "grounding_metadata", None)
            chunks = getattr(grounding_metadata, "grounding_chunks", None)

        for chunk in (chunks or []):
            web = getattr(chunk, "web", None)
            if web:
                sources.append({
                    "title": getattr(web, "title", ""),
                    "uri":   getattr(web, "uri",   ""),
                })
    except Exception:
        # grounding metadata unavailable — still return the text
        sources = []

    return SearchResult(text=text, sources=sources)

# ---------------------------------------------------------------------------
# Legacy fallback: Google Custom Search (returns plain text summary only)
# ---------------------------------------------------------------------------

async def _legacy_custom_search(query: str) -> SearchResult:
    if not GOOGLE_SEARCH_API_KEY or not SEARCH_ENGINE_ID:
        return SearchResult(text="Search not configured.")
    url    = "https://www.googleapis.com/customsearch/v1"
    params = {"key": GOOGLE_SEARCH_API_KEY, "cx": SEARCH_ENGINE_ID, "q": query, "num": 5}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()
        items = data.get("items", [])
        if not items:
            return SearchResult(text="No results found.")
        lines = [f"- {i['title']} ({i['link']})" for i in items]
        return SearchResult(
            text="\n".join(lines),
            sources=[{"title": i["title"], "uri": i["link"]} for i in items],
        )
    except Exception as e:
        logger.error(f"Legacy search error: {e}")
        return SearchResult(text="Search failed.")

# ---------------------------------------------------------------------------
# Public interface — tries Gemini grounding first, falls back to legacy
# ---------------------------------------------------------------------------

async def web_search(query: str) -> SearchResult:
    """
    Returns a SearchResult with .text (AI-synthesized answer) and
    .sources (list of {"title", "uri"} dicts).

    Primary:  Gemini grounding tool (real-time, cited, no extra API key)
    Fallback: Google Custom Search (legacy, existing engine only)
    """
    try:
        result = await _gemini_grounded_search(query)
        if result.text.strip():
            logger.info(f"Search via Gemini grounding ({len(result.sources)} sources)")
            return result
    except Exception as e:
        logger.warning(f"Gemini grounding failed, falling back to legacy: {e}")

    logger.info("Search via legacy Google Custom Search")
    return await _legacy_custom_search(query)