"""Tests for few-shot style-example selection from the user's local history."""
from __future__ import annotations

import json
from pathlib import Path

from siqspeak.enhancement.personalization import select_style_examples


def _write_session(home: Path, name: str, lines: list[str]) -> None:
    project_dir = home / ".claude" / "projects" / "proj"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / name).write_text("\n".join(lines), encoding="utf-8")


def _user_line(content: object) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": content}})


def test_extracts_user_text_from_string_content(tmp_path: Path) -> None:
    _write_session(
        tmp_path,
        "s.jsonl",
        [_user_line("add a login endpoint with jwt authentication")],
    )

    result = select_style_examples("add login", tmp_path, None)

    assert result == ("add a login endpoint with jwt authentication",)


def test_extracts_user_text_from_block_list_content(tmp_path: Path) -> None:
    content = [
        {"type": "text", "text": "please refactor the payment service module"},
        {"type": "image", "source": "ignored"},
    ]
    _write_session(tmp_path, "s.jsonl", [_user_line(content)])

    result = select_style_examples("refactor payment", tmp_path, None)

    assert result == ("please refactor the payment service module",)


def test_message_role_user_without_type_is_included(tmp_path: Path) -> None:
    line = json.dumps({"message": {"role": "user", "content": "wire up the settings panel toggle"}})
    _write_session(tmp_path, "s.jsonl", [line])

    result = select_style_examples("settings panel", tmp_path, None)

    assert result == ("wire up the settings panel toggle",)


def test_non_user_and_assistant_lines_are_skipped(tmp_path: Path) -> None:
    lines = [
        json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "here you go now"}}),
        json.dumps({"type": "summary", "content": "session summary text goes here"}),
    ]
    _write_session(tmp_path, "s.jsonl", lines)

    assert select_style_examples("anything", tmp_path, None) == ()


def test_malformed_lines_and_non_json_files_are_skipped(tmp_path: Path) -> None:
    _write_session(
        tmp_path,
        "s.jsonl",
        [
            "this is not json at all {{{",
            "",
            "12345",  # valid json, not a dict
            _user_line("build the transcription worker retry loop"),
        ],
    )

    result = select_style_examples("transcription worker", tmp_path, None)

    assert result == ("build the transcription worker retry loop",)


def test_ranking_prefers_highest_token_overlap(tmp_path: Path) -> None:
    _write_session(
        tmp_path,
        "s.jsonl",
        [
            _user_line("add a login endpoint with jwt authentication tokens"),
            _user_line("refactor the database migration helper scripts entirely"),
            _user_line("write documentation for the release process steps"),
        ],
    )

    result = select_style_examples("add a login endpoint", tmp_path, None, limit=1)

    assert result == ("add a login endpoint with jwt authentication tokens",)


def test_ties_break_on_shorter_example(tmp_path: Path) -> None:
    _write_session(
        tmp_path,
        "s.jsonl",
        [
            _user_line("update the cache and also update many other unrelated things here now"),
            _user_line("update the cache layer settings"),
        ],
    )

    result = select_style_examples("update cache", tmp_path, None, limit=1)

    assert result == ("update the cache layer settings",)


def test_length_empty_code_and_dedup_filters(tmp_path: Path) -> None:
    long_paste = "word " * 200  # > 400 chars after collapse
    _write_session(
        tmp_path,
        "s.jsonl",
        [
            _user_line("too short"),  # < 20 chars
            _user_line(""),  # empty
            _user_line(long_paste),  # giant paste
            _user_line("def handler(): return {value: compute()}"),  # code dump
            _user_line("please add retry logic to the upload flow"),
            _user_line("please add retry logic to the upload flow"),  # duplicate
        ],
    )

    result = select_style_examples("retry upload", tmp_path, None, limit=5)

    assert result == ("please add retry logic to the upload flow",)


def test_limit_is_respected(tmp_path: Path) -> None:
    _write_session(
        tmp_path,
        "s.jsonl",
        [_user_line(f"implement feature number {word} for the dashboard view")
         for word in ("alpha", "bravo", "charlie", "delta", "echo")],
    )

    result = select_style_examples("implement feature dashboard", tmp_path, None, limit=2)

    assert len(result) == 2


def test_empty_pool_returns_empty_tuple(tmp_path: Path) -> None:
    assert select_style_examples("anything at all", tmp_path, tmp_path) == ()
    assert select_style_examples("anything at all", None, None) == ()


def test_plan_objective_goal_line_is_included(tmp_path: Path) -> None:
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "feature.md").write_text(
        "# Big Feature Plan\n\n**Goal:** ship the streaming transcription pipeline\n",
        encoding="utf-8",
    )

    result = select_style_examples("streaming transcription", None, tmp_path)

    assert result == ("ship the streaming transcription pipeline",)


def test_plan_first_paragraph_used_when_no_goal(tmp_path: Path) -> None:
    plans = tmp_path / "docs" / "plans"
    plans.mkdir(parents=True)
    (plans / "feature.md").write_text(
        "# Heading Only\n## Sub Heading\nresolve the overlay flicker on mode switch\n",
        encoding="utf-8",
    )

    result = select_style_examples("overlay flicker", None, tmp_path)

    assert result == ("resolve the overlay flicker on mode switch",)
