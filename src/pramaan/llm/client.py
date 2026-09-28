"""LLM clients. ``WatsonxLLM`` talks to the watsonx.ai REST API directly via httpx."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Any, Protocol

import httpx

from ..config import Settings, get_settings

IAM_URL = "https://iam.cloud.ibm.com/identity/token"
CHAT_PATH = "/ml/v1/text/chat"
API_VERSION = "2024-10-08"


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    name: str

    def chat(self, system: str, user: str, max_tokens: int = 900) -> str: ...


class NullLLM:
    name = "none"

    def chat(self, system: str, user: str, max_tokens: int = 900) -> str:
        raise LLMError("No LLM provider configured (PRAMAAN_LLM_PROVIDER=none)")


class WatsonxLLM:
    """Minimal watsonx.ai chat client: IAM API-key exchange + /ml/v1/text/chat."""

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None, timeout: float = 45.0) -> None:
        if not settings.watsonx_api_key or not (settings.watsonx_project_id or settings.watsonx_space_id):
            raise LLMError("WATSONX_API_KEY and WATSONX_PROJECT_ID (or WATSONX_SPACE_ID) are required")
        self.settings = settings
        self.name = f"watsonx:{settings.watsonx_model_id}"
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self._token: str | None = None
        self._token_exp = 0.0
        self._lock = threading.Lock()

    def _bearer(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_exp - 60:
                return self._token
            try:
                r = self._http.post(
                    IAM_URL,
                    data={"grant_type": "urn:ibm:params:oauth:grant-type:apikey", "apikey": self.settings.watsonx_api_key},
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                raise LLMError(f"IAM token exchange failed: {exc}") from exc
            if r.status_code != 200:
                raise LLMError(f"IAM token exchange failed: HTTP {r.status_code}")
            body = r.json()
            self._token = body["access_token"]
            self._token_exp = time.time() + float(body.get("expires_in", 3600))
            return self._token

    def chat(self, system: str, user: str, max_tokens: int = 900) -> str:
        payload: dict[str, Any] = {
            "model_id": self.settings.watsonx_model_id,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": [{"type": "text", "text": user}]},
            ],
            "max_tokens": max_tokens,
            "temperature": 0,
            "time_limit": 40000,
        }
        if self.settings.watsonx_project_id:
            payload["project_id"] = self.settings.watsonx_project_id
        else:
            payload["space_id"] = self.settings.watsonx_space_id
        url = f"{self.settings.watsonx_url.rstrip('/')}{CHAT_PATH}?version={API_VERSION}"
        try:
            r = self._http.post(url, json=payload, headers={"Authorization": f"Bearer {self._bearer()}", "Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise LLMError(f"watsonx.ai chat failed: {exc}") from exc
        if r.status_code != 200:
            raise LLMError(f"watsonx.ai chat failed: HTTP {r.status_code}: {r.text[:300]}")
        try:
            return r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Unexpected watsonx.ai response shape: {exc}") from exc


def extract_json(text: str) -> Any:
    """Parse the first JSON object/array in a model reply (tolerates ``` fences and preambles)."""
    cleaned = re.sub(r"```(?:json)?", "", text).strip()
    for opener, closer in (("[", "]"), ("{", "}")):
        start, end = cleaned.find(opener), cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start: end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("Model reply did not contain valid JSON")


def get_llm(settings: Settings | None = None, strict: bool = False) -> LLMClient:
    """Return the configured client. With ``strict=False`` a mis-configured watsonx
    provider degrades to the offline engine (logged) instead of failing the triage."""
    settings = settings or get_settings()
    if settings.llm_provider == "watsonx":
        try:
            return WatsonxLLM(settings)
        except LLMError:
            if strict:
                raise
            logging.getLogger(__name__).warning("watsonx.ai not configured; falling back to offline engine")
    return NullLLM()
