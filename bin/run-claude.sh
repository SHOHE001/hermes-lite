#!/usr/bin/env bash
# claude -p を「無人」で安全に呼ぶ共通ラッパー。
#
# 使い方:
#   ~/hermes-lite/bin/run-claude.sh <job-name>
#
# 前提:
#   - jobs/<job-name>/prompt.md          ... プロンプト本体
#   - jobs/<job-name>/job.env (optional) ... このジョブ固有の上書き設定
#   - .env                                ... 共通設定（DISCORD_WEBHOOK_URL ほか）
#   - lib/disallowed-tools.txt           ... 共通禁止ツールリスト
#
# job.env で上書きできる変数（詳細仕様は docs/wrapper-api.md 参照）:
#   ALLOWED_TOOLS         ... 空白区切り。disallowed と被ったらこちらが優先（claude CLI 仕様）
#   MAX_TURNS             ... 既定 DEFAULT_MAX_TURNS
#   TIMEOUT_SEC           ... 既定 DEFAULT_TIMEOUT_SEC
#   MAX_BUDGET_USD        ... 既定 DEFAULT_MAX_BUDGET_USD（Max サブスク利用時は実害なし、保険）
#   MODEL                 ... 既定 DEFAULT_MODEL
#   NOTIFY_RESULT         ... 1 にすると正常終了時に result を Discord 投稿
#   NOTIFY_ON_ERROR       ... 1 にすると失敗時に概要を Discord 投稿（既定 1）
#   SUPPRESS_RESULT_IF    ... 最終応答が完全一致したら Discord 投稿をスキップ（opt-in）
#   SUPPRESS_EMPTY_RESULT ... 1 にすると空 result の "(no result text)" 投稿もスキップ（既定 0）
#   RESULT_ERROR_PREFIX   ... RESULT_TEXT がこの prefix で始まる場合 FAIL 経路扱い（既定 "ERROR:"、空で無効化）
#
# ラッパー自体は失敗しても exit 0 で抜ける（systemd timer の連鎖を壊さないため）。

set -u  # set -e は使わない。失敗してもログ→Discord通知→cost記録の流れを止めたくない。

# --- パス ---
export HERMES_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOB_NAME="${1:-}"
if [[ -z "$JOB_NAME" ]]; then
  echo "usage: $0 <job-name>" >&2
  exit 2
fi

JOB_DIR="$HERMES_HOME/jobs/$JOB_NAME"
PROMPT_FILE="$JOB_DIR/prompt.md"
JOB_ENV="$JOB_DIR/job.env"
LOG_DIR="$HERMES_HOME/logs/$JOB_NAME"
COST_CSV="$LOG_DIR/cost.csv"

if [[ ! -d "$JOB_DIR" ]]; then
  echo "[run-claude] ERROR: job dir not found: $JOB_DIR" >&2
  exit 2
fi
if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "[run-claude] ERROR: prompt.md not found: $PROMPT_FILE" >&2
  exit 2
fi

mkdir -p "$LOG_DIR"

# --- 共通設定読み込み ---
# set -a で .env 内の `KEY=value`（export 無し）も自動 export し、
# claude subprocess に環境変数として承継させる。
# shellcheck disable=SC1091
set -a
source "$HERMES_HOME/.env"
set +a
# shellcheck disable=SC1091
source "$HERMES_HOME/lib/notify.sh"

# --- ジョブ固有設定読み込み（任意） ---
ALLOWED_TOOLS=""
NOTIFY_RESULT="0"
NOTIFY_ON_ERROR="1"
MAX_TURNS="$DEFAULT_MAX_TURNS"
TIMEOUT_SEC="$DEFAULT_TIMEOUT_SEC"
MAX_BUDGET_USD="$DEFAULT_MAX_BUDGET_USD"
MODEL="$DEFAULT_MODEL"
# 最終応答が完全一致したら Discord 投稿をスキップしたいジョブ向け（opt-in）。
# 例: mail-watch は 0 件時に "[NOOP]" を返すので、job.env で SUPPRESS_RESULT_IF="[NOOP]" を設定する。
SUPPRESS_RESULT_IF=""

