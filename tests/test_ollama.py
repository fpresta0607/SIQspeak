"""Tests for the loopback-only Ollama HTTP client.

All network I/O is exercised through a mocked ``urllib.request.urlopen`` so no
real Ollama server is required.
"""
from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

from siqspeak.enhancement.ollama import (
    OllamaClient,
    OllamaError,
    OllamaUnavailable,
)


class FakeResponse:
    """Minimal context-manager stand-in for an ``http.client.HTTPResponse``."""

    def __init__(
        self,
        payload: object | None = None,
        *,
        raw: bytes | None = None,
        lines: list[bytes] | None = None,
    ) -> None:
        if raw is not None:
            self._body = raw
        elif payload is not None:
            self._body = json.dumps(payload).encode("utf-8")
        else:
            self._body = b""
        self._lines = lines or []

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body

    def __iter__(self) -> Any:
        return iter(self._lines)


def _patch(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    monkeypatch.setattr("urllib.request.urlopen", handler)


# --- construction / loopback enforcement -----------------------------------


def test_default_base_url_is_loopback() -> None:
    client = OllamaClient()
    assert client.base_url == "http://127.0.0.1:11434"
    assert client.timeout_seconds == 120.0


def test_localhost_base_url_allowed() -> None:
    assert OllamaClient(base_url="http://localhost:11434").base_url.endswith("11434")


def test_non_loopback_base_url_rejected() -> None:
    with pytest.raises(OllamaError):
        OllamaClient(base_url="http://192.168.1.10:11434")


def test_ollama_unavailable_is_ollama_error() -> None:
    assert issubclass(OllamaUnavailable, OllamaError)


# --- availability / list_models --------------------------------------------


def test_is_available_true_when_tags_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        assert request.full_url.endswith("/api/tags")
        assert request.get_method() == "GET"
        return FakeResponse(payload={"models": [{"name": "qwen3.5:2b"}]})

    _patch(monkeypatch, handler)
    assert OllamaClient().is_available() is True


def test_is_available_false_when_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        raise urllib.error.URLError("connection refused")

    _patch(monkeypatch, handler)
    assert OllamaClient().is_available() is False


def test_list_models_returns_names(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(
            payload={"models": [{"name": "qwen3.5:2b"}, {"name": "llama3:latest"}]}
        )

    _patch(monkeypatch, handler)
    assert OllamaClient().list_models() == ("qwen3.5:2b", "llama3:latest")


def test_list_models_skips_malformed_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(payload={"models": [{"name": "a"}, {}, "bogus", 5]})

    _patch(monkeypatch, handler)
    assert OllamaClient().list_models() == ("a",)


def test_list_models_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        raise urllib.error.HTTPError(request.full_url, 500, "boom", {}, None)  # type: ignore[arg-type]

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaError):
        OllamaClient().list_models()


def test_list_models_raises_on_invalid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(raw=b"not json")

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaError):
        OllamaClient().list_models()


def test_list_models_raises_when_shape_wrong(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(payload={"unexpected": True})

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaError):
        OllamaClient().list_models()


# --- has_model --------------------------------------------------------------


def test_has_model_exact_match(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(payload={"models": [{"name": "qwen3.5:2b"}]})

    _patch(monkeypatch, handler)
    assert OllamaClient().has_model("qwen3.5:2b") is True


def test_has_model_matches_latest_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(payload={"models": [{"name": "llama3:latest"}]})

    _patch(monkeypatch, handler)
    assert OllamaClient().has_model("llama3") is True


def test_has_model_false_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(payload={"models": [{"name": "qwen3.5:2b"}]})

    _patch(monkeypatch, handler)
    assert OllamaClient().has_model("mistral") is False


# --- chat_structured --------------------------------------------------------


def test_chat_structured_posts_expected_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["content_type"] = request.get_header("Content-type")
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse(
            payload={"message": {"content": json.dumps({"objective": "ship"})}}
        )

    _patch(monkeypatch, handler)
    schema = {"type": "object"}
    result = OllamaClient(timeout_seconds=12.0).chat_structured(
        "qwen3.5:2b",
        [{"role": "user", "content": "hi"}],
        schema,
    )

    assert result == {"objective": "ship"}
    assert captured["url"].endswith("/api/chat")
    assert captured["method"] == "POST"
    assert captured["content_type"] == "application/json"
    assert captured["timeout"] == 12.0
    body = captured["body"]
    assert body["think"] is False
    assert body["stream"] is False
    assert body["keep_alive"] == "10m"
    assert body["options"]["temperature"] == 0
    assert body["format"] == schema
    assert body["model"] == "qwen3.5:2b"
    assert body["messages"] == [{"role": "user", "content": "hi"}]


def test_chat_structured_raises_on_invalid_content_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(payload={"message": {"content": "not-json"}})

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaError):
        OllamaClient().chat_structured("m", [], {})


