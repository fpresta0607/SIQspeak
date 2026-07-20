"""Tests for the enhancement orchestration service and its lossless fallbacks."""
from __future__ import annotations

from pathlib import Path

from siqspeak.enhancement.context import ContextSource
from siqspeak.enhancement.ollama import OllamaError
from siqspeak.enhancement.prompt import EnhancementResult
from siqspeak.enhancement.service import enhance_request
from siqspeak.enhancement.skills import SkillMetadata

RAW = "publish the release to production and run the tests"


def _meta(name: str, description: str, *, disabled: bool = False) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=description,
        path=Path(name),
        disable_model_invocation=disabled,
    )


def _catalog() -> tuple[SkillMetadata, ...]:
    return (
        _meta("systematic-debugging", "debug failing tests and errors"),
        _meta("test-driven-development", "write a failing tests first"),
        _meta("deploy", "publish releases to production servers", disabled=True),
    )


def _valid_reply(selected: list[str]) -> dict[str, object]:
    return {
        "end_state": "The release is live and the suite is green",
        "sources_of_truth": ["deploy/release.md"],
        "hard_constraints": ["Run the suite before publishing"],
        "acceptance_criteria": ["All green"],
        "verification": ["pytest"],
        "selected_skills": selected,
    }


class FakeClient:
    """Configurable stand-in for the loopback Ollama client."""

    def __init__(
        self,
        *,
        available: bool = True,
        model_present: bool = True,
        reply: dict[str, object] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.available = available
        self.model_present = model_present
        self.reply = reply
        self.raises = raises
        self.chat_calls = 0
        self.last_messages: list[dict[str, str]] = []

    def is_available(self) -> bool:
        return self.available

    def has_model(self, model: str) -> bool:
        return self.model_present

    def chat_structured(
        self,
        model: str,
        messages: list[dict[str, str]],
        schema: dict[str, object],
    ) -> dict[str, object]:
        self.chat_calls += 1
        self.last_messages = messages
        if self.raises is not None:
            raise self.raises
        assert self.reply is not None
        return self.reply


class ExplodingClient:
    """Fails loudly if any method is touched — proves the disabled short-circuit."""

    def is_available(self) -> bool:  # pragma: no cover - must never run
        raise AssertionError("Ollama must not be contacted when disabled")

    def has_model(self, model: str) -> bool:  # pragma: no cover - must never run
        raise AssertionError("Ollama must not be contacted when disabled")

    def chat_structured(self, *args: object, **kwargs: object) -> dict[str, object]:  # pragma: no cover
        raise AssertionError("Ollama must not be contacted when disabled")


def _call(
    client: object,
    *,
    enabled: bool = True,
    raw: str = RAW,
    context: tuple[ContextSource, ...] = (),
) -> EnhancementResult:
    return enhance_request(
        raw,
        enabled=enabled,
        model="qwen3.5:2b",
        client=client,  # type: ignore[arg-type]
        catalog=_catalog(),
        context=context,
    )


def test_disabled_returns_raw_without_calling_ollama() -> None:
    result = _call(ExplodingClient(), enabled=False)

    assert result == EnhancementResult(RAW, RAW, (), False, None)


def test_unavailable_ollama_returns_raw() -> None:
    result = _call(FakeClient(available=False))

    assert result.final_text == RAW
    assert result.enhanced is False
    assert result.error is not None


def test_missing_model_returns_raw() -> None:
    result = _call(FakeClient(model_present=False))

    assert result.final_text == RAW
    assert result.enhanced is False
    assert result.error is not None


def test_malformed_response_returns_raw() -> None:
    client = FakeClient(reply={"objective": "only this field"})

    result = _call(client)

    assert result.final_text == RAW
    assert result.enhanced is False
    assert result.error is not None


def test_chat_exception_returns_raw() -> None:
    client = FakeClient(raises=OllamaError("boom"))

    result = _call(client)

    assert result.final_text == RAW
    assert result.enhanced is False
    assert result.error is not None


def test_explicit_skill_always_included() -> None:
    client = FakeClient(reply=_valid_reply(selected=[]))

    result = enhance_request(
        "run /deploy after the suite passes",
        enabled=True,
        model="qwen3.5:2b",
        client=client,  # type: ignore[arg-type]
        catalog=_catalog(),
    )

    assert result.enhanced is True
    assert "deploy" in result.selected_skills
    assert "Use these skills if available:\n- deploy" in result.final_text


def test_semantic_choices_are_catalog_validated() -> None:
    client = FakeClient(
        reply=_valid_reply(selected=["systematic-debugging", "made-up-skill"])
    )

    result = _call(client, raw="help me debug failing tests")

    assert result.enhanced is True
    assert result.selected_skills == ("systematic-debugging",)


def test_restricted_automatic_skill_is_removed() -> None:
    # The model tries to auto-select a restricted skill the user never named.
    client = FakeClient(reply=_valid_reply(selected=["deploy"]))

    result = _call(client)

    assert result.enhanced is True
    assert "deploy" not in result.selected_skills


def test_successful_enhancement_reports_enhanced() -> None:
    client = FakeClient(reply=_valid_reply(selected=["systematic-debugging"]))

    result = _call(client, raw="help me debug failing tests")

    assert result.enhanced is True
    assert result.error is None
    assert result.raw_text == "help me debug failing tests"
    assert result.final_text.startswith("Original request:\nhelp me debug failing tests")
    assert "End-state behavior:\nThe release is live and the suite is green" in result.final_text
    assert client.chat_calls == 1


_CONTEXT = (
    ContextSource(label="CLAUDE.md", text="Always use parameterized SQL."),
    ContextSource(label="docs/plans/login.md", text="Add a login endpoint."),
)


def _all_message_text(messages: list[dict[str, str]]) -> str:
    return "\n".join(message["content"] for message in messages)


def test_context_text_appears_in_messages() -> None:
    client = FakeClient(reply=_valid_reply(selected=[]))

    result = _call(client, raw="add login", context=_CONTEXT)

    assert result.enhanced is True
    sent = _all_message_text(client.last_messages)
    assert "CLAUDE.md" in sent
    assert "Always use parameterized SQL." in sent
    assert "docs/plans/login.md" in sent
    assert "Add a login endpoint." in sent


def test_context_does_not_break_success() -> None:
    client = FakeClient(reply=_valid_reply(selected=["systematic-debugging"]))

    result = _call(client, raw="help me debug failing tests", context=_CONTEXT)

    assert result.enhanced is True
    assert result.error is None


def test_disabled_returns_raw_even_with_context() -> None:
    result = _call(ExplodingClient(), enabled=False, context=_CONTEXT)

    assert result == EnhancementResult(RAW, RAW, (), False, None)


def test_unavailable_ollama_returns_raw_with_context() -> None:
    result = _call(FakeClient(available=False), context=_CONTEXT)

    assert result.final_text == RAW
    assert result.enhanced is False
    assert result.error is not None


def test_missing_model_returns_raw_with_context() -> None:
    result = _call(FakeClient(model_present=False), context=_CONTEXT)

    assert result.final_text == RAW
    assert result.enhanced is False
    assert result.error is not None


def test_malformed_response_returns_raw_with_context() -> None:
    result = _call(FakeClient(reply={"objective": "only this field"}), context=_CONTEXT)

    assert result.final_text == RAW
    assert result.enhanced is False
    assert result.error is not None


def test_chat_exception_returns_raw_with_context() -> None:
    result = _call(FakeClient(raises=OllamaError("boom")), context=_CONTEXT)

    assert result.final_text == RAW
    assert result.enhanced is False
    assert result.error is not None
