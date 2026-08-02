#!/usr/bin/env python3
"""hermes-lite Curator (LLM 不使用、自動状態遷移のみ)。

本家 NousResearch/hermes-agent agent/curator.py :: apply_automatic_transitions の踏襲。
7 日サイクル想定 (cron で起動)。

State transitions:
  - last_used_at が 30 日以内 → active
  - 31 〜 90 日 → stale
  - 91 日以上 → archived (~/.claude/skills/hermes-lite/<name>/ を .archive/<name>/ に mv)
  - 一度 stale でも使われたら active に戻る (reactivation)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import skill_io  # noqa: E402
import usage_store  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
RUNS_DIR = STATE_DIR / "runs"
CURATOR_STATE = STATE_DIR / "curator_state.json"
ARCHIVE_DIR = skill_io.HERMES_LITE_ROOT / ".archive"
USAGE_TRACKER = ROOT / "bin" / "usage-tracker.py"

STALE_DAYS = 30
ARCHIVE_DAYS = 90
# state/runs/ の保持期間。削除処理が無く 817 ファイル・3.4MB まで溜まっていた。
RUNS_RETENTION_DAYS = ARCHIVE_DAYS


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _classify(last_used_at: str | None, fallback: str | None) -> str:
    ts = _parse_iso(last_used_at) or _parse_iso(fallback)
    if ts is None:
        return "active"
    age = _now() - ts
    if age >= timedelta(days=ARCHIVE_DAYS):
        return "archived"
    if age >= timedelta(days=STALE_DAYS):
        return "stale"
    return "active"


def _previous_run_at() -> datetime | None:
    if not CURATOR_STATE.exists():
        return None
    try:
        return _parse_iso(json.loads(CURATOR_STATE.read_text()).get("last_run_at"))
    except (OSError, json.JSONDecodeError):
        return None


def collect_on_stop_health(since: datetime | None) -> dict:
    """state/runs/on-stop-*.json を走査してレビューの成立率を出す。

    Stop hook は「対話セッションが終わったとき」という不定期トリガーなので、
    最終実行が何時間前かでは健康状態を測れない（作業していない日は動かない）。
    実行があったときに成立しているかどうかで見る。

    2026-08-02 以前の記録には ok フィールドが無い。当時は exit 0 なら成功として
    扱っていたが、実際には 810 件すべてレビューが成立していなかった。
    判定できない記録は失敗側に数える。
    """
    files = sorted(RUNS_DIR.glob("on-stop-*.json"))
    total = 0
    failed = 0
    last_run_at: datetime | None = None
    reasons: dict[str, int] = {}

    for f in files:
        try:
            rec = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        ran_at = _parse_iso(rec.get("ran_at"))
        if since is not None and ran_at is not None and ran_at < since:
            continue
        total += 1
        if ran_at is not None and (last_run_at is None or ran_at > last_run_at):
            last_run_at = ran_at

        ok = rec.get("ok")
        if ok is None:
            failed += 1
            reasons["ok フィールドの無い旧記録"] = reasons.get("ok フィールドの無い旧記録", 0) + 1
        elif not ok:
            failed += 1
            key = str(rec.get("parse_error") or rec.get("apply_error") or "理由不明")[:60]
            reasons[key] = reasons.get(key, 0) + 1

    return {
        "window_since": since.isoformat(timespec="seconds") if since else None,
        "run_count": total,
        "fail_count": failed,
        "fail_rate": round(failed / total, 3) if total else None,
        "last_run_at": last_run_at.isoformat(timespec="seconds") if last_run_at else None,
        "top_reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])[:3]),
    }


def prune_runs(dry_run: bool) -> int:
    """保持期間を過ぎた run 記録を削除し、削除件数を返す。"""
    if not RUNS_DIR.exists():
        return 0
    cutoff = _now() - timedelta(days=RUNS_RETENTION_DAYS)
    removed = 0
    for f in RUNS_DIR.glob("*.json"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        if not dry_run:
            try:
                f.unlink()
            except OSError:
                continue
        removed += 1
    return removed


def run(dry_run: bool) -> dict:
    if not dry_run:
        subprocess.run([sys.executable, str(USAGE_TRACKER)], check=False)

    data = usage_store.load()
    managed_paths = {skill_io.skill_name_from_path(p): p for p in skill_io.list_managed_skills()}

    transitions: list[dict] = []
    archives: list[dict] = []

    for name, skill_md in managed_paths.items():
        entry = data.get(name, {})
        old_state = entry.get("state", "active")
        new_state = _classify(entry.get("last_used_at"), entry.get("created_at"))
        if new_state != old_state:
            transitions.append({"name": name, "from": old_state, "to": new_state})
        if new_state == "archived":
            archives.append(
                {"name": name, "from": str(skill_md.parent), "to": str(ARCHIVE_DIR / name)}
            )
        if not dry_run:
            entry["state"] = new_state
            data[name] = entry

    if not dry_run:
        usage_store.save(data)
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        for arch in archives:
            src = Path(arch["from"])
            dst = Path(arch["to"])
            if dst.exists():
                dst = dst.with_name(dst.name + "-" + _now().strftime("%Y%m%d%H%M%S"))
                arch["to"] = str(dst)
            try:
                shutil.move(str(src), str(dst))
            except OSError as e:
                arch["error"] = str(e)

    return {
        "ran_at": _now().isoformat(timespec="seconds"),
        "dry_run": dry_run,
        "managed_count": len(managed_paths),
        "transitions": transitions,
        "archives": archives,
        # 生成側 (Stop hook) が機能しているかを記録する。ここが見えていなかったため、
        # skills-loop は 6/20 から一度も成功しないまま、7/29 に hook が外れたことにも
        # 誰も気づかなかった (docs/audit-2026-08-02.md A-3)。
        "on_stop_health": collect_on_stop_health(_previous_run_at()),
        "pruned_runs": prune_runs(dry_run),
    }


def update_state_file(summary: dict) -> None:
    state: dict = {}
    if CURATOR_STATE.exists():
        try:
            state = json.loads(CURATOR_STATE.read_text())
        except json.JSONDecodeError:
            pass
    state["last_run_at"] = summary["ran_at"]
    state["run_count"] = state.get("run_count", 0) + 1
    state["last_run_summary"] = {
        "transitions": len(summary["transitions"]),
        "archives": len(summary["archives"]),
        "managed_count": summary["managed_count"],
        "pruned_runs": summary.get("pruned_runs", 0),
    }
    # jobwatch-review が毎朝ここを読む
    state["on_stop_health"] = summary["on_stop_health"]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CURATOR_STATE.write_text(json.dumps(state, indent=2))


def write_run_log(summary: dict) -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = summary["ran_at"].replace(":", "").replace("-", "")
    path = RUNS_DIR / f"curator-{ts}.json"
    path.write_text(json.dumps(summary, indent=2))
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    summary = run(dry_run=args.dry_run)

    h = summary["on_stop_health"]
    print(
        f"[curator] managed={summary['managed_count']} "
        f"transitions={len(summary['transitions'])} "
        f"archives={len(summary['archives'])} "
        f"pruned={summary['pruned_runs']} dry_run={args.dry_run}"
    )
    print(
        f"[curator] on-stop: runs={h['run_count']} fails={h['fail_count']} "
        f"rate={h['fail_rate']} last={h['last_run_at']}"
    )
    for reason, n in h["top_reasons"].items():
        print(f"  fail reason x{n}: {reason}")
    for tr in summary["transitions"]:
        print(f"  state: {tr['name']}: {tr['from']} -> {tr['to']}")
    for ar in summary["archives"]:
        print(f"  archive: {ar['name']} -> {ar['to']}")

    if not args.dry_run:
        update_state_file(summary)
        log = write_run_log(summary)
        print(f"[curator] log: {log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
