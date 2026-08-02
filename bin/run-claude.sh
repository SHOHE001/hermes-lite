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
#   MAX_BUDGET_USD        ... 既定 DEFAULT_MAX_BUDGET_USD。OAuth 枠でも効き、超えると is_error で落ちる
#   MODEL                 ... 既定 DEFAULT_MODEL
#   NOTIFY_RESULT         ... 1 にすると正常終了時に result を Discord 投稿
#   NOTIFY_ON_ERROR       ... 1 にすると失敗時に概要を Discord 投稿（既定 1）
#   SUPPRESS_RESULT_IF    ... 最終応答が完全一致 or この文字列で終わるなら Discord 投稿をスキップ（opt-in）
#   SUPPRESS_EMPTY_RESULT ... 1 にすると空 result の "(no result text)" 投稿もスキップ（既定 0）
#   RESULT_ERROR_PREFIX   ... RESULT_TEXT がこの prefix で始まる場合 FAIL 経路扱い（既定 "ERROR:"、空で無効化）
#
# 終了コードの契約:
#   0 ... OK 経路（claude が正常終了し is_error でも ERROR: 行でもない）
#   1 ... FAIL 経路（claude の失敗 / タイムアウト / is_error / ERROR: 行 / claude 不在）
#   2 ... セットアップ不備（引数なし・ジョブ不在・prompt.md 不在）
# 非 0 を返しても systemd timer の次回発火は止まらない（timer は前回の service 結果を
# 参照せず OnCalendar で独立に起動する）。詳細は末尾のコメント参照。

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
  # 廃止済みジョブを叩いたときは、ただの not found ではなくその旨を返す
  if [[ -d "$HERMES_HOME/jobs/_archived/$JOB_NAME" ]]; then
    echo "[run-claude] ERROR: '$JOB_NAME' は廃止済み。jobs/_archived/$JOB_NAME/README.md に経緯がある" >&2
    exit 2
  fi
  echo "[run-claude] ERROR: job dir not found: $JOB_DIR" >&2
  exit 2
fi
if [[ ! -f "$PROMPT_FILE" ]]; then
  echo "[run-claude] ERROR: prompt.md not found: $PROMPT_FILE" >&2
  exit 2
fi

mkdir -p "$LOG_DIR"

# --- 共通設定読み込み ---
# .env は本シェル内でのみ参照し、claude 子プロセスへは環境変数として渡さない
# （DISCORD_TOKEN 等の秘密が prompt injection 経由で流出する経路を断つ / 秘密の継承カット）。
# notify.sh は同一シェルで source され、DEFAULT_* も同一シェル内の変数参照なので export は不要。
# shellcheck disable=SC1091
source "$HERMES_HOME/.env"
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
# 判定は trim 後の完全一致 or 末尾一致（前置きの説明文が付いても抑止する。投稿箇所のコメント参照）。
SUPPRESS_RESULT_IF=""

# 空 RESULT_TEXT のときの "(no result text)" 投稿を抑止するか。"1" のみ true（opt-in）。
SUPPRESS_EMPTY_RESULT="0"

# RESULT_TEXT がこの prefix で始まる場合に FAIL 経路扱いとする。
# 既定 "ERROR:" は mail-watch / mail-digest / goals-nudge / approval-demo-proposer の既存契約。
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
  exit 1  # 環境が壊れている。systemd 側にも失敗として見せる
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

# MAX_BUDGET_USD は Claude Max の OAuth 枠でも効く（当初「API キー利用時のみ意味を持つ」
# と書いていたが誤り）。2026-08-01 に mail-digest が subtype=error_max_budget_usd /
# is_error=true で落ちるのを実測した。上限に当たるとその回の処理が丸ごと失われるので、
# 実測コストの 2〜3 倍を job.env に設定しておくこと。
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
# RESULT_TEXT の *いずれかの行* が RESULT_ERROR_PREFIX で始まる場合は、
# claude プロセス自体が正常終了でも失敗扱いにする
# (例: prompt 側の fail-fast でラベル不在等)。
#
# かつては RESULT_TEXT の先頭だけを見ていた。しかし実際の応答は説明文から
# 始まり "ERROR: ..." は末尾の行に来る。mail-watch はこれで 2026-07-03 以降
# 60 回連続の失敗を「成功」として通知し続け、23 日間気づかれなかった。
# 先頭一致ではなく行単位で判定すること。
#
# RESULT_ERROR_PREFIX が空のときはこの判定を無効化する。
# substring 比較で literal 一致を保証（pattern matching に依存しない）。
# 既定は失敗側。OK 経路に入ったときだけ 0 に落とす（set -u 対策も兼ねる）。
WRAPPER_EXIT=1

