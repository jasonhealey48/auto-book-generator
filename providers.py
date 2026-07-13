"""
Text generation providers with auto-fallback routing.

Supported providers:
- Pollinations  (free, no key — OpenAI-compatible POST)
- OpenRouter    (free tier available — needs API key)
- NVIDIA NIM    (needs API key)
- HuggingFace   (needs API key)
- Google Gemini (needs API key — native Gemini API)
- Groq          (needs API key)
"""

import os
import time
import json
import requests
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Result + base class
# ---------------------------------------------------------------------------

@dataclass
class ProviderResult:
    text: str
    latency_ms: int
    model: str
    ok: bool = True
    error: Optional[str] = None


class Provider:
    name: str = "base"
    requires_key: bool = True
    DEFAULT_MODEL: str = ""

    def __init__(self, api_key: str = "", model: str = "", base_url: str = ""):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.base_url = base_url

    def is_available(self) -> bool:
        if not self.requires_key:
            return True
        return bool(self.api_key)

    def complete(self, messages: List[Dict[str, str]], **opts) -> ProviderResult:
        raise NotImplementedError

    def probe_latency(self) -> int:
        try:
            t0 = time.time()
            res = self.complete(
                [{"role": "user", "content": "Reply with the single word: pong"}],
                max_tokens=8, temperature=0.0,
            )
            if res.ok:
                return int((time.time() - t0) * 1000)
        except Exception:
            pass
        return 99999


# ---------------------------------------------------------------------------
# Pollinations (free, keyless) — uses POST /openai/chat/completions
# ---------------------------------------------------------------------------

POLLINATIONS_MODELS = ("openai-fast", "openai")


class PollinationsProvider(Provider):
    name = "Pollinations"
    requires_key = False
    DEFAULT_MODEL = "openai-fast"

    def __init__(self, api_key: str = "", model: str = ""):
        super().__init__(api_key="", model=model)
        if self.model not in POLLINATIONS_MODELS:
            self.model = self.DEFAULT_MODEL

    def is_available(self) -> bool:
        return True

    def complete(self, messages: List[Dict], **opts) -> ProviderResult:
        max_tokens = int(opts.get("max_tokens", 1500))
        temperature = float(opts.get("temperature", 0.8))
        t0 = time.time()
        last_err = None

        models_to_try = [self.model]
        for m in POLLINATIONS_MODELS:
            if m not in models_to_try:
                models_to_try.append(m)

        for model in models_to_try:
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            try:
                r = requests.post(
                    "https://text.pollinations.ai/openai/chat/completions",
                    json=payload,
                    timeout=180,
                )
            except requests.exceptions.Timeout:
                last_err = f"{model}: request timed out after 180s"
                continue
            except requests.exceptions.RequestException as e:
                last_err = f"{model}: network: {e}"
                continue

            latency_ms = int((time.time() - t0) * 1000)
            if r.status_code == 429:
                last_err = f"{model}: rate limited (HTTP 429)"
                time.sleep(5)
                continue
            if r.status_code != 200:
                last_err = f"{model}: HTTP {r.status_code}: {r.text[:120]}"
                continue

            try:
                data = r.json()
                text = data["choices"][0]["message"]["content"]
            except Exception as e:
                last_err = f"{model}: parse error: {e}"
                continue

            text = (text or "").strip()
            if not text:
                last_err = f"{model}: empty response"
                continue

            return ProviderResult(text, latency_ms, model, ok=True)

        return ProviderResult(
            "", int((time.time() - t0) * 1000),
            models_to_try[0], ok=False,
            error=last_err or "all models failed",
        )


# ---------------------------------------------------------------------------
# Generic OpenAI-compatible provider
# ---------------------------------------------------------------------------

