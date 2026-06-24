#!/usr/bin/env bash
# hermes-lite 承認ゲートの bash ヘルパー.
#
# 使い方:
#   source "$HERMES_HOME/lib/approvals.sh"
#   approval_enqueue <proposer> <executor> <action> <summary> <payload_json>
#   approval_get <id>
#   approval_list [status]
#
# Python CLI (lib/approvals.py) を呼ぶだけの薄いラッパー。jq 非依存。
# proposer ジョブの prompt.md からも呼べる。

set -u

# HERMES_HOME 自己導出 (run-claude.sh が export しているはずだが念のため)
if [[ -z "${HERMES_HOME:-}" ]]; then
  HERMES_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

approval_python() {
  python3 "$HERMES_HOME/lib/approvals.py" "$@"
}

# stdin から payload JSON を流し込んで enqueue する。stdout に id を返す。
approval_enqueue() {
  local proposer="$1" executor="$2" action="$3" summary="$4" payload_json="$5"
  printf '%s' "$payload_json" | approval_python enqueue \
    --proposer "$proposer" \
    --executor "$executor" \
    --action "$action" \
    --summary "$summary"
}

approval_decide() {
  local aid="$1" decision="$2"
  shift 2
  approval_python decide --id "$aid" --decision "$decision" "$@"
}

approval_get() {
  local aid="$1"
  approval_python get --id "$aid"
}

approval_list() {
  if [[ $# -gt 0 ]]; then
    approval_python list --status "$1"
  else
    approval_python list
  fi
}

approval_sweep_all() {
  approval_python sweep
  approval_python sweep-stale-approved
  approval_python sweep-stale-executing
}
