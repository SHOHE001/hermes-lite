"""`/status` — gloop の現在状態を表示する。

module top は stdlib のみ import する（glob / pid 確認 / json parse は
すべて関数内 = 実行時に閉じ込め、import 時 IO なしを徹底する）。

読み取り contract（loop 側の内部形式変更で壊れ得る密結合をこの3関数に閉じる）:

| ファイル | 参照フィールド | 欠損/破損時の表示 |
|---|---|---|
| `features/.loop/state.json` | `cycle`, `recent_cycles[-1].pause_reason` | cycle=N/A / 直近 pause=不明 |
| `features/.loop/tmux-state.json` | `watcher_pid`, `worker_pane_id` | watcher=unknown |
| `logs/*/*.json`（mtime 降順・スキーマガード後の最新） | 親ディレクトリ名, mtime, `result` | 直近ジョブ=N/A |
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .types import CommandContext


@dataclass(frozen=True)
class LoopStateStatus:
    cycle: int | None
    pause_reason: str | None


@dataclass(frozen=True)
class TmuxStatus:
    watcher_alive: bool | None
    worker_pane_id: str | None
    watcher_pid: int | None


@dataclass(frozen=True)
class LatestJobStatus:
    name: str
    at: str
    result_summary: str


def _read_loop_state(hermes_home: Path) -> LoopStateStatus:
    path = hermes_home / "features" / ".loop" / "state.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    cycle = data.get("cycle")
    pause_reason = None
    recent_cycles = data.get("recent_cycles")
    if isinstance(recent_cycles, list) and recent_cycles:
        last = recent_cycles[-1]
        if isinstance(last, dict):
            pause_reason = last.get("pause_reason")
    return LoopStateStatus(cycle=cycle, pause_reason=pause_reason)


def _read_tmux_state(hermes_home: Path) -> TmuxStatus:
    path = hermes_home / "features" / ".loop" / "tmux-state.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    pid = data.get("watcher_pid")
    worker_pane_id = data.get("worker_pane_id")
    watcher_alive: bool | None = None
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
            watcher_alive = True
        except ProcessLookupError:
            watcher_alive = False
        except PermissionError:
            watcher_alive = True
    return TmuxStatus(
        watcher_alive=watcher_alive,
        worker_pane_id=worker_pane_id,
        watcher_pid=pid if isinstance(pid, int) else None,
    )


def _latest_job_log(hermes_home: Path) -> LatestJobStatus | None:
    logs_dir = hermes_home / "logs"
    candidates = sorted(
        logs_dir.glob("*/*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "result" not in data:
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        result = data.get("result")
        summary = str(result)[:80] if result is not None else ""
        return LatestJobStatus(
            name=path.parent.name,
            at=mtime.isoformat(timespec="seconds"),
            result_summary=summary,
        )
    return None


def status_handler(ctx: CommandContext, args: str) -> str:
    lines = ["📊 gloop status"]

    try:
        loop_state = _read_loop_state(ctx.hermes_home)
        cycle_text = loop_state.cycle if loop_state.cycle is not None else "N/A"
        pause_text = loop_state.pause_reason if loop_state.pause_reason else "なし"
    except Exception:
        cycle_text = "N/A"
        pause_text = "不明"
    lines.append(f"• cycle: {cycle_text}")
    lines.append(f"• 直近 pause: {pause_text}")

    try:
        tmux_state = _read_tmux_state(ctx.hermes_home)
        if tmux_state.watcher_alive is True:
            watcher_text = (
                f"alive (pid {tmux_state.watcher_pid})"
                if tmux_state.watcher_pid is not None
                else "alive"
            )
        elif tmux_state.watcher_alive is False:
            watcher_text = "dead"
        else:
            watcher_text = "unknown"
    except Exception:
        watcher_text = "unknown"
    lines.append(f"• watcher: {watcher_text}")

    try:
        latest = _latest_job_log(ctx.hermes_home)
        if latest is not None:
            job_text = f"{latest.name} ({latest.at}) — {latest.result_summary}"
        else:
            job_text = "N/A"
    except Exception:
        job_text = "N/A"
    lines.append(f"• 直近ジョブ: {job_text}")

    return "\n".join(lines)
