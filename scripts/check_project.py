#!/usr/bin/env python3
"""Project checks that can run before pushing without editor tooling."""

from __future__ import annotations

import ast
import importlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from types import ModuleType
from urllib.parse import urlparse


ROOT = pathlib.Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "__pycache__", "venv", ".venv"}


class CheckFailure(Exception):
    pass


def iter_python_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for path in ROOT.rglob("*.py"):
        if SKIP_DIRS.intersection(path.relative_to(ROOT).parts):
            continue
        files.append(path)
    return sorted(files)


def check_python_syntax() -> None:
    errors: list[str] = []
    for path in iter_python_files():
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            rel = path.relative_to(ROOT)
            errors.append(f"{rel}:{exc.lineno}:{exc.offset}: {exc.msg}")

    if errors:
        raise CheckFailure("Python syntax errors:\n" + "\n".join(errors))


def reload_local_module(name: str) -> ModuleType:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if name in sys.modules:
        del sys.modules[name]
    return importlib.import_module(name)


def check_config_round_trip() -> None:
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    old_path = os.environ.get("CONFIG_FILE_PATH")

    try:
        os.environ["CONFIG_FILE_PATH"] = path
        config = reload_local_module("utils.config")
        config.save_config({
            "prefix": "!",
            "chat_channel_id": 123,
            "autonomy": True,
            "model_name": "test-model",
        })
        loaded = config.load_config()
        model_name = config.get_model_name()
    finally:
        if old_path is None:
            os.environ.pop("CONFIG_FILE_PATH", None)
        else:
            os.environ["CONFIG_FILE_PATH"] = old_path
        pathlib.Path(path).unlink(missing_ok=True)
        sys.modules.pop("utils.config", None)

    assert loaded["prefix"] == "!"
    assert loaded["chat_channel_id"] == 123
    assert loaded["autonomy"] is True
    assert model_name == "test-model"


def check_public_url_guard() -> None:
    security = reload_local_module("utils.security")
    assert security.is_public_http_url("https://example.com/watch?v=1")
    assert security.is_public_http_url("http://example.com/file.mp3")
    assert not security.is_public_http_url("ftp://example.com/file.mp3")
    assert not security.is_public_http_url("http://localhost:8000")
    assert not security.is_public_http_url("http://127.0.0.1:8000")
    assert not security.is_public_http_url("http://10.0.0.1/file.mp3")
    assert not security.is_public_http_url("http://169.254.1.1/file.mp3")


def load_mvsep_helpers() -> dict:
    source = (ROOT / "cogs" / "mvsep.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    keep: list[ast.stmt] = []

    for node in module.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if names & {"DIRECT_AUDIO_EXTS", "YTDLP_DOMAINS"}:
                keep.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {
            "is_direct_audio_url",
            "should_download_with_ytdlp",
            "stem_label",
        }:
            keep.append(node)

    namespace = {"urlparse": urlparse}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "cogs/mvsep.py", "exec"), namespace)
    return namespace


def check_mvsep_url_routing() -> None:
    helpers = load_mvsep_helpers()
    should_ytdlp = helpers["should_download_with_ytdlp"]
    is_direct_audio = helpers["is_direct_audio_url"]

    assert should_ytdlp("https://www.youtube.com/watch?v=abc")
    assert should_ytdlp("https://m.tiktok.com/v/123")
    assert should_ytdlp("https://x.com/user/status/1")
    assert should_ytdlp("https://soundcloud.com/user/track")
    assert is_direct_audio("https://cdn.example.com/file.mp3?token=1")
    assert not should_ytdlp("https://cdn.example.com/file.mp3")
    assert helpers["stem_label"]({"name": "stem"}, 0) == "Vocals"
    assert helpers["stem_label"]({"name": "stem"}, 1) == "Instrumental"
    assert helpers["stem_label"]({"name": "vocals.mp3"}, 1) == "Vocals"


def check_module_registry() -> None:
    modules = reload_local_module("utils.modules")
    enabled = modules.load_enabled_modules({
        "enabled_modules": {
            "genai": False,
            "mvsep": True,
            "unknown": False,
        }
    })
    assert enabled["genai"] is False
    assert enabled["mvsep"] is True
    assert "unknown" not in enabled
    assert modules.module_extension("GENAI") == "cogs.genai"
    assert modules.module_extension("news") == "cogs.news"
    assert modules.module_extension("missing") is None


def check_rss_parser() -> None:
    rss = reload_local_module("utils.rss")
    sample = """<?xml version="1.0"?><rss><channel><item><title>One</title><link>https://example.com/1</link><pubDate>Sun, 24 May 2026 01:00:00 GMT</pubDate><description>Hello &amp;amp; hi</description></item></channel></rss>"""
    items = rss.parse_feed(sample)
    assert len(items) == 1
    assert items[0].title == "One"
    assert items[0].link == "https://example.com/1"
    assert "Hello" in items[0].summary


def check_json_files() -> None:
    for rel in ("config.json",):
        path = ROOT / rel
        if not path.exists():
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise CheckFailure(f"{rel} is invalid JSON: line {exc.lineno}, column {exc.colno}")


def check_env_sample() -> None:
    sample = ROOT / ".env.sample"
    if not sample.exists():
        raise CheckFailure(".env.sample is missing")

    keys = set()
    for line in sample.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        keys.add(line.split("=", 1)[0])

    required = {
        "BOT_TOKEN",
        "CHANNEL_ID",
        "GOOGLE_API_KEY",
        "MODEL_NAME",
        "CONFIG_FILE_PATH",
        "MEMORY_FILE_PATH",
    }
    missing = sorted(required - keys)
    if missing:
        raise CheckFailure(".env.sample is missing keys: " + ", ".join(missing))


def check_secret_files_not_tracked() -> None:
    try:
        result = subprocess.run(
            [
                "git", "ls-files",
                ".env",
                "persona.txt", "persona.json", "personas.json",
                "memory.json", "kb.json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return

    tracked = [line for line in result.stdout.splitlines() if line.strip()]
    if tracked:
        raise CheckFailure("Secret/runtime files are tracked: " + ", ".join(tracked))


def run_check(name: str, func) -> None:
    print(f"[check] {name}...", end=" ", flush=True)
    func()
    print("ok")


def main() -> int:
    checks = [
        ("python syntax", check_python_syntax),
        ("config round trip", check_config_round_trip),
        ("public URL guard", check_public_url_guard),
        ("MVSEP URL routing", check_mvsep_url_routing),
        ("module registry", check_module_registry),
        ("RSS parser", check_rss_parser),
        ("JSON files", check_json_files),
        (".env.sample", check_env_sample),
        ("tracked secrets", check_secret_files_not_tracked),
    ]

    try:
        for name, func in checks:
            run_check(name, func)
    except (AssertionError, CheckFailure) as exc:
        print("failed")
        print(f"\nERROR: {exc}")
        return 1

    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