def test_chat_structured_raises_when_content_not_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(payload={"message": {"content": json.dumps([1, 2])}})

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaError):
        OllamaClient().chat_structured("m", [], {})


def test_chat_structured_raises_when_message_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(payload={"unexpected": True})

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaError):
        OllamaClient().chat_structured("m", [], {})


def test_chat_structured_maps_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        raise urllib.error.HTTPError(request.full_url, 404, "no", {}, None)  # type: ignore[arg-type]

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaError):
        OllamaClient().chat_structured("m", [], {})


def test_chat_structured_maps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        raise TimeoutError("slow")

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaUnavailable):
        OllamaClient().chat_structured("m", [], {})


def test_chat_structured_maps_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        raise urllib.error.URLError("refused")

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaUnavailable):
        OllamaClient().chat_structured("m", [], {})


# --- pull_model -------------------------------------------------------------


def test_pull_model_reports_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    lines = [
        b'{"status": "pulling manifest"}\n',
        b'{"status": "downloading", "completed": 25, "total": 100}\n',
        b'{"status": "downloading", "completed": 100, "total": 100}\n',
        b'{"status": "success"}\n',
    ]

    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(lines=lines)

    _patch(monkeypatch, handler)

    seen: list[float] = []
    OllamaClient().pull_model("qwen3.5:2b", seen.append)

    assert captured["url"].endswith("/api/pull")
    assert captured["method"] == "POST"
    assert captured["body"]["model"] == "qwen3.5:2b"
    assert seen == [0.0, 0.25, 1.0, 0.0]


def test_pull_model_zero_total_yields_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [b'{"status": "starting", "completed": 5, "total": 0}\n']

    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(lines=lines)

    _patch(monkeypatch, handler)
    seen: list[float] = []
    OllamaClient().pull_model("m", seen.append)
    assert seen == [0.0]


def test_pull_model_skips_blank_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [b"\n", b'{"completed": 50, "total": 100}\n', b"   \n"]

    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(lines=lines)

    _patch(monkeypatch, handler)
    seen: list[float] = []
    OllamaClient().pull_model("m", seen.append)
    assert seen == [0.5]


def test_pull_model_raises_on_error_line(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [b'{"error": "model not found"}\n']

    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(lines=lines)

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaError):
        OllamaClient().pull_model("m", lambda _: None)


def test_pull_model_raises_on_invalid_line(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [b"not json\n"]

    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        return FakeResponse(lines=lines)

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaError):
        OllamaClient().pull_model("m", lambda _: None)


def test_pull_model_maps_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        raise urllib.error.URLError("refused")

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaUnavailable):
        OllamaClient().pull_model("m", lambda _: None)


def test_pull_model_maps_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        raise TimeoutError("slow")

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaUnavailable):
        OllamaClient().pull_model("m", lambda _: None)


def test_pull_model_maps_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: Any, timeout: float | None = None) -> FakeResponse:
        raise urllib.error.HTTPError(request.full_url, 500, "boom", {}, None)  # type: ignore[arg-type]

    _patch(monkeypatch, handler)
    with pytest.raises(OllamaError):
        OllamaClient().pull_model("m", lambda _: None)