class OpenAICompatibleProvider(Provider):
    def __init__(self, name: str, base_url: str, requires_key: bool,
                 default_model: str, api_key: str = "", model: str = ""):
        super().__init__(api_key=api_key, model=model or default_model, base_url=base_url)
        self.name = name
        self._requires_key = requires_key
        self.DEFAULT_MODEL = default_model

    def is_available(self) -> bool:
        if not self._requires_key:
            return True
        return bool(self.api_key)

    def complete(self, messages: List[Dict], **opts) -> ProviderResult:
        if self._requires_key and not self.api_key:
            return ProviderResult("", 0, self.model, ok=False, error="missing API key")

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": float(opts.get("temperature", 0.8)),
            "max_tokens": int(opts.get("max_tokens", 1500)),
        }

        t0 = time.time()
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=120)
        except requests.exceptions.RequestException as e:
            return ProviderResult("", int((time.time()-t0)*1000), self.model,
                                  ok=False, error=f"network: {e}")

        latency_ms = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            return ProviderResult("", latency_ms, self.model, ok=False,
                                  error=f"HTTP {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
            text = data["choices"][0]["message"]["content"]
        except Exception as e:
            return ProviderResult("", latency_ms, self.model, ok=False,
                                  error=f"parse: {e}")

        text = (text or "").strip()
        if not text:
            return ProviderResult("", latency_ms, self.model, ok=False, error="empty response")
        return ProviderResult(text, latency_ms, self.model, ok=True)


# ---------------------------------------------------------------------------
# Google Gemini — native generateContent API
# ---------------------------------------------------------------------------

class GoogleGeminiProvider(Provider):
    """Uses Google's native Gemini API (not the OpenAI-compat wrapper)."""
    name = "Google"
    requires_key = True
    DEFAULT_MODEL = "gemini-2.0-flash"

    def __init__(self, api_key: str = "", model: str = ""):
        super().__init__(api_key=api_key, model=model or self.DEFAULT_MODEL)
        self.DEFAULT_MODEL = "gemini-2.0-flash"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def _messages_to_contents(self, messages: List[Dict]) -> list:
        contents = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            gemini_role = "user" if role in ("user", "system") else "model"
            contents.append({"role": gemini_role, "parts": [{"text": content}]})
        if not contents:
            contents = [{"role": "user", "parts": [{"text": "Hello"}]}]
        return contents

    def complete(self, messages: List[Dict], **opts) -> ProviderResult:
        if not self.api_key:
            return ProviderResult("", 0, self.model, ok=False, error="missing API key")

        model = self.model or self.DEFAULT_MODEL
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {"Content-Type": "application/json"}
        params = {"key": self.api_key}
        payload = {
            "contents": self._messages_to_contents(messages),
            "generationConfig": {
                "temperature": float(opts.get("temperature", 0.8)),
                "maxOutputTokens": int(opts.get("max_tokens", 1500)),
            },
        }

        t0 = time.time()
        try:
            r = requests.post(url, headers=headers, params=params, json=payload, timeout=120)
        except requests.exceptions.RequestException as e:
            return ProviderResult("", int((time.time()-t0)*1000), model,
                                  ok=False, error=f"network: {e}")

        latency_ms = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            error_detail = ""
            try:
                err_data = r.json()
                error_detail = err_data.get("error", {}).get("message", r.text[:200])
            except Exception:
                error_detail = r.text[:200]
            return ProviderResult("", latency_ms, model, ok=False,
                                  error=f"HTTP {r.status_code}: {error_detail}")

        try:
            data = r.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return ProviderResult("", latency_ms, model, ok=False, error="no candidates returned")
            parts = candidates[0].get("content", {}).get("parts", [])
            text = parts[0].get("text", "") if parts else ""
        except Exception as e:
            return ProviderResult("", latency_ms, model, ok=False, error=f"parse: {e}")

        text = (text or "").strip()
        if not text:
            return ProviderResult("", latency_ms, model, ok=False, error="empty response")
        return ProviderResult(text, latency_ms, model, ok=True)

    def probe_latency(self) -> int:
        try:
            t0 = time.time()
            res = self.complete(
                [{"role": "user", "content": "Reply with the single word: pong"}],
                max_tokens=8, temperature=0.0,
            )
            if res.ok:
                return int((time.time() - t0) * 1000)
        except Exception:
            pass
        return 99999


# ---------------------------------------------------------------------------
# Provider factory functions
# ---------------------------------------------------------------------------

def make_nvidia(api_key: str = "", model: str = "") -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="NVIDIA",
        base_url="https://integrate.api.nvidia.com/v1",
        requires_key=True,
        default_model="meta/llama-3.1-8b-instruct",
        api_key=api_key, model=model,
    )