_has_error_line=0
if [[ -n "$RESULT_ERROR_PREFIX" ]]; then
  while IFS= read -r _result_line; do
    if [[ "${_result_line:0:${#RESULT_ERROR_PREFIX}}" == "$RESULT_ERROR_PREFIX" ]]; then
      _has_error_line=1
      break
    fi
  done <<< "$RESULT_TEXT"
fi

if [[ "$EXIT_CODE" -eq 0 && "$IS_ERROR" != "true" && "$_has_error_line" -eq 0 ]]; then
  WRAPPER_EXIT=0
  echo "[run-claude] OK exit=0 cost=${COST_USD:-?} in=${INPUT_TOKENS:-?} out=${OUTPUT_TOKENS:-?}" >&2
  if [[ "$NOTIFY_RESULT" == "1" ]]; then
    # 完全一致だけでなく「末尾一致」も抑止対象にする。claude が指示に反して
    # 前置きの説明文を書いたうえで最後に [NOOP] を置くケースが実測で起きており
    # (2026-07-31 18:00 / 2026-08-01 16:15 の mail-watch)、完全一致だけでは
    # 「0 件です」という不要通知が Discord に飛ぶ。前後の空白は落として比較する。
    _result_trimmed="${RESULT_TEXT#"${RESULT_TEXT%%[![:space:]]*}"}"
    _result_trimmed="${_result_trimmed%"${_result_trimmed##*[![:space:]]}"}"
    if [[ -n "${SUPPRESS_RESULT_IF:-}" && ( "$_result_trimmed" == "$SUPPRESS_RESULT_IF" || "$_result_trimmed" == *"$SUPPRESS_RESULT_IF" ) ]]; then
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
  WRAPPER_EXIT=1
  if [[ "$_has_error_line" -eq 1 && "$EXIT_CODE" -eq 0 && "$IS_ERROR" != "true" ]]; then
    if [[ "$RESULT_ERROR_PREFIX" == "ERROR:" ]]; then
      echo "[run-claude] FAIL via ERROR: line in result" >&2
    else
      printf '[run-claude] FAIL via error line in result (%q)\n' "$RESULT_ERROR_PREFIX" >&2
    fi
  else
    echo "[run-claude] FAIL exit=$EXIT_CODE is_error=${IS_ERROR:-?}" >&2
  fi
  if [[ "$NOTIFY_ON_ERROR" == "1" ]]; then
    ERR_SNIPPET=""
    # 旧来 ERROR: prefix 互換: prefix を無効化していても RESULT_TEXT を採用する（データフロー分離）
    if [[ "$_has_error_line" -eq 1 || "$RESULT_TEXT" == ERROR:* ]]; then
      ERR_SNIPPET="$RESULT_TEXT"
    elif [[ -s "$ERR_LOG" ]]; then
      ERR_SNIPPET=$(tail -c 500 "$ERR_LOG")
    elif [[ -n "$RESULT_TEXT" ]]; then
      # 最後の手段: claude CLI 自身が返すエラーは ERROR: prefix を持たず stderr も空になる。
      # 原因は JSON の .result にだけ入っているので、それを載せる。
      # 2026-08-01 20:00 / 22:00 の mail-watch は
      # "Failed to authenticate: OAuth session expired and could not be refreshed" を
      # JSON に持っていたのに、通知には "(no stderr)" しか出ず原因が読めなかった。
      ERR_SNIPPET=$(printf '%s' "$RESULT_TEXT" | tail -c 500)
    fi
    notify_discord "[$JOB_NAME] FAIL exit=$EXIT_CODE\n\`\`\`\n${ERR_SNIPPET:-(no stderr)}\n\`\`\`"
  fi
fi

# FAIL 判定なら非 0 で抜ける。
# 2026-08-02 まで「タイマー連鎖を保つ」という理由でここは常に exit 0 だったが、
# その前提は誤りだった: systemd の timer は前回の service の Result を参照せず、
# OnCalendar 到達で独立して次回起動する（失敗したままでも次回は動く）。
# 常に 0 を返していたせいで claude-agent@*.service は永遠に Result=success となり、
# systemctl --user list-units --failed にも jobwatch の「サービスの終了結果」判定にも
# 失敗が一切現れなかった。result_glob を持たない switchbot-action@* に至っては
# exit code だけが唯一の手がかりで、そこが潰れていた。
exit "$WRAPPER_EXIT"
