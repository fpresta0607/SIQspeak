"""Tests for safe Agent Skill metadata discovery and ranking."""
from __future__ import annotations

from pathlib import Path

from siqspeak.enhancement.skills import (
    MAX_AUTOMATIC_CANDIDATES,
    MAX_DESCRIPTION_CHARS,
    MAX_SKILL_BYTES,
    SkillMetadata,
    discover_skills,
    find_explicit_skills,
    rank_skill_candidates,
)


def write_skill(
    base: Path,
    name: str,
    description: str,
    *,
    root: str = ".claude/skills",
    dir_name: str | None = None,
    disable_model_invocation: bool = False,
    body: str = "Body content.",
    frontmatter: str | None = None,
) -> SkillMetadata:
    """Create a skill directory with a SKILL.md and return its expected metadata."""
    skill_dir = base / root / (dir_name or name)
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    if frontmatter is None:
        lines = ["---", f"name: {name}", f"description: {description}"]
        if disable_model_invocation:
            lines.append("disable-model-invocation: true")
        lines.append("---")
        content = "\n".join(lines) + "\n" + body + "\n"
    else:
        content = frontmatter
    skill_file.write_text(content, encoding="utf-8")
    return SkillMetadata(
        name=name,
        description=description,
        path=skill_file,
        disable_model_invocation=disable_model_invocation,
    )


def _names(catalog: tuple[SkillMetadata, ...]) -> list[str]:
    return [meta.name for meta in catalog]


