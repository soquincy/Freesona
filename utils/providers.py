import os
from typing import Any

import requests

from utils.config import get_model_name, get_provider_model as get_configured_provider_model, get_provider_name as get_configured_provider_name


DEFAULT_PROVIDER = os.getenv("AI_PROVIDER", "gemini")
OPENAI_COMPATIBLE_CONTENT_TYPE = "application/json"


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


def normalize_provider_name(provider: str | None) -> str:
    provider_name = (provider or get_provider_name()).strip().lower() or DEFAULT_PROVIDER
    aliases = {
        "nvidia": "nim",
        "nvidia-nim": "nim",
        "azure-foundry": "azure",
        "azure-ai-foundry": "azure",
        "azure-ai": "azure",
        "groqcloud": "groq",
        "open-router": "openrouter",
        "open_router": "openrouter",
    }
    return aliases.get(provider_name, provider_name)


def post_chat_completion(
    *,
    url: str,
    headers: dict[str, str],
    model: str,
    messages: list[dict[str, str]],
    max_output_tokens: int,
    token_field: str = "max_tokens",
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        token_field: max_output_tokens,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]


def generate_text(
    user_prompt: str,
    *,
    system_prompt: str = "",
    provider: str | None = None,
    model: str | None = None,
    max_output_tokens: int = 1024,
) -> str:
    provider_name = normalize_provider_name(provider)
    model_name = (model or get_provider_model() or get_model_name()).strip() or get_model_name()
    messages = build_messages(system_prompt, user_prompt)

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
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": OPENAI_COMPATIBLE_CONTENT_TYPE}
        return post_chat_completion(
            url=url,
            headers=headers,
            model=model_name or "gpt-4o-mini",
            messages=messages,
            max_output_tokens=max_output_tokens,
        )

    if provider_name == "ollama":
        url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/api/chat")
        payload = {
            "model": model_name or "llama3.1",
            "messages": messages,
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
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": OPENAI_COMPATIBLE_CONTENT_TYPE}
        return post_chat_completion(
            url=url,
            headers=headers,
            model=model_name or "meta/llama-3.1-8b-instruct",
            messages=messages,
            max_output_tokens=max_output_tokens,
        )

    if provider_name == "azure":
        api_key = os.getenv("AZURE_AI_KEY")
        if not api_key:
            raise RuntimeError("AZURE_AI_KEY missing.")
        url = os.getenv("AZURE_AI_BASE_URL")
        if not url:
            raise RuntimeError("AZURE_AI_BASE_URL missing — set it to your Azure AI Foundry endpoint.")
        headers = {"api-key": api_key, "Content-Type": OPENAI_COMPATIBLE_CONTENT_TYPE}
        return post_chat_completion(
            url=url,
            headers=headers,
            model=model_name or "gpt-4o-mini",
            messages=messages,
            max_output_tokens=max_output_tokens,
        )

    if provider_name == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY missing.")
        url = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": OPENAI_COMPATIBLE_CONTENT_TYPE}
        return post_chat_completion(
            url=url,
            headers=headers,
            model=model_name or "llama-3.3-70b-versatile",
            messages=messages,
            max_output_tokens=max_output_tokens,
            token_field="max_completion_tokens",
        )

    if provider_name == "openrouter":
        api_key = os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY missing.")
        url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": OPENAI_COMPATIBLE_CONTENT_TYPE}
        site_url = os.getenv("OPENROUTER_SITE_URL")
        site_name = os.getenv("OPENROUTER_SITE_NAME")
        if site_url:
            headers["HTTP-Referer"] = site_url
        if site_name:
            headers["X-Title"] = site_name
        return post_chat_completion(
            url=url,
            headers=headers,
            model=model_name or "meta-llama/llama-3.3-70b-instruct:free",
            messages=messages,
            max_output_tokens=max_output_tokens,
            token_field="max_completion_tokens",
        )

    raise RuntimeError(f"Unsupported provider '{provider_name}'.")
