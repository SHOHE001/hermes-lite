"""SKILL.md frontmatter の最小限パース (PyYAML 不要)。"""
from __future__ import annotations

import re
from pathlib import Path

HERMES_LITE_ROOT = Path.home() / ".claude" / "skills" / "hermes-lite"
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def extract_frontmatter(text: str) -> str | None:
    m = FRONTMATTER_RE.match(text)
    return m.group(1) if m else None


def is_agent_created(skill_md_path: Path) -> bool:
    """frontmatter に metadata.hermes_lite.agent_created: true が含まれるか。

    PyYAML を入れず単純な文字列マッチで判定 (フォーマット崩れには寛容)。
    """
    try:
        text = skill_md_path.read_text(errors="replace")
    except OSError:
        return False
    fm = extract_frontmatter(text)
    if fm is None:
        return False
    return "hermes_lite" in fm and re.search(r"agent_created\s*:\s*true", fm, re.IGNORECASE) is not None


def list_managed_skills() -> list[Path]:
    """~/.claude/skills/hermes-lite/<name>/SKILL.md のうち agent_created なものを返す。

    .archive/ や .で始まるディレクトリ・ファイル (sidecar 含む) は除外する。
    """
    if not HERMES_LITE_ROOT.exists():
        return []
    out: list[Path] = []
    for child in HERMES_LITE_ROOT.iterdir():
        if child.name.startswith("."):
            continue
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if skill_md.exists() and is_agent_created(skill_md):
            out.append(skill_md)
    return out


def skill_name_from_path(skill_md_path: Path) -> str:
    return skill_md_path.parent.name