def test_discovers_workspace_and_user_roots(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    write_skill(workspace, "ws-skill", "A workspace skill.", root=".github/skills")
    write_skill(home, "user-skill", "A user skill.", root=".copilot/skills")

    catalog = discover_skills(workspace=workspace, home=home)

    assert set(_names(catalog)) == {"ws-skill", "user-skill"}


def test_home_none_skips_user_skills(tmp_path: Path) -> None:
    # With home=None the global user skill dirs are never scanned, so only the
    # workspace's own skills are returned — no global-skill noise.
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    write_skill(workspace, "ws-skill", "A workspace skill.", root=".github/skills")
    write_skill(home, "user-skill", "A user skill.", root=".copilot/skills")

    catalog = discover_skills(workspace=workspace, home=None)

    assert _names(catalog) == ["ws-skill"]


def test_valid_frontmatter_is_parsed(tmp_path: Path) -> None:
    write_skill(tmp_path, "linting", "  Lint the code.  ")

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert len(catalog) == 1
    meta = catalog[0]
    assert meta.name == "linting"
    assert meta.description == "Lint the code."
    assert meta.disable_model_invocation is False
    assert meta.path.name == "SKILL.md"


def test_missing_skill_file_is_skipped(tmp_path: Path) -> None:
    (tmp_path / ".claude/skills/empty").mkdir(parents=True)

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert catalog == ()


def test_malformed_yaml_is_ignored(tmp_path: Path) -> None:
    broken = "---\nname: [unclosed\ndescription: bad\n---\nbody\n"
    write_skill(tmp_path, "broken", "", frontmatter=broken)

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert catalog == ()


def test_scalar_frontmatter_is_ignored(tmp_path: Path) -> None:
    scalar = "---\njust a string\n---\nbody\n"
    write_skill(tmp_path, "scalar", "", frontmatter=scalar)

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert catalog == ()


def test_missing_closing_delimiter_is_ignored(tmp_path: Path) -> None:
    no_close = "---\nname: nofence\ndescription: d\nstill going and never closes\n"
    write_skill(tmp_path, "nofence", "", frontmatter=no_close)

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert catalog == ()


def test_non_frontmatter_file_is_ignored(tmp_path: Path) -> None:
    plain = "# Just a heading\n\nNo frontmatter here.\n"
    write_skill(tmp_path, "plain", "", frontmatter=plain)

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert catalog == ()


def test_invalid_names_are_ignored(tmp_path: Path) -> None:
    write_skill(tmp_path, "Bad Name!", "Invalid name.", dir_name="bad")
    too_long = "a" * 65
    write_skill(tmp_path, too_long, "Too long.", dir_name="toolong")

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert catalog == ()


def test_name_is_normalized_to_lowercase(tmp_path: Path) -> None:
    write_skill(tmp_path, "MixedCase", "desc", dir_name="mixed")

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert _names(catalog) == ["mixedcase"]


def test_non_string_name_is_ignored(tmp_path: Path) -> None:
    numeric = "---\nname: 123\ndescription: d\n---\nbody\n"
    write_skill(tmp_path, "numeric", "", frontmatter=numeric)

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert catalog == ()


def test_oversized_description_is_truncated(tmp_path: Path) -> None:
    long_desc = "x" * (MAX_DESCRIPTION_CHARS + 500)
    write_skill(tmp_path, "verbose", long_desc)

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert len(catalog[0].description) == MAX_DESCRIPTION_CHARS


def test_non_string_description_becomes_empty(tmp_path: Path) -> None:
    listy = "---\nname: listy\ndescription:\n  - one\n  - two\n---\nbody\n"
    write_skill(tmp_path, "listy", "", frontmatter=listy)

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert catalog[0].description == ""


def test_control_characters_are_stripped(tmp_path: Path) -> None:
    dirty = "---\nname: dirty\ndescription: \"a\\tb\\u0000c\"\n---\nbody\n"
    write_skill(tmp_path, "dirty", "", frontmatter=dirty)

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert catalog[0].description == "abc"


def test_bounded_read_ignores_frontmatter_beyond_limit(tmp_path: Path) -> None:
    padding = "# filler line\n" * ((MAX_SKILL_BYTES // 12) + 100)
    late = f"---\nname: late\ndescription: d\n{padding}---\nbody\n"
    write_skill(tmp_path, "late", "", frontmatter=late)

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert catalog == ()


def test_bounded_read_still_parses_leading_frontmatter(tmp_path: Path) -> None:
    huge_body = "z" * (MAX_SKILL_BYTES * 2)
    write_skill(tmp_path, "leading", "Valid.", body=huge_body)

    catalog = discover_skills(workspace=tmp_path, home=None)

    assert _names(catalog) == ["leading"]


def test_duplicate_names_deduplicate_workspace_first(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    home = tmp_path / "home"
    write_skill(workspace, "dup", "workspace copy")
    write_skill(home, "dup", "user copy")

    catalog = discover_skills(workspace=workspace, home=home)

    assert len(catalog) == 1
    assert catalog[0].description == "workspace copy"


def test_find_explicit_matches_slash_form(tmp_path: Path) -> None:
    write_skill(tmp_path, "deploy", "Deploy the application.")
    catalog = discover_skills(workspace=tmp_path, home=None)

    assert find_explicit_skills("Use /deploy after tests", catalog) == ["deploy"]


def test_find_explicit_matches_dollar_form(tmp_path: Path) -> None:
    write_skill(tmp_path, "deploy", "Deploy the application.")
    catalog = discover_skills(workspace=tmp_path, home=None)

    assert find_explicit_skills("run $deploy now", catalog) == ["deploy"]


def test_find_explicit_matches_natural_name(tmp_path: Path) -> None:
    write_skill(tmp_path, "testing", "Run the tests.")
    catalog = discover_skills(workspace=tmp_path, home=None)

    assert find_explicit_skills("please run testing before merge", catalog) == ["testing"]


def test_find_explicit_no_match_returns_empty(tmp_path: Path) -> None:
    write_skill(tmp_path, "deploy", "Deploy the application.")
    catalog = discover_skills(workspace=tmp_path, home=None)

    assert find_explicit_skills("nothing relevant here", catalog) == []


def test_rank_orders_by_descending_score(tmp_path: Path) -> None:
    write_skill(tmp_path, "alpha", "apple banana cherry")
    write_skill(tmp_path, "beta", "banana")
    catalog = discover_skills(workspace=tmp_path, home=None)

    ranked = rank_skill_candidates("apple banana", catalog)

    assert [meta.name for meta in ranked] == ["alpha", "beta"]


def test_rank_breaks_ties_by_name(tmp_path: Path) -> None:
    write_skill(tmp_path, "zzz", "apple")
    write_skill(tmp_path, "aaa", "apple")
    catalog = discover_skills(workspace=tmp_path, home=None)

    ranked = rank_skill_candidates("apple pie", catalog)

    assert [meta.name for meta in ranked] == ["aaa", "zzz"]


def test_rank_excludes_zero_overlap(tmp_path: Path) -> None:
    write_skill(tmp_path, "match-me", "shared token here")
    write_skill(tmp_path, "no-match", "completely different words")
    catalog = discover_skills(workspace=tmp_path, home=None)

    ranked = rank_skill_candidates("shared token", catalog)

    assert [meta.name for meta in ranked] == ["match-me"]


def test_rank_caps_at_twelve(tmp_path: Path) -> None:
    for index in range(MAX_AUTOMATIC_CANDIDATES + 3):
        name = f"skill-{index:02d}"
        write_skill(tmp_path, name, "match token")
    catalog = discover_skills(workspace=tmp_path, home=None)

    ranked = rank_skill_candidates("match", catalog)

    assert len(ranked) == MAX_AUTOMATIC_CANDIDATES


def test_rank_excludes_disabled_skill(tmp_path: Path) -> None:
    write_skill(tmp_path, "deploy", "deploy production release", disable_model_invocation=True)
    catalog = discover_skills(workspace=tmp_path, home=None)

    assert rank_skill_candidates("deploy production", catalog) == []


def test_lexical_shortlist_contains_debugging_and_testing(tmp_path: Path) -> None:
    write_skill(tmp_path, "systematic-debugging", "debug failing test errors")
    write_skill(tmp_path, "test-driven-development", "write a failing test first")
    write_skill(tmp_path, "deploy-app", "publish releases to production servers")
    catalog = discover_skills(workspace=tmp_path, home=None)

    ranked = rank_skill_candidates("help me debug this failing test", catalog)
    names = [meta.name for meta in ranked]

    assert "systematic-debugging" in names
    assert "test-driven-development" in names
    assert "deploy-app" not in names


def test_explicit_restricted_skill_is_preserved(tmp_path: Path) -> None:
    skill = write_skill(
        tmp_path,
        "deploy",
        "Deploy the application.",
        disable_model_invocation=True,
    )
    catalog = discover_skills(workspace=tmp_path, home=tmp_path)

    explicit = find_explicit_skills("Use /deploy after the tests pass", catalog)

    assert explicit == [skill.name]
    assert rank_skill_candidates("deploy this", catalog) == []
