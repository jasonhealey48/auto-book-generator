"""
Image generation providers with auto-fallback routing.

Providers:
- Pollinations       (free, no key required — fast GET)
- Stable Horde       (community GPUs, async, needs free registered key)
- HFSpace            (Hugging Face Gradio space — experimental)
- Google Nano Banana (Google Gemini API — needs API key, uses Cloud credits)
"""

import os
import time
import json
import base64
import urllib.parse
import requests
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Result + base class
# ---------------------------------------------------------------------------

@dataclass
class ImageResult:
    path: str
    url: str = ""
    latency_ms: int = 0
    model: str = ""
    ok: bool = True
    error: Optional[str] = None


class ImageProvider:
    name: str = "base"
    requires_key: bool = False
    DEFAULT_MODEL: str = ""

    def __init__(self, api_key: str = "", model: str = "",
                 save_dir: str = "Generated_Books/images"):
        self.api_key = api_key
        self.model = model or self.DEFAULT_MODEL
        self.save_dir = save_dir
        os.makedirs(self.save_dir, exist_ok=True)

    def is_available(self) -> bool:
        if not self.requires_key:
            return True
        return bool(self.api_key)

    def generate(self, prompt: str, negative: str = "",
                 width: int = 512, height: int = 512,
                 filename_hint: str = "") -> ImageResult:
        raise NotImplementedError

    def probe_latency(self) -> int:
        return 99999

    @staticmethod
    def _safe_name(hint: str, prompt: str) -> str:
        base = hint or prompt[:40]
        safe = "".join(c for c in base if c.isalnum() or c in (" ", "_"))
        return (safe.strip().replace(" ", "_") or "img")[:40]


# ---------------------------------------------------------------------------
# Pollinations image (free, keyless GET)
# ---------------------------------------------------------------------------

class PollinationsImageProvider(ImageProvider):
    name = "Pollinations"
    requires_key = False
    DEFAULT_MODEL = "flux"

    def generate(self, prompt: str, negative: str = "",
                 width: int = 512, height: int = 512,
                 filename_hint: str = "") -> ImageResult:
        safe = self._safe_name(filename_hint, prompt)
        local = os.path.join(self.save_dir,
                             f"poll_{safe}_{int(time.time()*1000) % 100000}.jpg")

        params = [f"width={width}", f"height={height}", "nologo=true",
                  "model=" + urllib.parse.quote(self.model or "flux")]
        if negative:
            params.append("negative_prompt=" + urllib.parse.quote(negative))
        url = ("https://image.pollinations.ai/prompt/"
               + urllib.parse.quote(prompt[:300])
               + "?" + "&".join(params))

        t0 = time.time()
        try:
            r = requests.get(url, timeout=90)
        except requests.exceptions.RequestException as e:
            return ImageResult("", url, int((time.time()-t0)*1000), self.model,
                               ok=False, error=f"network: {e}")

        ms = int((time.time() - t0) * 1000)
        if r.status_code != 200 or len(r.content) < 1024:
            return ImageResult("", url, ms, self.model, ok=False,
                               error=f"HTTP {r.status_code}")

        with open(local, "wb") as f:
            f.write(r.content)
        return ImageResult(local, url, ms, self.model, ok=True)


# ---------------------------------------------------------------------------
# Stable Horde (async, needs free registered API key)
# ---------------------------------------------------------------------------

