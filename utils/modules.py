# utils/modules.py: Cog module registry and config helpers.

from __future__ import annotations

CORE_EXTENSIONS = [
    "cogs.help",
    "cogs.ping",
    "cogs.status",
    "cogs.admin",
]

OPTIONAL_MODULES = {
    "hello": "cogs.hello",
    "moderation": "cogs.utils",
    "genai": "cogs.genai",
    "wolfram": "cogs.wolfram",
    "news": "cogs.news",
    "ytdlp": "cogs.ytdlp",
    "mvsep": "cogs.mvsep",
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
