#!/bin/bash
# Stop hook entry. Reads stdin (hook event JSON), forks on-stop.py in background.
# 即 exit 0 (hook 自体は数ms で返す)。
set -u

# 緊急停止 / 再帰防止
if [ "${HERMES_SKILL_REVIEW_DISABLE:-0}" = "1" ]; then
    exit 0
fi
if [ "${HERMES_SKILL_REVIEW_RUNNING:-0}" = "1" ]; then
    exit 0
fi

# stdin を一時ファイルに保存 (background 起動後も読めるように)
DIR="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -p /tmp hermes-on-stop.XXXXXX.json)
cat > "$TMP"

# 空 stdin ならスキップ
if [ ! -s "$TMP" ]; then
    rm -f "$TMP"
    exit 0
fi

# background で本体を起動。終了後に tmp を消す。
(
    /usr/bin/python3 "$DIR/bin/on-stop.py" < "$TMP" >> "$DIR/state/on-stop.log" 2>&1
    rm -f "$TMP"
) &
disown
exit 0
