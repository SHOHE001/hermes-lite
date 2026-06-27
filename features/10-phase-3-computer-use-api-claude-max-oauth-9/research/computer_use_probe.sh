#!/usr/bin/env bash
# Approach A: capability/CLI schema observation, + Approach C pricing curl.
# Issue #10 research code. NOT for production import. See ../README.md.
#
# Usage:
#   bash computer_use_probe.sh approach-a
#       claude --help grep + curl docs.claude.com + (optional) CLI probe.
#       Output: allowlist JSON only (no raw bodies, no tokens, no home paths).
#   bash computer_use_probe.sh pricing
#       curl Anthropic pricing page, write redacted excerpt to stdout.

set -u  # not -e: we want to record failures as allowlist JSON, not crash

CMD="${1:-help}"
TIMEOUT_SEC=60
STAGE=""

emit_a_summary() {
  # args: outcome sub_outcome cli_help_has_betas_flag cli_probe_tool_use_observed elapsed stage extra_notes
  python3 -c "
import json,sys
print(json.dumps({
  'approach':'A',
  'outcome':sys.argv[1], 'sub_outcome':sys.argv[2],
  'cli_help_has_betas_flag': sys.argv[3]=='true',
  'cli_probe_tool_use_observed': sys.argv[4]=='true',
  'additional_turn_attempted': False,
  'console_window_minutes': 15,
  'console_checked_at': None,
  'billing_delta_class': 'not_applicable',
  'billing_observation': 'not_applicable',
  'elapsed_seconds': int(sys.argv[5]),
  'stage': sys.argv[6],
  'exit_code': 0,
  'notes': sys.argv[7][:80],
}, sort_keys=True))
" "$1" "$2" "$3" "$4" "$5" "$6" "$7"
}

approach_a() {
  local t0=$(date +%s)

  # Step 1: claude --help has betas/computer flag?
  STAGE="approach_a_help"
  local has_betas="false"
  if command -v claude >/dev/null 2>&1; then
    if claude --help 2>&1 | grep -iqE 'computer.use|--beta|--experimental|--tool'; then
      has_betas="true"
    fi
  fi

  # Step 2: docs URL fetch (existence check only, no body persisted)
  STAGE="approach_a_docs"
  local docs_ok="false"
  if curl -fsSL --max-time 30 -o /dev/null \
      "https://docs.claude.com/en/docs/agents-and-tools/computer-use" 2>/dev/null; then
    docs_ok="true"
  fi

  # Step 3: CLI probe (capability observation only — does NOT call the Anthropic API
  # itself; we just check that claude -p subprocess returns something). We do NOT
  # use this for outcome judgement (Approach A is capability-only).
  STAGE="approach_a_probe"
  local probe_tool_use="false"
  local probe_ok="false"
  if command -v claude >/dev/null 2>&1; then
    if timeout 30 claude -p --output-format text "ok とだけ返して" >/dev/null 2>&1; then
      probe_ok="true"
    fi
  fi
  # NOTE: claude -p capability check above does not exercise Computer Use tool;
  # tool_use_observed via CLI is treated as best-effort (always false here).

  local elapsed=$(( $(date +%s) - t0 ))

  # Approach A is capability observation only. Outcome is always 'undetermined'
  # in the sense that A does not produce a supported/unsupported verdict on its
  # own — final outcome is decided by Approach B. We record capability flags.
  emit_a_summary "undetermined" "capability_observation_only" \
    "$has_betas" "$probe_tool_use" "$elapsed" "approach_a_complete" \
    "docs_reachable=$docs_ok cli_probe_ok=$probe_ok"
}

pricing() {
  STAGE="approach_c_pricing_fetch"
  local url="https://docs.claude.com/en/docs/about-claude/models/overview"
  local pricing_url="https://www.anthropic.com/pricing"
  local t0=$(date +%s)

  # We fetch pricing into a tmp and grep for safe patterns only (no raw body
  # dumped to stdout). The cost_estimate.md should record assumptions and ranges.
  local tmp=$(mktemp)
  local fetch_ok="false"
  if curl -fsSL --max-time 30 -o "$tmp" "$pricing_url" 2>/dev/null; then
    fetch_ok="true"
  fi

  # Extract dollar-per-token-ish patterns (informational only).
  local found_lines="0"
  if [ "$fetch_ok" = "true" ]; then
    found_lines=$(grep -cE '\$[0-9.]+ */ ?MTok|per million tokens|input tokens|output tokens' "$tmp" 2>/dev/null || echo 0)
  fi
  rm -f "$tmp"

  local elapsed=$(( $(date +%s) - t0 ))
  # Approach C is purely a reference fetch; do NOT reuse Approach B outcome enum.
  # We always set outcome=undetermined sub_outcome=usage_schema_unknown to mean
  # "not part of the B-side outcome decision, just informational reference data".
  python3 -c "
import json,sys
print(json.dumps({
  'approach':'C',
  'outcome':'undetermined',
  'sub_outcome':'usage_schema_unknown',
  'additional_turn_attempted': False,
  'console_window_minutes': 15,
  'console_checked_at': None,
  'billing_delta_class': 'not_applicable',
  'billing_observation': 'not_applicable',
  'elapsed_seconds': int(sys.argv[2]),
  'stage': 'approach_c_pricing_fetch',
  'exit_code': 0,
  'notes': ('pricing_url_fetch_ok=%s informational_match_lines=%s' % (sys.argv[1], sys.argv[3]))[:80],
}, sort_keys=True))
" "$fetch_ok" "$elapsed" "$found_lines"
}

case "$CMD" in
  approach-a) approach_a ;;
  pricing) pricing ;;
  help|*)
    cat <<EOF
Usage: $0 approach-a | pricing

  approach-a   Run Approach A (capability observation, CLI + docs reachability).
  pricing      Fetch Anthropic pricing page for Approach C estimate.

Output: a single line of allowlist JSON per command.
EOF
    ;;
esac