class StableHordeImageProvider(ImageProvider):
    name = "StableHorde"
    requires_key = True
    DEFAULT_MODEL = "Deliberate"

    def is_available(self) -> bool:
        return bool(self.api_key and self.api_key.strip())

    def generate(self, prompt: str, negative: str = "",
                 width: int = 512, height: int = 512,
                 filename_hint: str = "") -> ImageResult:
        safe = self._safe_name(filename_hint, prompt)
        local = os.path.join(self.save_dir,
                             f"horde_{safe}_{int(time.time()*1000) % 100000}.png")

        payload = {
            "prompt": prompt,
            "params": {
                "sampler_name": "k_dpmpp_2m",
                "cfg_scale": 7.5,
                "seed": "0",
                "steps": 25,
                "width": width,
                "height": height,
                "karras": True,
                "n": 1,
            },
            "nsfw": False,
            "trusted_workers": False,
            "slow_workers": True,
            "censor_nsfw": True,
            "models": [self.model],
            "shared": True,
        }
        if negative:
            payload["params"]["negative_prompt"] = negative

        t0 = time.time()
        try:
            r = requests.post(
                "https://stablehorde.net/api/v2/generate/async",
                json=payload,
                headers={"apikey": self.api_key, "Content-Type": "application/json"},
                timeout=30,
            )
        except requests.exceptions.RequestException as e:
            return ImageResult("", "", int((time.time()-t0)*1000), self.model,
                               ok=False, error=f"network: {e}")

        ms = int((time.time() - t0) * 1000)
        if r.status_code == 401:
            return ImageResult("", "", ms, self.model, ok=False, error="auth failed — check Horde API key")
        if r.status_code not in (200, 202):
            return ImageResult("", "", ms, self.model, ok=False,
                               error=f"HTTP {r.status_code}: {r.text[:120]}")

        try:
            job_id = r.json().get("id")
        except Exception as e:
            return ImageResult("", "", ms, self.model, ok=False, error=f"parse: {e}")

        if not job_id:
            return ImageResult("", "", ms, self.model, ok=False, error="no job id returned")

        poll_url = f"https://stablehorde.net/api/v2/generate/check/{job_id}"
        status_url = f"https://stablehorde.net/api/v2/generate/status/{job_id}"
        deadline = time.time() + 180
        poll_interval = 3.0
        generation = None

        while time.time() < deadline:
            time.sleep(poll_interval)
            try:
                ck = requests.get(poll_url, timeout=15)
                ck_data = ck.json() if ck.status_code == 200 else {}
            except Exception:
                continue

            if ck_data.get("done"):
                try:
                    res_data = requests.get(status_url, timeout=20).json()
                    gens = res_data.get("generations") or []
                    if gens:
                        generation = gens[0]
                        break
                except Exception:
                    continue
            else:
                eta = ck_data.get("wait_time", 0)
                poll_interval = min(10, max(2, (eta or 5) / 3))

        if not generation:
            return ImageResult("", "", int((time.time()-t0)*1000), self.model,
                               ok=False, error="timeout waiting for Horde job")

        img_url = (generation.get("img") or "").replace("&amp;", "&")
        if not img_url:
            return ImageResult("", "", int((time.time()-t0)*1000), self.model,
                               ok=False, error="no image URL in result")

        try:
            ir = requests.get(img_url, timeout=60)
        except requests.exceptions.RequestException as e:
            return ImageResult("", img_url, int((time.time()-t0)*1000),
                               self.model, ok=False, error=f"download: {e}")

        if ir.status_code != 200 or len(ir.content) < 256:
            return ImageResult("", img_url, int((time.time()-t0)*1000),
                               self.model, ok=False, error=f"download HTTP {ir.status_code}")

        with open(local, "wb") as f:
            f.write(ir.content)
        return ImageResult(local, img_url, int((time.time()-t0)*1000), self.model, ok=True)

    def probe_latency(self) -> int:
        try:
            t0 = time.time()
            r = requests.get("https://stablehorde.net/api/v2/status/heartbeat", timeout=10)
            return int((time.time()-t0)*1000) if r.status_code == 200 else 99999
        except Exception:
            return 99999


# ---------------------------------------------------------------------------
# HF Space (experimental — returns not-implemented gracefully)
# ---------------------------------------------------------------------------

class HFSpaceImageProvider(ImageProvider):
    name = "HuggingFaceSpace"
    requires_key = False
    DEFAULT_MODEL = "black-forest-labs/FLUX.1-schnell"

    def generate(self, prompt: str, negative: str = "",
                 width: int = 512, height: int = 512,
                 filename_hint: str = "") -> ImageResult:
        return ImageResult("", "", 0, self.model, ok=False,
                           error="HFSpace provider not implemented — use Pollinations")


# ---------------------------------------------------------------------------
# Google Nano Banana — Gemini API image generation
# ---------------------------------------------------------------------------

NANO_BANANA_MODELS = {
    "gemini-3.1-flash-lite-image": "Nano Banana 2 Lite (fastest, cheapest)",
    "gemini-3.1-flash-image": "Nano Banana 2 (best balance)",
    "gemini-2.5-flash-image": "Nano Banana (original)",
    "gemini-3-pro-image": "Nano Banana Pro (highest quality)",
}


