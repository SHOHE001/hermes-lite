#!/usr/bin/env bash
# stub-claude.sh — 本物の claude の代わりに、env 経由で渡された job ID に応じた固定 JSON response を返す。
# CLAUDE_BIN= で wrapper に差し込まれ、`claude -p ... --output-format json` のように引数を受けるが、
# 引数の中身は無視し、$STUB_CLAUDE_JOB_FILE に書かれた job ID で fixture を選ぶ。

set -u

JOB_ID=$(cat "${STUB_CLAUDE_JOB_FILE:-/dev/null}" 2>/dev/null || echo unknown)

IS_ERROR=false

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
  t13-is-error-no-stderr)
    # claude CLI 自身のエラー: ERROR: prefix を持たず stderr も空だが、
    # is_error=true と result に原因が入る（2026-08-01 の OAuth 失効の実物と同型）。
    RESULT='Failed to authenticate: OAuth session expired and could not be refreshed'
    IS_ERROR=true
    ;;
  *)
    RESULT='ok'
    ;;
esac

jq -n --arg r "$RESULT" --argjson e "$IS_ERROR" \
  '{type:"result", result:$r, total_cost_usd:0, usage:{input_tokens:0, output_tokens:0}, is_error:$e}'
