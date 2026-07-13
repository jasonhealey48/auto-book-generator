"""
Fetch free model catalogs from each provider.

Returns lists of model ids (and friendly names when available) that the user
can pick from the GUI dropdown.

Providers:
- Pollinations: small hardcoded list (free, keyless)
- OpenRouter: hits /api/v1/models and filters free tier
- NVIDIA NIM: hits /v1/models (needs API key)
- HuggingFace: curated free chat models
- Google Gemini: free tier models via listing API
- Groq: free tier models via listing API
"""

import json
import time
import urllib.parse
import requests
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ModelInfo:
    id: str
    label: str = ""
    note: str = ""

    def display(self) -> str:
        if self.note:
            return f"{self.label} — {self.note}"
        return self.label or self.id


def _http_get(url: str, headers=None, timeout: int = 30):
    r = requests.get(url, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Pollinations (free, keyless)
# ---------------------------------------------------------------------------

POLLINATIONS_FREE = [
    ModelInfo("openai-fast", "openai-fast", "default, fast"),
    ModelInfo("openai", "openai", "slower, sometimes more capable"),
]


def fetch_pollinations_models(api_key: str = "") -> List[ModelInfo]:
    return list(POLLINATIONS_FREE)


# ---------------------------------------------------------------------------
# OpenRouter (free tier :free models)
# ---------------------------------------------------------------------------

def fetch_openrouter_models(api_key: str = "") -> List[ModelInfo]:
    """OpenRouter lists its models. Free models end in ':free'."""
    url = "https://openrouter.ai/api/v1/models"
    try:
        data = _http_get(url, timeout=30)
    except Exception:
        return []
    models = []
    for m in data.get("data", []):
        mid = m.get("id", "")
        if not mid:
            continue
        is_free = ":free" in mid
        if not is_free:
            continue
        label = m.get("name", mid)
        ctx = m.get("context_length") or 0
        note = f"{ctx // 1000}k ctx" if ctx else ""
        models.append(ModelInfo(id=mid, label=label, note=note))
    models.sort(key=lambda m: m.id)
    return models


OPENROUTER_FREE_FALLBACK = [
    ModelInfo("meta-llama/llama-3.1-8b-instruct:free", "Llama 3.1 8B (free)", "recommended"),
    ModelInfo("mistralai/mistral-7b-instruct:free", "Mistral 7B (free)", ""),
    ModelInfo("qwen/qwen-2-7b-instruct:free", "Qwen 2 7B (free)", ""),
    ModelInfo("google/gemma-2-9b-it:free", "Gemma 2 9B IT (free)", ""),
    ModelInfo("meta-llama/llama-3.2-3b-instruct:free", "Llama 3.2 3B (free)", "small + fast"),
    ModelInfo("deepseek/deepseek-r1:free", "DeepSeek R1 (free)", "reasoning"),
    ModelInfo("anthracite/gemma-2-27b-it:free", "Gemma 2 27B IT (free)", "large"),
    ModelInfo("huggingfaceh4/zephyr-7b-beta:free", "Zephyr 7B (free)", ""),
]


# ---------------------------------------------------------------------------
# NVIDIA NIM (needs API key — free preview tier)
# ---------------------------------------------------------------------------

NVIDIA_FREE_FALLBACK = [
    ModelInfo("meta/llama-3.1-8b-instruct", "Llama 3.1 8B (fast)", "recommended default"),
    ModelInfo("meta/llama-3.2-3b-instruct", "Llama 3.2 3B (very fast)", "smallest chat"),
    ModelInfo("google/gemma-2-2b-it", "Gemma 2 2B IT", "extremely fast"),
    ModelInfo("nvidia/llama-3.1-nemotron-nano-8b-v1", "Nemotron Nano 8B", ""),
    ModelInfo("nvidia/nemotron-mini-4b-instruct", "Nemotron Mini 4B", "fastest"),
    ModelInfo("mistralai/mistral-7b-instruct-v0.3", "Mistral 7B Instruct v0.3", ""),
    ModelInfo("meta/llama-3.3-70b-instruct", "Llama 3.3 70B", "high quality (slow)"),
]


def fetch_nvidia_models(api_key: str = "") -> List[ModelInfo]:
    """NVIDIA's integrate API exposes /v1/models. Filter for free tier by name heuristic."""
    if not api_key:
        return list(NVIDIA_FREE_FALLBACK)
    url = "https://integrate.api.nvidia.com/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        data = _http_get(url, headers=headers, timeout=30)
    except Exception:
        return list(NVIDIA_FREE_FALLBACK)
    models = []
    for m in data.get("data", []):
        mid = m.get("id", "")
        if not mid:
            continue
        models.append(ModelInfo(id=mid, label=mid))
    models.sort(key=lambda m: m.id)
    if not models:
        return list(NVIDIA_FREE_FALLBACK)
    return models


# ---------------------------------------------------------------------------
# HuggingFace (curated free chat models — no listing API)
# ---------------------------------------------------------------------------

HF_FREE_CHAT = [
    ModelInfo("meta-llama/Meta-Llama-3-8B-Instruct",
              "Llama 3 8B Instruct", "popular, chat-tuned"),
    ModelInfo("mistralai/Mistral-7B-Instruct-v0.3",
              "Mistral 7B Instruct v0.3", "fast"),
    ModelInfo("google/gemma-1.1-7b-it",
              "Gemma 1.1 7B IT", "Google chat-tuned"),
    ModelInfo("microsoft/Phi-3-mini-4k-instruct",
              "Phi-3 Mini 4K", "compact"),
    ModelInfo("HuggingFaceH4/zephyr-7b-beta",
              "Zephyr 7B", "open chat"),
    ModelInfo("NousResearch/Nous-Hermes-2-Mistral-7B-DPO",
              "Hermes 2 Mistral 7B DPO", "chat-tuned"),
]


def fetch_huggingface_models(api_key: str = "") -> List[ModelInfo]:
    return list(HF_FREE_CHAT)


# ---------------------------------------------------------------------------
# Google Gemini (free tier)
# ---------------------------------------------------------------------------

GOOGLE_FREE_MODELS = [
    ModelInfo("gemini-2.0-flash", "Gemini 2.0 Flash", "recommended, free tier"),
    ModelInfo("gemini-2.0-flash-lite", "Gemini 2.0 Flash Lite", "fastest, free tier"),
    ModelInfo("gemini-1.5-flash", "Gemini 1.5 Flash", "free tier"),
    ModelInfo("gemini-1.5-flash-8b", "Gemini 1.5 Flash 8B", "smaller, faster"),
    ModelInfo("gemini-2.5-flash-preview-04-17", "Gemini 2.5 Flash Preview", "preview, free"),
]


def fetch_google_models(api_key: str = "") -> List[ModelInfo]:
    """Google Gemini API listing. Falls back to curated free list."""
    if not api_key:
        return list(GOOGLE_FREE_MODELS)
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    headers = {"x-goog-api-key": api_key}
    try:
        data = _http_get(url, headers=headers, timeout=30)
    except Exception:
        return list(GOOGLE_FREE_MODELS)
    models = []
    for m in data.get("models", []):
        mid = m.get("name", "").replace("models/", "")
        if not mid:
            continue
        display = m.get("displayName", mid)
        desc = m.get("description", "")
        note = ""
        if "free" in desc.lower() or "free" in mid.lower():
            note = "free tier"
        models.append(ModelInfo(id=mid, label=display, note=note))
    models.sort(key=lambda m: m.id)
    if not models:
        return list(GOOGLE_FREE_MODELS)
    return models


# ---------------------------------------------------------------------------
# Groq (free tier — very fast inference)
# ---------------------------------------------------------------------------

GROQ_FREE_MODELS = [
    ModelInfo("llama-3.1-8b-instant", "Llama 3.1 8B Instant", "recommended, fast"),
    ModelInfo("llama3-8b-8192", "Llama 3 8B", "8k context"),
    ModelInfo("gemma2-9b-it", "Gemma 2 9B IT", "Google chat model"),
    ModelInfo("llama-3.2-1b-preview", "Llama 3.2 1B Preview", "tiny, fastest"),
    ModelInfo("llama-3.2-3b-preview", "Llama 3.2 3B Preview", "small, fast"),
    ModelInfo("llama-3.2-11b-vision-preview", "Llama 3.2 11B Vision", "multimodal"),
    ModelInfo("llama-3.2-90b-vision-preview", "Llama 3.2 90B Vision", "large, multimodal"),
]


def fetch_groq_models(api_key: str = "") -> List[ModelInfo]:
    """Groq API listing. Falls back to curated free list."""
    if not api_key:
        return list(GROQ_FREE_MODELS)
    url = "https://api.groq.com/openai/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        data = _http_get(url, headers=headers, timeout=30)
    except Exception:
        return list(GROQ_FREE_MODELS)
    models = []
    for m in data.get("data", []):
        mid = m.get("id", "")
        if not mid:
            continue
        display = m.get("owned_by", "") or mid
        models.append(ModelInfo(id=mid, label=mid, note=display))
    models.sort(key=lambda m: m.id)
    if not models:
        return list(GROQ_FREE_MODELS)
    return models


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

FETCHERS = {
    "Pollinations": fetch_pollinations_models,
    "OpenRouter": fetch_openrouter_models,
    "NVIDIA": fetch_nvidia_models,
    "HuggingFace": fetch_huggingface_models,
    "Google": fetch_google_models,
    "Groq": fetch_groq_models,
}


def fetch_for(provider_name: str, api_key: str = "") -> List[ModelInfo]:
    """Fetch model list for a provider, always returning a fallback list if live fetch fails."""
    fetcher = FETCHERS.get(provider_name)
    if not fetcher:
        return list(POLLINATIONS_FREE)

    fallback_map = {
        "Pollinations": POLLINATIONS_FREE,
        "OpenRouter": OPENROUTER_FREE_FALLBACK,
        "NVIDIA": NVIDIA_FREE_FALLBACK,
        "HuggingFace": HF_FREE_CHAT,
        "Google": GOOGLE_FREE_MODELS,
        "Groq": GROQ_FREE_MODELS,
    }
    fallback = fallback_map.get(provider_name, [])

    fetched = fetcher(api_key)
    if not fetched:
        return fallback

    seen = set()
    out = []
    for m in fetched + fallback:
        if m.id in seen:
            continue
        seen.add(m.id)
        out.append(m)
    return out