def make_openrouter(api_key: str = "", model: str = "") -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        requires_key=True,
        default_model="meta-llama/llama-3.1-8b-instruct:free",
        api_key=api_key, model=model,
    )


def make_huggingface(api_key: str = "", model: str = "") -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="HuggingFace",
        base_url="https://huggingface.co/api",
        requires_key=True,
        default_model="meta-llama/Meta-Llama-3-8B-Instruct",
        api_key=api_key, model=model,
    )


def make_google(api_key: str = "", model: str = "") -> GoogleGeminiProvider:
    return GoogleGeminiProvider(api_key=api_key, model=model)


def make_groq(api_key: str = "", model: str = "") -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
        requires_key=True,
        default_model="llama-3.1-8b-instant",
        api_key=api_key, model=model,
    )


# ---------------------------------------------------------------------------
# Router config + Router
# ---------------------------------------------------------------------------

@dataclass
class ProviderConfig:
    name: str
    api_key: str = ""
    model: str = ""
    enabled: bool = True
    priority: int = 0


class Router:
    def __init__(self, configs: List[ProviderConfig]):
        self.configs = sorted(configs, key=lambda c: c.priority)
        self.latency_ms: Dict[str, int] = {}
        self.mode: str = "priority"

    def _build(self, cfg: ProviderConfig) -> Provider:
        n = cfg.name.lower()
        if n == "pollinations":
            return PollinationsProvider(model=cfg.model)
        if n == "nvidia":
            return make_nvidia(api_key=cfg.api_key, model=cfg.model)
        if n == "openrouter":
            return make_openrouter(api_key=cfg.api_key, model=cfg.model)
        if n in ("huggingface", "hf"):
            return make_huggingface(api_key=cfg.api_key, model=cfg.model)
        if n == "google":
            return make_google(api_key=cfg.api_key, model=cfg.model)
        if n == "groq":
            return make_groq(api_key=cfg.api_key, model=cfg.model)
        raise ValueError(f"Unknown provider: {cfg.name}")

    def _available(self) -> List[ProviderConfig]:
        out = []
        for c in self.configs:
            if not c.enabled:
                continue
            try:
                if self._build(c).is_available():
                    out.append(c)
            except Exception:
                pass
        return out

    def _sorted(self) -> List[ProviderConfig]:
        cfgs = self._available()
        if self.mode == "fastest" and self.latency_ms:
            return sorted(cfgs, key=lambda c: self.latency_ms.get(c.name, 99999))
        return sorted(cfgs, key=lambda c: c.priority)

    def probe_all(self) -> Dict[str, int]:
        self.latency_ms = {}
        for cfg in self._available():
            try:
                ms = self._build(cfg).probe_latency()
            except Exception:
                ms = 99999
            self.latency_ms[cfg.name] = ms
        return dict(self.latency_ms)

    def complete(self, messages: List[Dict], **opts) -> Tuple[ProviderResult, str]:
        last_err = None
        for cfg in self._sorted():
            try:
                p = self._build(cfg)
                res = p.complete(messages, **opts)
                if res.ok and res.text and len(res.text) >= 20:
                    return res, p.name
                last_err = (p.name, res.error or "too short")
                if res.error and ("401" in str(res.error) or "404" in str(res.error)):
                    break
            except Exception as e:
                last_err = (cfg.name, str(e))
        name = last_err[0] if last_err else "(none)"
        err = last_err[1] if last_err else "no providers available"
        return ProviderResult("", 0, "", ok=False,
                              error=f"all providers failed (last={name}): {err}"), name
