# utils/config.py: Config I/O and shared embed helpers.

import os
import json

CONFIG_PATH = os.getenv("CONFIG_FILE_PATH", "config.json")

DEFAULT_CONFIG = {
    "prefix": "~",
    "conversation_response_mode": "all",
    "provider": "gemini",
}

DEFAULT_MODEL_NAME = os.getenv("MODEL_NAME", "gemini-flash-lite-latest")
DEFAULT_PROVIDER_NAME = os.getenv("PROVIDER", "gemini")

LAST_DEBUG: dict[int, str] = {}


def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    config.update(data)
        except Exception:
            pass
    return config


def save_config(data: dict):
    os.makedirs(
        os.path.dirname(CONFIG_PATH) if os.path.dirname(CONFIG_PATH) else ".",
        exist_ok=True
    )
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


def get_model_name() -> str:
    model = load_config().get("model_name") or DEFAULT_MODEL_NAME
    return str(model).strip() or DEFAULT_MODEL_NAME


def get_provider_name() -> str:
    provider = load_config().get("provider") or DEFAULT_PROVIDER_NAME
    return str(provider).strip().lower() or DEFAULT_PROVIDER_NAME


def embed_footer(author_display: str, query: str, max_query_len: int = 80) -> str:
    """Returns a footer string: 'Asked by <name> • <truncated query>'"""
    truncated = query if len(query) <= max_query_len else query[:max_query_len - 1] + "…"
    return f"Asked by {author_display}  •  {truncated}"
