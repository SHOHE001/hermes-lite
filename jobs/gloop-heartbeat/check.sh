#!/usr/bin/env bash
# gloop watcher 生死監視。hourly で叩く。
#
# 判定:
#   watcher_pid が生きていない かつ worker_pane_id が tmux 上に残っている
#     → gloop が中途半端に死んでいる状態 → Discord 通知
#   watcher_pid が生きていない かつ worker_pane も無い
#     → 意図的に停止された状態 → 通知しない
#
# 通知は 24h に 1 回だけ (spam 防止)。状態は features/.loop/heartbeat-state.json に保持。
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/hermes-lite}"
TMUX_STATE="$HERMES_HOME/features/.loop/tmux-state.json"
HEARTBEAT_STATE="$HERMES_HOME/features/.loop/heartbeat-state.json"

# .env から DISCORD_WEBHOOK_URL を読む
if [[ -f "$HERMES_HOME/.env" ]]; then
  # shellcheck disable=SC1090
  source "$HERMES_HOME/.env"
fi
# shellcheck disable=SC1090
source "$HERMES_HOME/lib/notify.sh"

if [[ ! -f "$TMUX_STATE" ]]; then
  # gloop 未起動 — 何もしない
  exit 0
fi

watcher_pid=$(jq -r '.watcher_pid // empty' "$TMUX_STATE")
worker_pane_id=$(jq -r '.worker_pane_id // empty' "$TMUX_STATE")

# watcher が生きているか
watcher_alive=0
if [[ -n "$watcher_pid" ]] && kill -0 "$watcher_pid" 2>/dev/null; then
  watcher_alive=1
fi

# worker pane が tmux 上に存在するか
worker_pane_exists=0
if [[ -n "$worker_pane_id" ]] && tmux list-panes -a -F '#{pane_id}' 2>/dev/null | grep -qFx "$worker_pane_id"; then
  worker_pane_exists=1
fi

if (( watcher_alive == 1 )); then
  jq -n '{last_alert_at: null, last_state: "alive"}' > "$HEARTBEAT_STATE"
  exit 0
fi

if (( worker_pane_exists == 0 )); then
  jq -n '{last_alert_at: null, last_state: "stopped"}' > "$HEARTBEAT_STATE"
  exit 0
fi

# 異常: watcher 死亡 but worker pane 残存
last_alert_at=""
if [[ -f "$HEARTBEAT_STATE" ]]; then
  last_alert_at=$(jq -r '.last_alert_at // empty' "$HEARTBEAT_STATE")
fi

should_notify=1
if [[ -n "$last_alert_at" ]]; then
  now_epoch=$(date +%s)
  last_epoch=$(date -d "$last_alert_at" +%s 2>/dev/null || echo 0)
  if (( now_epoch - last_epoch < 86400 )); then
    should_notify=0
  fi
fi

if (( should_notify == 1 )); then
  msg="[gloop-heartbeat] watcher dead (watcher_pid=${watcher_pid:-null}) but worker pane $worker_pane_id still alive. /gloop を再投入して復活させてください. cf. docs/runbook-gloop.md"
  notify_discord "$msg"
  now_iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  jq -n --arg t "$now_iso" '{last_alert_at: $t, last_state: "watcher-dead"}' > "$HEARTBEAT_STATE"
fi
