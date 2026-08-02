#!/usr/bin/env bash
# Discord webhook へ通知を送るヘルパー。
#
# 使い方:
#   source "$AGENTS_HOME/lib/notify.sh"
#   notify_discord "本文"
#
# DISCORD_WEBHOOK_URL は config/agents.env で設定する。
# 未設定なら stderr に WARN を出して何もしない（ジョブは続行）。

# このファイル自身の位置から hermes-lite ルートを解決する。
# 呼び出し元（run-claude.sh / gloop-heartbeat/check.sh / switchbot-action@.service /
# jobwatch の notify_cmd）が HERMES_HOME を export しているとは限らないため、
# 失敗記録の書き先は呼び出し元の環境変数に依存させない。
_NOTIFY_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# リトライを尽くしても投稿できなかったことをローカルに残す。
# これが無いと、Discord webhook が死んでいる間の失敗は stderr WARN が
# journal に流れるだけで、誰も読まないまま消える（2026-07-08/09 の
# DNS 障害では FAIL 通知そのものが落ち、障害が二重に沈黙した）。
# webhook URL は秘密なので記録しない。本文も先頭 200 文字だけにする。
_notify_record_failure() {
  local message="$1"
  local curl_exit="$2"
  local dir="$_NOTIFY_HOME/var"
  mkdir -p "$dir" 2>/dev/null || return 0
  # -c は必須。既定の pretty-print だと 1 件が複数行に割れて JSONL が壊れる。
  jq -nc \
    --arg ts "$(date -Is)" \
    --arg src "${JOB_NAME:-unknown}" \
    --arg ec "$curl_exit" \
    --arg m "${message:0:200}" \
    '{ts:$ts, source:$src, curl_exit:($ec|tonumber?), message_head:$m}' \
    >> "$dir/notify-failures.jsonl" 2>/dev/null || true
}

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
  # 失敗してもジョブは止めない。
  # ただし 1 発勝負にはしない: 2026-07-08 / 07-09 に DNS の一時失敗
  # (Temporary failure in name resolution) で投稿が落ち、しかも落ちたのが
  # ジョブ失敗を知らせる FAIL 通知そのものだったため、障害が二重に沈黙した。
  # --retry-all-errors は 4xx/5xx も含めて再試行する（webhook 側の 5xx 対策）。
  local curl_exit=0
  curl -fsS --retry 3 --retry-delay 2 --retry-connrefused --retry-all-errors \
    --max-time 20 -X POST -H "Content-Type: application/json" \
    -d "$payload" "$DISCORD_WEBHOOK_URL" >/dev/null 2>&1 || curl_exit=$?
  if (( curl_exit != 0 )); then
    echo "[notify] WARN: Discord post failed (after retries, curl exit=$curl_exit)" >&2
    _notify_record_failure "$message" "$curl_exit"
  fi
  # 呼び出し元を止めない契約は維持する（通知失敗でジョブ本体を失敗扱いにしない）。
  return 0
}
