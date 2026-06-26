#!/usr/bin/env bash
# harness 用 stub。本体 lib/notify.sh の同名関数 notify_discord を上書きし、
# Discord HTTP 呼び出しの代わりに $STUB_DISCORD_LOG に payload を append する。

notify_discord() {
  local message="$1"
  if [[ -n "${STUB_DISCORD_LOG:-}" ]]; then
    echo "$message" >> "$STUB_DISCORD_LOG"
  fi
}
