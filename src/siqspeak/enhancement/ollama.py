"""Loopback-only HTTP client for a local Ollama server.

This client talks only to a loopback endpoint. Every HTTP, network, timeout,
and malformed-response failure is mapped to a small exception hierarchy so the
enhancement service can fall back to raw text losslessly.

Request messages and generated prompt content are never logged.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_HEADERS = {"Content-Type": "application/json"}


class OllamaError(RuntimeError):
    """Any failure while talking to the local Ollama server."""


class OllamaUnavailable(OllamaError):
    """The server could not be reached (network refused or timed out)."""


@dataclass(frozen=True)
class OllamaClient:
    """Minimal client for the local Ollama HTTP API, loopback only."""

    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 45.0

    def __post_init__(self) -> None:
        host = urllib.parse.urlsplit(self.base_url).hostname
        if host not in _LOOPBACK_HOSTS:
            raise OllamaError(f"Ollama endpoint must be loopback, got {host!r}")

    def is_available(self) -> bool:
        """Return whether the server responds to a tags request."""
        try:
            self.list_models()
        except OllamaError:
            return False
        return True

    def list_models(self) -> tuple[str, ...]:
        """Return the names of locally installed models."""
        body = self._send_json("/api/tags")
        if not isinstance(body, dict):
            raise OllamaError("Unexpected tags response")
        models = body.get("models")
        if not isinstance(models, list):
            raise OllamaError("Tags response missing models list")
        names: list[str] = []
        for entry in models:
            if isinstance(entry, dict):
                name = entry.get("name")
                if isinstance(name, str):
                    names.append(name)
        return tuple(names)

    def has_model(self, model: str) -> bool:
        """Return whether a model is installed, matching exact and ``:latest``."""
        available = self.list_models()
        if model in available:
            return True
        return ":" not in model and f"{model}:latest" in available

    def chat_structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: dict[str, object],
    ) -> dict[str, object]:
        """Request a structured JSON reply constrained by ``schema``."""
        payload = {
            "model": model,
            "messages": messages,
            "format": schema,
            "think": False,
            "stream": False,
            "keep_alive": "10m",
            "options": {"temperature": 0},
        }
        body = self._send_json("/api/chat", payload)
        if not isinstance(body, dict):
            raise OllamaError("Unexpected chat response")
        message = body.get("message")
        if not isinstance(message, dict):
            raise OllamaError("Chat response missing message")
        content = message.get("content")
        if not isinstance(content, str):
            raise OllamaError("Chat response missing content")
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaError("Chat content was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise OllamaError("Chat content was not a JSON object")
        return parsed

    def pull_model(
        self,
        model: str,
        on_progress: Callable[[float], None],
    ) -> None:
        """Download a model, reporting fractional progress per streamed event."""
        request = self._build_request("/api/pull", {"model": model, "stream": True})
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue
                    on_progress(self._pull_progress(line))
        except urllib.error.HTTPError as exc:
            raise OllamaError(f"Ollama HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise OllamaUnavailable("Ollama is not reachable") from exc
        except TimeoutError as exc:
            raise OllamaUnavailable("Ollama request timed out") from exc

    @staticmethod
    def _pull_progress(line: str) -> float:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OllamaError("Invalid pull progress line") from exc
        if not isinstance(event, dict):
            raise OllamaError("Invalid pull progress event")
        if event.get("error"):
            raise OllamaError(str(event["error"]))
        completed = event.get("completed", 0)
        total = event.get("total", 0)
        return completed / total if total else 0.0

    def _build_request(
        self,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> urllib.request.Request:
        data = None
        method = "GET"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            method = "POST"
        return urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers=dict(_HEADERS),
        )

    def _send_json(
        self,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        request = self._build_request(path, payload)
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout_seconds
            ) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            raise OllamaError(f"Ollama HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise OllamaUnavailable("Ollama is not reachable") from exc
        except TimeoutError as exc:
            raise OllamaUnavailable("Ollama request timed out") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise OllamaError("Invalid JSON from Ollama") from exc
