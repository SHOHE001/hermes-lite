#!/usr/bin/env bash
# Discord webhook へ通知を送るヘルパー。
#
# 使い方:
#   source "$AGENTS_HOME/lib/notify.sh"
#   notify_discord "本文"
#
# DISCORD_WEBHOOK_URL は config/agents.env で設定する。
# 未設定なら stderr に WARN を出して何もしない（ジョブは続行）。

notify_discord() {
  local message="$1"
  if [[ -z "${DISCORD_WEBHOOK_URL:-}" ]]; then
    echo "[notify] WARN: DISCORD_WEBHOOK_URL is empty — skipping Discord post" >&2
    return 0
  fi
  # Discord の content は最大 2000 文字。安全のため 1900 で切る。
  if (( ${#message} > 1900 )); then
    message="${message:0:1900}…(truncated)"
  fi
  # jq で JSON を安全に組み立てる
  local payload
  payload=$(jq -n --arg c "$message" '{content: $c}')
  # 失敗してもジョブは止めない
  curl -fsS -X POST -H "Content-Type: application/json" \
    -d "$payload" "$DISCORD_WEBHOOK_URL" >/dev/null 2>&1 \
    || echo "[notify] WARN: Discord post failed" >&2
}
