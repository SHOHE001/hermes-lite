#!/usr/bin/env bash
# session-search.sh: Search across Claude Code session JSONL logs.
#
# Public contract is documented in --help (this file's usage()).
# See features/5-fts5-claude-projects-jsonl-grep/plan.md for design notes.
set -euo pipefail

PROJECTS_DIR="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
# Normalize trailing slash so `ltrimstr($pdir + "/")` in JQ_EXTRACT works
# correctly even when caller passes "/path/" (otherwise PROJECT becomes empty).
PROJECTS_DIR="${PROJECTS_DIR%/}"
# Batch size for xargs-driven jq invocations. With BATCH_SIZE=500 and typical
# Claude Code path lengths (~100 bytes) this keeps each batch under ~50 KB
# argv, well below the OS ARG_MAX limit (~2 MB on Linux). Override only for
# tests.
BATCH_SIZE=500
PROJECT_GLOB='*'
SINCE=''
UNTIL=''
MAX_RESULTS=50
SNIPPET_LEN=200
CASE_INSENSITIVE=0
FIXED_STRING=0
declare -a QUERY_PARTS=()
QUERY=""

usage() {
  cat <<'EOF'
Usage: session-search [OPTIONS] [--] QUERY...

Search across all Claude Code session JSONL logs in $CLAUDE_PROJECTS_DIR
(default: ~/.claude/projects).

Options:
  -p PROJECT_GLOB   Restrict to project dirs matching glob (default: *)
  -s YYYY-MM-DD     Only show entries on/after this date
  -u YYYY-MM-DD     Only show entries on/before this date
  -n MAX            Max number of results (positive integer, default: 50)
  -c LEN            Snippet length cap in bytes (positive integer, default: 200)
  -i                Case-insensitive
  -F                Treat QUERY as fixed string
  -h, --help        Show this help

Use '--' to start QUERY when it begins with '-':
  session-search -- '-foo'

Exit codes:
  0  Success (including zero matches).
  1  Environment error (missing dependency, projects dir not found,
     internal jq filter compile error). Unreadable jsonl files are skipped
     silently and do NOT affect the exit code.
  2  Usage / argument error (missing QUERY, invalid date, invalid -n / -c,
     invalid project glob characters, invalid regex QUERY).

Output (TSV, 5 columns): PROJECT<TAB>DATE<TAB>SESSION<TAB>TYPE<TAB>SNIPPET
  - Same-jsonl order is time-ascending; cross-jsonl order is not guaranteed.
  - SNIPPET is the first LEN bytes of the matched extracted text. The query
    string is not guaranteed to appear within SNIPPET (no match-center cut).
    Output length is at most LEN + 3 bytes (the trailing '...' marker is
    UTF-8 '…' = 3 bytes).
  - SNIPPET is the extracted text with control characters (tab/newline/CR)
    normalized to single spaces. Literal backslash sequences (e.g. '\t' in
    source) are preserved as-is.
  - DATE is the first 10 characters of the JSONL record's "timestamp" field,
    only when it starts with an ISO-8601 date (YYYY-MM-DD). Otherwise DATE is
    the empty string. When -s / -u are given, rows with empty DATE are
    excluded (cannot be compared lexically against the bound).
  - Unreadable JSONL files are skipped silently.

Limitations:
  - Project dir names that contain tab or newline characters are NOT
    supported. Only Claude Code's auto-generated naming convention
    (path-encoded dirs under ~/.claude/projects/) is in scope.

Environment:
  CLAUDE_PROJECTS_DIR   Root directory containing per-project subdirs
                        (default: ~/.claude/projects).
EOF
}

