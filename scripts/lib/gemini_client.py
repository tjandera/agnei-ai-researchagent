"""
Gemini cloud client — uses Google's OpenAI-compatible endpoint.

The primary synthesis backend for the hosted web app. make_client() picks this
when GEMINI_API_KEY is set. Gemini 2.5 Flash is the default: fast, generous
free tier (1M tokens/day), and has built-in thinking/reasoning.

Get a free key at: https://aistudio.google.com/apikey
"""

import json
import os
import re
import requests
from typing import Any, Dict, Generator, List, Optional

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
_DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


class GeminiClient:
    """Gemini API via Google's OpenAI-compatible endpoint."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        request_timeout: int = 120,
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self.model = model or _DEFAULT_MODEL
        self.base_url = _BASE_URL
        self.request_timeout = request_timeout
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------ #
    # Reachability
    # ------------------------------------------------------------------ #

    @staticmethod
    def is_available() -> bool:
        """True when a Gemini API key is present in the environment."""
        return bool(os.environ.get("GEMINI_API_KEY", "").strip())

    # ------------------------------------------------------------------ #
    # Chat / Synthesis
    # ------------------------------------------------------------------ #

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict]] = None,
        thinking: bool = True,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.7,
        **kwargs,
    ) -> Dict:
        """Call Gemini chat completions (non-streaming, returns full response dict)."""
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self.headers,
            json=payload,
            timeout=self.request_timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        max_tokens: int = 1200,
        temperature: float = 0.4,
    ) -> Generator[str, None, None]:
        """Stream content token-by-token (generator of str chunks).

        Handles the SSE `data: {...}` format that Gemini's OpenAI-compat
        endpoint emits. Filters out any stray thinking blocks.
        """
        payload = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        with requests.post(
            f"{self.base_url}/chat/completions",
            headers=self.headers,
            json=payload,
            stream=True,
            timeout=self.request_timeout,
        ) as resp:
            resp.raise_for_status()
            for raw in resp.iter_lines():
                if not raw:
                    continue
                text = raw.decode("utf-8")
                if text.startswith("data: "):
                    text = text[6:]
                if text.strip() == "[DONE]":
                    break
                try:
                    obj = json.loads(text)
                except (ValueError, UnicodeDecodeError):
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content") or ""
                if piece:
                    yield piece

    def get_message_content(self, response: Dict) -> str:
        """Extract text, stripping any <think> blocks."""
        try:
            content = response["choices"][0]["message"].get("content") or ""
        except (KeyError, IndexError, TypeError):
            return ""
        return _THINK_BLOCK.sub("", content).strip()

    def get_tool_calls(self, response: Dict) -> Optional[List[Dict]]:
        try:
            return response["choices"][0]["message"].get("tool_calls")
        except (KeyError, IndexError, TypeError):
            return None

    def finish_reason(self, response: Dict) -> str:
        try:
            return response["choices"][0].get("finish_reason", "")
        except (KeyError, IndexError, TypeError):
            return ""

    # Media stubs — not supported; callers fall back gracefully
    def generate_image(self, *args, **kwargs):
        raise NotImplementedError("Gemini client does not generate images.")

    def generate_video(self, *args, **kwargs):
        raise NotImplementedError("Gemini client does not generate video.")
