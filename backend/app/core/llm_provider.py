"""Unified LLM provider abstraction supporting local Ollama and external APIs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from app.config import Settings, settings


class BaseLLMProvider(ABC):
    """Abstract interface for text generation across local and cloud LLMs."""

    @abstractmethod
    async def generate(self, prompt: str, system: str = "", temperature: float = 0.2) -> str:
        """Generate a completion for the given prompt."""


class OllamaProvider(BaseLLMProvider):
    """100% local LLM execution via Ollama HTTP API (with automatic Docker host fallback & 90s cold-start timeout)."""

    def __init__(self, base_url: str, model: str, timeout: float = 90.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = max(float(timeout), 60.0)

    def _candidate_urls(self) -> list[str]:
        urls = [self.base_url]
        if "localhost" in self.base_url or "127.0.0.1" in self.base_url:
            docker_host = self.base_url.replace("localhost", "host.docker.internal").replace(
                "127.0.0.1", "host.docker.internal"
            )
            if docker_host not in urls:
                urls.append(docker_host)
        return urls

    async def generate(self, prompt: str, system: str = "", temperature: float = 0.2) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"temperature": temperature},
        }
        last_exc: Optional[Exception] = None
        for u in self._candidate_urls():
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(f"{u}/api/generate", json=payload)
                    resp.raise_for_status()
                    return resp.json().get("response", "")
            except httpx.ConnectError as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        return ""

    async def analyze_image_and_text(
        self,
        prompt: str,
        image_b64: str,
        mime_type: str = "image/png",
        client: Optional[httpx.AsyncClient] = None,
    ) -> str:
        """Analyze an attached screenshot/document image using a local Ollama vision model."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": [image_b64],
            "stream": False,
        }
        last_exc: Optional[Exception] = None
        for u in self._candidate_urls():
            try:
                if client is not None:
                    resp = await client.post(f"{u}/api/generate", json=payload, timeout=self.timeout)
                else:
                    async with httpx.AsyncClient(timeout=self.timeout) as temp_client:
                        resp = await temp_client.post(f"{u}/api/generate", json=payload)
                resp.raise_for_status()
                return resp.json().get("response", "")
            except httpx.ConnectError as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        return ""


class OpenAICompatibleProvider(BaseLLMProvider):
    """Supports OpenAI, OpenRouter, vLLM, or any OpenAI-compatible chat endpoint."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def generate(self, prompt: str, system: str = "", temperature: float = 0.2) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"model": self.model, "messages": messages, "temperature": temperature}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions", headers=headers, json=payload
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]


class GeminiProvider(BaseLLMProvider):
    """Google Gemini REST API provider."""

    def __init__(self, api_key: str, model: str, timeout: float = 60.0) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def generate(self, prompt: str, system: str = "", temperature: float = 0.2) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": 8192},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            candidates = resp.json().get("candidates", [])
            if not candidates:
                return ""
            parts = candidates[0].get("content", {}).get("parts", [])
            text_parts = [
                str(p.get("text", ""))
                for p in parts
                if p.get("text") and not p.get("thought")
            ]
            return "".join(text_parts).strip()

    async def generate_with_google_search(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        client: Optional[httpx.AsyncClient] = None,
    ) -> dict[str, Any]:
        """Run Gemini with native Google Search Grounding (Google AI Mode API).

        Returns `{"text": str, "sources": [{"title": str, "url": str}]}`.
        """
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"temperature": temperature},
        }
        if client is not None:
            resp = await client.post(url, json=payload)
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as temp_client:
                resp = await temp_client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        candidates = data.get("candidates", [])
        if not candidates:
            return {"text": "", "sources": []}

        cand = candidates[0]
        parts = cand.get("content", {}).get("parts", [])
        text = "\n".join(str(p.get("text", "")) for p in parts if p.get("text")).strip()

        sources: list[dict[str, str]] = []
        grounding = cand.get("groundingMetadata") or {}
        for chunk in grounding.get("groundingChunks", []):
            web = chunk.get("web") or {}
            if web.get("uri"):
                sources.append(
                    {
                        "title": str(web.get("title") or web["uri"]),
                        "url": str(web["uri"]),
                    }
                )
        return {"text": text, "sources": sources}

    async def analyze_image_and_text(
        self,
        prompt: str,
        image_b64: str,
        mime_type: str = "image/png",
        client: Optional[httpx.AsyncClient] = None,
    ) -> str:
        """Analyze an attached screenshot/table (e.g. schedule, portal) via Gemini Vision."""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0.1},
        }
        if client is not None:
            resp = await client.post(url, json=payload)
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as temp_client:
                resp = await temp_client.post(url, json=payload)
        resp.raise_for_status()
        candidates = resp.json().get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "\n".join(str(p.get("text", "")) for p in parts if p.get("text")).strip()


def build_llm_provider(cfg: Settings = settings) -> BaseLLMProvider | None:
    """Instantiate the configured LLM provider, or None if running heuristic-only."""
    if cfg.llm_provider == "ollama":
        return OllamaProvider(cfg.ollama_base_url, cfg.ollama_model)
    if cfg.llm_provider == "openai":
        return OpenAICompatibleProvider(cfg.openai_base_url, cfg.openai_api_key, cfg.openai_model)
    if cfg.llm_provider == "gemini":
        return GeminiProvider(cfg.gemini_api_key, cfg.gemini_model)
    return None