validate_date()   { [[ "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; }
validate_posint() { [[ "$1" =~ ^[1-9][0-9]*$ ]]; }
validate_glob()   { [[ "$1" =~ ^[A-Za-z0-9_*?@.+-]+$ ]]; }

check_deps() {
  for c in jq awk find xargs; do
    command -v "$c" >/dev/null || { echo "missing dep: $c" >&2; exit 1; }
  done
}

# JQ_EXTRACT emits a 5-column TSV directly:
#   PROJECT<TAB>DATE<TAB>SESSION<TAB>TYPE<TAB>TEXT
#
# PROJECT and SESSION are derived from input_filename so that one jq invocation
# can process every matching jsonl in a single fork (avoids the per-file
# startup cost). The text column is the @tsv-escaped extracted string: any
# real tab/newline/CR in the parsed JSON value becomes a 2-char "\t"/"\n"/"\r"
# escape, and any real backslash becomes "\\". As a result the 5-column TSV
# is *always* well-formed (no field can hold a literal tab) and downstream
# awk can parse it with -F'\t' safely.
#
# DATE is only emitted when the timestamp string starts with an ISO-8601 date
# (YYYY-MM-DD). Non-ISO or empty timestamps yield an empty DATE; the awk
# stage drops those rows when -s / -u is in effect.
#
# Normalization (control chars -> space, multi-space collapse) is intentionally
# done in awk (match_and_format) rather than in jq: jq's gsub on every output
# string is ~25x slower than awk for our workload and would blow through the
# T26 5s acceptance budget on real ~/.claude/projects/ corpora.
JQ_EXTRACT='
  ($pdir + "/") as $pfx
  | (input_filename // "") as $fn
  | (($fn | ltrimstr($pfx)) | split("/") | (.[0] // "")) as $project
  | (($fn | split("/") | (.[-1] // "")) | sub("\\.jsonl$"; "")) as $session
  | (fromjson?) as $r
  | if $r == null then empty
    elif ($r.type == "user") then
      ($r.message.content
        | if type == "string" then [.]
          elif type == "array" then map(select(type == "object" and .type == "text") | .text)
          else [] end)
    elif ($r.type == "assistant") then
      ($r.message.content
        | if type == "string" then [.]
          elif type == "array" then
            map(select(type == "object" and (.type == "text" or .type == "thinking")) | (.text // .thinking))
          else [] end)
    else [] end
  | .[]?
  | select(type == "string" and . != "")
  | (($r.timestamp // "") | tostring) as $ts
  | (if ($ts | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}")) then $ts[0:10] else "" end) as $date
  | [$project, $date, $session, ($r.type // ""), .]
  | @tsv
'

precompile_filters() {
  # jq exit codes: 3 = compile (syntax) error. Other non-zero codes (runtime,
  # no-output) are not fatal here because the real invocation provides input.
  set +e
  jq -n --arg pdir "$PROJECTS_DIR" "$JQ_EXTRACT" >/dev/null 2>&1
  local rc=$?
  set -e
  if [[ $rc -eq 3 ]]; then
    echo "internal: invalid jq filter" >&2
    exit 1
  fi
  if [[ $FIXED_STRING -eq 0 ]]; then
    LC_ALL=C awk -v q="$QUERY" 'BEGIN { if ("" ~ q) {} }' </dev/null 2>/dev/null \
      || { echo "invalid regex: $QUERY" >&2; exit 2; }
  fi
}

parse_args() {
  while getopts ":p:s:u:n:c:iFh-:" opt; do
    case "$opt" in
      p) PROJECT_GLOB="$OPTARG" ;;
      s) SINCE="$OPTARG" ;;
      u) UNTIL="$OPTARG" ;;
      n) MAX_RESULTS="$OPTARG" ;;
      c) SNIPPET_LEN="$OPTARG" ;;
      i) CASE_INSENSITIVE=1 ;;
      F) FIXED_STRING=1 ;;
      h) usage; exit 0 ;;
      -) case "$OPTARG" in
           help) usage; exit 0 ;;
           *)    echo "unknown option: --$OPTARG" >&2; exit 2 ;;
         esac ;;
      :) echo "missing argument for -$OPTARG" >&2; exit 2 ;;
      \?) echo "unknown option: -$OPTARG" >&2; exit 2 ;;
    esac
  done
  shift $((OPTIND - 1))
  QUERY_PARTS=("$@")
}

validate_args() {
  if [[ ${#QUERY_PARTS[@]} -eq 0 ]]; then
    usage >&2
    exit 2
  fi
  validate_glob   "$PROJECT_GLOB"  || { echo "invalid project glob: $PROJECT_GLOB" >&2; exit 2; }
  validate_posint "$MAX_RESULTS"   || { echo "invalid -n: $MAX_RESULTS" >&2; exit 2; }
  validate_posint "$SNIPPET_LEN"   || { echo "invalid -c: $SNIPPET_LEN" >&2; exit 2; }
  if [[ -n "$SINCE" ]]; then
    validate_date "$SINCE" || { echo "invalid date: $SINCE" >&2; exit 2; }
  fi
  if [[ -n "$UNTIL" ]]; then
    validate_date "$UNTIL" || { echo "invalid date: $UNTIL" >&2; exit 2; }
  fi
  if [[ -n "$SINCE" && -n "$UNTIL" && "$SINCE" > "$UNTIL" ]]; then
    echo "since after until: $SINCE > $UNTIL" >&2
    exit 2
  fi
  [[ -d "$PROJECTS_DIR" ]] || { echo "no projects dir: $PROJECTS_DIR" >&2; exit 1; }
}

match_and_format() {
  # ci 時は gawk の IGNORECASE には依存せず、tolower() で揃える（gawk/mawk 共通）
  LC_ALL=C awk -F '\t' \
    -v query="$QUERY" \
    -v ci="$CASE_INSENSITIVE" \
    -v fx="$FIXED_STRING" \
    -v since="$SINCE" \
    -v upto="$UNTIL" \
    -v slen="$SNIPPET_LEN" \
    -v max="$MAX_RESULTS" \
    'BEGIN {
       OFS = "\t"; c = 0
       if (ci) q_norm = tolower(query); else q_norm = query
     }
     {
       # When -s/-u is given, rows whose DATE is empty (non-ISO or missing
       # timestamp) cannot be compared against the bound — drop them.
       if ((since != "" || upto != "") && $2 == "") next
       if (since != "" && $2 < since) next
       if (upto  != "" && $2 > upto)  next
       # Normalize the @tsv-escaped text column:
       #   real "\\" (escape for source backslash) -> sentinel  (preserve)
       #   real "\t" / "\n" / "\r" (escapes for control chars) -> single space
       #   sentinel -> "\\" (restore)
       #   collapse repeated spaces -> single space
       # The 4-step dance keeps a literal source "\\t" 2-char sequence intact
       # (it appears as "\\\\t" 4-char after @tsv; sentinel hides the "\\\\"
       # so only the unescaped "\t" gets normalized to space).
       text = $5
       gsub(/\\\\/, "\x01", text)
       gsub(/\\[tnr]/, " ", text)
       gsub(/\x01/, "\\\\", text)
       gsub(/  +/, " ", text)
       hay = ci ? tolower(text) : text
       if (fx) {
         if (index(hay, q_norm) == 0) next
       } else {
         if (!(hay ~ q_norm)) next
       }
       snippet = text
       if (length(snippet) > slen) snippet = substr(snippet, 1, slen) "…"
       print $1, $2, $3, $4, snippet
       c++
       if (c >= max) exit
     }'
}

# emit_extracted: list every readable jsonl path under matching project dirs
# as a NUL-separated stream and pipe it to xargs, which invokes jq in batches
# of BATCH_SIZE files. PROJECT and SESSION are derived in jq via
# input_filename, so we keep the same public contract ("PROJECT is the
# top-level project dir, not subagent/UUID nesting") even though we no longer
# iterate per-file in shell.
#
# Batching avoids the ARG_MAX trap: jq is invoked once per batch with at most
# BATCH_SIZE file paths on its command line. Each batch is independent — a
# read error in one batch does not affect later batches.
emit_extracted() {
  local project_dir project jsonl
  {
    for project_dir in "$PROJECTS_DIR"/*/; do
      [[ -d "$project_dir" ]] || continue
      project=$(basename "$project_dir")
      [[ "$project" == $PROJECT_GLOB ]] || continue
      while IFS= read -r -d '' jsonl; do
        # Silently skip files that are not readable (chmod 000, permission
        # denied, broken symlink, etc.). Keeping the check here means jq
        # never sees an unreadable path, so it can never abort a whole batch
        # for one bad file.
        [[ -r "$jsonl" ]] || continue
        printf '%s\0' "$jsonl"
      done < <(find "$project_dir" -name '*.jsonl' -print0 2>/dev/null)
    done
  } | xargs -0 -n "$BATCH_SIZE" -r jq -Rr --arg pdir "$PROJECTS_DIR" "$JQ_EXTRACT" 2>/dev/null
}

main() {
  check_deps
  parse_args "$@"
  validate_args
  QUERY="${QUERY_PARTS[*]}"
  precompile_filters

  (
    set +o pipefail
    emit_extracted | match_and_format
    rc=$?
    # 141 = SIGPIPE (match_and_format が cap で exit したときに上流が受け取る)。これは正常パス
    [[ $rc -eq 141 ]] && rc=0
    exit "$rc"
  )
}

main "$@"
