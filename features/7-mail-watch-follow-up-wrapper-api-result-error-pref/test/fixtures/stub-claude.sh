#!/usr/bin/env bash
# stub-claude.sh — 本物の claude の代わりに、env 経由で渡された job ID に応じた固定 JSON response を返す。
# CLAUDE_BIN= で wrapper に差し込まれ、`claude -p ... --output-format json` のように引数を受けるが、
# 引数の中身は無視し、$STUB_CLAUDE_JOB_FILE に書かれた job ID で fixture を選ぶ。

set -u

JOB_ID=$(cat "${STUB_CLAUDE_JOB_FILE:-/dev/null}" 2>/dev/null || echo unknown)

case "$JOB_ID" in
  t01-default-compat)
    RESULT='ok'
    ;;
  t02-empty|t03-empty-default|t09-suppress-bad-value)
    RESULT=''
    ;;
  t04-error-default|t05-error-disabled)
    RESULT='ERROR: stub fail'
    ;;
  t06-error-custom)
    RESULT='[ERR] stub fail'
    ;;
  *)
    RESULT='ok'
    ;;
esac

jq -n --arg r "$RESULT" \
  '{type:"result", result:$r, total_cost_usd:0, usage:{input_tokens:0, output_tokens:0}, is_error:false}'
