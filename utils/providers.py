import os
from typing import Any

import requests

from utils.config import get_model_name, get_provider_model as get_configured_provider_model, get_provider_name as get_configured_provider_name


DEFAULT_PROVIDER = os.getenv("AI_PROVIDER", "gemini")


def get_provider_name() -> str:
    return get_configured_provider_name()


def get_provider_model() -> str:
    return get_configured_provider_model()


def build_messages(system_prompt: str, user_prompt: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def get_provider_config() -> dict[str, Any]:
    return {
        "provider": get_provider_name(),
        "model": get_provider_model() or get_model_name(),
    }


def generate_text(
    user_prompt: str,
    *,
    system_prompt: str = "",
    provider: str | None = None,
    model: str | None = None,
    max_output_tokens: int = 1024,
) -> str:
    provider_name = (provider or get_provider_name()).strip().lower() or DEFAULT_PROVIDER
    if provider_name in {"nim", "nvidia", "nvidia-nim"}:
        provider_name = "nim"
    if provider_name in {"github", "github-models"}:
        provider_name = "github"
    model_name = (model or get_provider_model() or get_model_name()).strip() or get_model_name()

    if provider_name == "gemini":
        from google import genai

        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GOOGLE_API_KEY missing.")
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config={"system_instruction": system_prompt or "You are a helpful assistant.", "max_output_tokens": max_output_tokens},
        )
        return getattr(response, "text", "") or ""

    if provider_name == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY missing.")
        url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
        payload = {
            "model": model_name or "gpt-4o-mini",
            "messages": build_messages(system_prompt, user_prompt),
            "max_tokens": max_output_tokens,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    if provider_name == "ollama":
        url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/api/chat")
        payload = {
            "model": model_name or "llama3.1",
            "messages": build_messages(system_prompt, user_prompt),
            "stream": False,
        }
        response = requests.post(url, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "")

    if provider_name == "nim":
        api_key = os.getenv("NVIDIA_API_KEY") or os.getenv("NIM_API_KEY")
        if not api_key:
            raise RuntimeError("NVIDIA_API_KEY or NIM_API_KEY missing.")
        url = os.getenv("NVIDIA_NIM_BASE_URL") or os.getenv("NIM_BASE_URL") or "https://integrate.api.nvidia.com/v1/chat/completions"
        payload = {
            "model": model_name or "meta/llama-3.1-8b-instruct",
            "messages": build_messages(system_prompt, user_prompt),
            "max_tokens": max_output_tokens,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    if provider_name == "github":
        api_key = os.getenv("GITHUB_TOKEN")
        if not api_key:
            raise RuntimeError("GITHUB_TOKEN missing.")
        url = os.getenv("GITHUB_MODELS_BASE_URL", "https://models.inference.ai.azure.com/chat/completions")
        payload = {
            "model": model_name or "gpt-4o-mini",
            "messages": build_messages(system_prompt, user_prompt),
            "max_tokens": max_output_tokens,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    raise RuntimeError(f"Unsupported provider '{provider_name}'.")
