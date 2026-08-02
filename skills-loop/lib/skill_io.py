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


class SkillWriteError(Exception):
    """レビュー結果をファイルへ書く前の検証に失敗した。"""


def _safe_target(rel_path: str) -> Path:
    """`<skill-name>/SKILL.md` のような相対パスを実パスへ解決する。

    範囲外を指していれば例外。子 claude が返した値をそのまま信用しないための関門。
    """
    if not isinstance(rel_path, str) or not rel_path.strip():
        raise SkillWriteError(f"path が空: {rel_path!r}")
    if rel_path.startswith("/") or rel_path.startswith("~"):
        raise SkillWriteError(f"相対パスではない: {rel_path!r}")
    root = HERMES_LITE_ROOT.resolve()
    target = (HERMES_LITE_ROOT / rel_path).resolve()
    if not target.is_relative_to(root):
        raise SkillWriteError(f"{HERMES_LITE_ROOT} の外を指している: {rel_path!r}")
    if target == root:
        raise SkillWriteError(f"ディレクトリ自体は書けない: {rel_path!r}")
    # .archive/ や .usage.json は curator の管理領域なので触らせない
    if any(part.startswith(".") for part in target.relative_to(root).parts):
        raise SkillWriteError(f"隠しパスには書けない: {rel_path!r}")
    return target


def write_skill_files(files: list[dict]) -> list[Path]:
    """[{"path": ..., "content": ...}] を書き込み、書いたパスを返す。

    子 claude は ~/.claude/ 配下へ直接書けない（Claude Code の保護対象）ため、
    レビュー結果は JSON で受け取ってここで書く。全件を検証してから書き始めるので、
    1 件でも不正なら何も書かれない。
    """
    if not isinstance(files, list) or not files:
        raise SkillWriteError("files が空")
    planned: list[tuple[Path, str]] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise SkillWriteError(f"files の要素が dict でない: {entry!r}")
        content = entry.get("content")
        if not isinstance(content, str) or not content.strip():
            raise SkillWriteError(f"content が空: {entry.get('path')!r}")
        planned.append((_safe_target(entry.get("path")), content))

    written: list[Path] = []
    for target, content in planned:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        written.append(target)
    return written