class GoogleNanoBananaProvider(ImageProvider):
    """Google Nano Banana via Gemini API — uses same API key as text."""
    name = "Google Nano Banana"
    requires_key = True
    DEFAULT_MODEL = "gemini-3.1-flash-lite-image"

    def __init__(self, api_key: str = "", model: str = "",
                 save_dir: str = "Generated_Books/images"):
        super().__init__(api_key=api_key, model=model or self.DEFAULT_MODEL, save_dir=save_dir)
        self.DEFAULT_MODEL = "gemini-3.1-flash-lite-image"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, prompt: str, negative: str = "",
                 width: int = 512, height: int = 512,
                 filename_hint: str = "") -> ImageResult:
        if not self.api_key:
            return ImageResult("", "", 0, self.model, ok=False, error="missing API key")

        safe = self._safe_name(filename_hint, prompt)
        local = os.path.join(self.save_dir,
                             f"nano_{safe}_{int(time.time()*1000) % 100000}.png")

        model = self.model or self.DEFAULT_MODEL
        url = (f"https://generativelanguage.googleapis.com/v1beta/"
               f"models/{model}:generateContent")

        full_prompt = prompt
        if negative:
            full_prompt += f"\nAvoid: {negative}"

        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
            },
        }

        t0 = time.time()
        try:
            r = requests.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                json=payload,
                timeout=120,
            )
        except requests.exceptions.RequestException as e:
            return ImageResult("", "", int((time.time()-t0)*1000), self.model,
                               ok=False, error=f"network: {e}")

        ms = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            error_detail = ""
            try:
                err_data = r.json()
                error_detail = err_data.get("error", {}).get("message", r.text[:200])
            except Exception:
                error_detail = r.text[:200]
            return ImageResult("", "", ms, self.model, ok=False,
                               error=f"HTTP {r.status_code}: {error_detail}")

        try:
            data = r.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return ImageResult("", "", ms, self.model, ok=False,
                                   error="no candidates returned")

            parts = candidates[0].get("content", {}).get("parts", [])
            img_bytes = None
            for part in parts:
                if "inlineData" in part:
                    img_data = part["inlineData"]
                    img_bytes = base64.b64decode(img_data.get("data", ""))
                    break

            if not img_bytes:
                return ImageResult("", "", ms, self.model, ok=False,
                                   error="no image data in response")
        except Exception as e:
            return ImageResult("", "", ms, self.model, ok=False, error=f"parse: {e}")

        if len(img_bytes) < 256:
            return ImageResult("", "", ms, self.model, ok=False,
                               error="image data too small")

        with open(local, "wb") as f:
            f.write(img_bytes)

        return ImageResult(local, "", ms, self.model, ok=True)

    def probe_latency(self) -> int:
        if not self.api_key:
            return 99999
        try:
            t0 = time.time()
            model = self.model or self.DEFAULT_MODEL
            url = (f"https://generativelanguage.googleapis.com/v1beta/"
                   f"models/{model}:generateContent")
            payload = {
                "contents": [{"parts": [{"text": "Generate a tiny red dot"}]}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            }
            r = requests.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": self.api_key,
                },
                json=payload,
                timeout=30,
            )
            return int((time.time()-t0)*1000) if r.status_code == 200 else 99999
        except Exception:
            return 99999


# ---------------------------------------------------------------------------
# Factory + config + router
# ---------------------------------------------------------------------------

def make_image_provider(name: str, api_key: str = "", model: str = "",
                         save_dir: str = "Generated_Books/images") -> ImageProvider:
    n = name.lower()
    if n in ("pollinations", "pollinations (free)"):
        return PollinationsImageProvider(api_key, model, save_dir)
    if n in ("stablehorde", "horde", "stable horde"):
        return StableHordeImageProvider(api_key, model, save_dir)
    if n in ("hfspace", "huggingface_space", "huggingface", "hf"):
        return HFSpaceImageProvider(api_key, model, save_dir)
    if n in ("google nano banana", "nano banana", "google", "nano_banana"):
        return GoogleNanoBananaProvider(api_key, model, save_dir)
    raise ValueError(f"Unknown image provider: {name}")


@dataclass
class ImageProviderConfig:
    name: str
    api_key: str = ""
    model: str = ""
    enabled: bool = True
    priority: int = 0


class ImageRouter:
    def __init__(self, configs: List[ImageProviderConfig],
                 save_dir: str = "Generated_Books/images"):
        self.configs = sorted(configs, key=lambda c: c.priority)
        self.save_dir = save_dir
        self.latency_ms: Dict[str, int] = {}

    def _build(self, cfg: ImageProviderConfig) -> ImageProvider:
        return make_image_provider(cfg.name, cfg.api_key, cfg.model, self.save_dir)

    def _available(self) -> List[ImageProviderConfig]:
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

    def probe_all(self) -> Dict[str, int]:
        out = {}
        for cfg in self._available():
            try:
                ms = self._build(cfg).probe_latency()
            except Exception:
                ms = 99999
            out[cfg.name] = ms
            self.latency_ms[cfg.name] = ms
        return out

    def generate(self, prompt: str, **opts) -> Tuple[ImageResult, str]:
        last = None
        for cfg in self._available():
            try:
                p = self._build(cfg)
                res = p.generate(prompt, **opts)
                if res.ok and res.path:
                    return res, p.name
                last = (p.name, res.error or "unknown")
            except Exception as e:
                last = (cfg.name, f"{type(e).__name__}: {e}")
        name = last[0] if last else "(none)"
        err = last[1] if last else "no image providers available"
        return ImageResult("", "", 0, "", ok=False,
                           error=f"all image providers failed (last={name}): {err}"), name