# 空 RESULT_TEXT のときの "(no result text)" 投稿を抑止するか。"1" のみ true（opt-in）。
SUPPRESS_EMPTY_RESULT="0"

# RESULT_TEXT がこの prefix で始まる場合に FAIL 経路扱いとする。
# 既定 "ERROR:" は 4 job (mail-watch / goals-nudge / approval-demo-proposer / interview-mail-proposer) の既存契約。
# 空文字に設定すれば検出を無効化できる。値内の [, *, ? 等のメタ文字は literal 扱い。
RESULT_ERROR_PREFIX="ERROR:"

if [[ -f "$JOB_ENV" ]]; then
  # shellcheck disable=SC1090
  source "$JOB_ENV"
fi

# --- disallowed-tools を配列化（コメント行・空行を除外） ---
DISALLOWED=()
while IFS= read -r line; do
  [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
  DISALLOWED+=("$line")
done < "$HERMES_HOME/lib/disallowed-tools.txt"

# --- claude バイナリ ---
CLAUDE_BIN="${CLAUDE_BIN:-$HOME/.local/bin/claude}"
if [[ ! -x "$CLAUDE_BIN" ]]; then
  echo "[run-claude] ERROR: claude not found at $CLAUDE_BIN" >&2
  [[ "$NOTIFY_ON_ERROR" == "1" ]] && notify_discord "[$JOB_NAME] ERROR: claude binary not found"
  exit 0  # ラッパーは静かに抜ける
fi

# --- ログファイル ---
TS="$(date +%Y%m%d-%H%M%S)"
JSON_LOG="$LOG_DIR/$TS.json"
ERR_LOG="$LOG_DIR/$TS.stderr"

# --- claude -p 呼び出し ---
PROMPT="$(cat "$PROMPT_FILE")"

CLAUDE_ARGS=(
  -p "$PROMPT"
  --output-format json
  --max-turns "$MAX_TURNS"
  --model "$MODEL"
  --permission-mode default
)

# MAX_BUDGET_USD は claude -p が API キー利用時のみ意味を持つ。
# サブスク利用時にエラーにならないことを優先するため指定だけはしておく。
CLAUDE_ARGS+=(--max-budget-usd "$MAX_BUDGET_USD")

if (( ${#DISALLOWED[@]} > 0 )); then
  CLAUDE_ARGS+=(--disallowed-tools "${DISALLOWED[@]}")
fi

if [[ -n "${ALLOWED_TOOLS// /}" ]]; then
  # shellcheck disable=SC2206  # 空白で配列化したい
  ALLOWED_ARR=(${ALLOWED_TOOLS})
  CLAUDE_ARGS+=(--allowed-tools "${ALLOWED_ARR[@]}")
fi

echo "[run-claude] $(date -Is) job=$JOB_NAME model=$MODEL timeout=${TIMEOUT_SEC}s" >&2

# CI=1 を立てて非対話化（claude-watch でも同じ）
CI=1 timeout --foreground "${TIMEOUT_SEC}s" \
  "$CLAUDE_BIN" "${CLAUDE_ARGS[@]}" \
  >"$JSON_LOG" 2>"$ERR_LOG"
EXIT_CODE=$?

# --- 結果抽出 ---
RESULT_TEXT=""
COST_USD=""
INPUT_TOKENS=""
OUTPUT_TOKENS=""
IS_ERROR=""

if [[ -s "$JSON_LOG" ]]; then
  # --output-format json は {"type":"result","result":"...","total_cost_usd":...,"usage":{...},"is_error":false,...} を出す
  RESULT_TEXT=$(jq -r '.result // empty' "$JSON_LOG" 2>/dev/null || true)
  COST_USD=$(jq -r '.total_cost_usd // empty' "$JSON_LOG" 2>/dev/null || true)
  INPUT_TOKENS=$(jq -r '.usage.input_tokens // empty' "$JSON_LOG" 2>/dev/null || true)
  OUTPUT_TOKENS=$(jq -r '.usage.output_tokens // empty' "$JSON_LOG" 2>/dev/null || true)
  IS_ERROR=$(jq -r '.is_error // empty' "$JSON_LOG" 2>/dev/null || true)
fi

# --- cost.csv 追記 ---
if [[ ! -f "$COST_CSV" ]]; then
  echo "timestamp,exit_code,is_error,usd,input_tokens,output_tokens" > "$COST_CSV"
fi
echo "$TS,$EXIT_CODE,${IS_ERROR:-},${COST_USD:-},${INPUT_TOKENS:-},${OUTPUT_TOKENS:-}" >> "$COST_CSV"

# --- 通知 ---
# RESULT_TEXT が RESULT_ERROR_PREFIX で始まる場合は claude プロセス自体は正常終了でも
# 失敗扱いにする (例: prompt 側の fail-fast でラベル不在等)。
# RESULT_ERROR_PREFIX が空のときはこの判定を無効化する。
# substring 比較で literal 一致を保証（pattern matching に依存しない）。
_starts_with_error_prefix=0
if [[ -n "$RESULT_ERROR_PREFIX" \
    && "${RESULT_TEXT:0:${#RESULT_ERROR_PREFIX}}" == "$RESULT_ERROR_PREFIX" ]]; then
  _starts_with_error_prefix=1
fi

if [[ "$EXIT_CODE" -eq 0 && "$IS_ERROR" != "true" && "$_starts_with_error_prefix" -eq 0 ]]; then
  echo "[run-claude] OK exit=0 cost=${COST_USD:-?} in=${INPUT_TOKENS:-?} out=${OUTPUT_TOKENS:-?}" >&2
  if [[ "$NOTIFY_RESULT" == "1" ]]; then
    if [[ -n "${SUPPRESS_RESULT_IF:-}" && "$RESULT_TEXT" == "$SUPPRESS_RESULT_IF" ]]; then
      echo "[run-claude] result matched SUPPRESS_RESULT_IF — skipping Discord post" >&2
    elif [[ -z "$RESULT_TEXT" && "$SUPPRESS_EMPTY_RESULT" == "1" ]]; then
      echo "[run-claude] empty result + SUPPRESS_EMPTY_RESULT=1 — skipping Discord post" >&2
    elif [[ -z "$RESULT_TEXT" ]]; then
      notify_discord "[$JOB_NAME] (no result text)"
    else
      notify_discord "[$JOB_NAME] $RESULT_TEXT"
    fi
  fi
else
  if [[ "$_starts_with_error_prefix" -eq 1 && "$EXIT_CODE" -eq 0 && "$IS_ERROR" != "true" ]]; then
    if [[ "$RESULT_ERROR_PREFIX" == "ERROR:" ]]; then
      echo "[run-claude] FAIL via ERROR: prefix in result" >&2
    else
      printf '[run-claude] FAIL via ERROR: prefix in result (%q)\n' "$RESULT_ERROR_PREFIX" >&2
    fi
  else
    echo "[run-claude] FAIL exit=$EXIT_CODE is_error=${IS_ERROR:-?}" >&2
  fi
  if [[ "$NOTIFY_ON_ERROR" == "1" ]]; then
    ERR_SNIPPET=""
    # 旧来 ERROR: prefix 互換: prefix を無効化していても RESULT_TEXT を採用する（データフロー分離）
    if [[ "$_starts_with_error_prefix" -eq 1 || "$RESULT_TEXT" == ERROR:* ]]; then
      ERR_SNIPPET="$RESULT_TEXT"
    elif [[ -s "$ERR_LOG" ]]; then
      ERR_SNIPPET=$(tail -c 500 "$ERR_LOG")
    fi
    notify_discord "[$JOB_NAME] FAIL exit=$EXIT_CODE\n\`\`\`\n${ERR_SNIPPET:-(no stderr)}\n\`\`\`"
  fi
fi

# ラッパー自身は常に exit 0（タイマー連鎖を保つ）
exit 0
