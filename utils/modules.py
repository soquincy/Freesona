# utils/modules.py: Cog module registry and config helpers.

from __future__ import annotations

CORE_EXTENSIONS = [
    "cogs.system.help",
    "cogs.tools.ping",
    "cogs.system.status",
    "cogs.system.admin",
]

OPTIONAL_MODULES = {
    "hello":      "cogs.fun.hello",
    "random":     "cogs.fun.random",
    "moderation": "cogs.moderation.core",
    "genai":      "cogs.ai.genai",
    "wolfram":    "cogs.tools.wolfram",
    "news":       "cogs.system.news",
    "ytdlp":      "cogs.media.ytdlp",
    "mvsep":      "cogs.media.mvsep",
    "warns":      "cogs.moderation.warns",
}

DEFAULT_ENABLED_MODULES = {name: True for name in OPTIONAL_MODULES}


def normalized_module_name(name: str) -> str:
    return name.lower().strip()


def module_extension(name: str) -> str | None:
    return OPTIONAL_MODULES.get(normalized_module_name(name))


def load_enabled_modules(config: dict) -> dict[str, bool]:
    enabled = DEFAULT_ENABLED_MODULES.copy()
    saved = config.get("enabled_modules", {})
    if isinstance(saved, dict):
        for name, value in saved.items():
            key = normalized_module_name(str(name))
            if key in enabled:
                enabled[key] = bool(value)
    return enabled


def save_module_state(config: dict, name: str, enabled: bool) -> None:
    key = normalized_module_name(name)
    states = config.setdefault("enabled_modules", {})
    states[key] = enabled
