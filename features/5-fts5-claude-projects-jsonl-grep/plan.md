# plan: #5 FTS5 全セッション検索: ~/.claude/projects/ の JSONL を横断検索（grep 版から）

slug: fts5-claude-projects-jsonl-grep
milestone: Phase 2
labels: type:feature, batch:feature

> Issue 名に `FTS5` が含まれるが、本 Issue 本文に明示されている通り「初期は grep でよい / FTS5 は将来 follow-up」という起票者意図に従い、本 plan は grep 実装に絞る。Issue 名はリネームしない（rejection.md 参照）。

## In-Scope / Out-of-Scope

| In-Scope | Out-of-Scope |
|---|---|
| `bin/session-search.sh` を新規追加（jq + awk の bash ラッパー） | LLM 要約 / セマンティック検索 |
| `~/.claude/projects/<project>/**/*.jsonl` を横断検索（外側 for で `<project>` を回し、内側 find で配下の jsonl を列挙する） | Web UI |
| **一段構成**: 各 jsonl を `jq -Rr 'fromjson?'` で抽出（`<timestamp>\t<type>\t<extracted_text>`）→ awk で第3列だけに QUERY 判定 | SQLite FTS5 インデックス（57MB 全件で実用速度のため不要、必要になったら follow-up Issue） |
| `features/5-fts5-claude-projects-jsonl-grep/test-spec.md` と `features/5-fts5-claude-projects-jsonl-grep/smoke-test.sh` を成果物として追加（手動チェックリスト + 開発者ローカル assert 用） | grep prefilter（false negative リスクと exit code の混在を構造的に避けるため、初版では入れない。性能不足が判明したら follow-up Issue で再検討する） |
| プロジェクト名 / 日付範囲 / 件数上限 / 大文字小文字 / fixed-string / snippet 長 のフィルタ引数 | Discord 連携（既存 `lib/notify.sh` と組み合わせれば外で繋げられる） |
| TSV 出力: `PROJECT<TAB>DATE<TAB>SESSION<TAB>TYPE<TAB>SNIPPET` | ripgrep 依存（ゼロ追加依存にする） |
| `~/.claude/projects/**/*.jsonl`（subagent 階層含む）の壊れた行 tolerant 走査 | tool_use / tool_result / attachment / queue-operation 等のメタペイロード本文（Non-Goals） |
| `CLAUDE_PROJECTS_DIR` 環境変数で検索対象 root を差し替え可能（fixture テスト用） | セッション本文のフォーマット整形（マッチ行を抽出テキストからそのまま抜粋する以上のことはしない） |

## Non-Goals

- インデックスの構築・更新パイプライン（grep で十分）
- jsonl の以下フィールド以外の構造化検索:
  - `type=user` の `.message.content`（string）または `.message.content[]?.text`（array の中の text block のみ）
  - `type=assistant` の `.message.content[]?.text`（text block）
  - `type=assistant` の `.message.content[]?.thinking`（thinking block）
  - ※ user の content array に混在する `tool_result` ブロックは抽出対象外
  - ※ assistant の `tool_use` ブロックも抽出対象外
  - ※ `attachment` / `last-prompt` / `mode` / `queue-operation` 等のメタ type は抽出対象外
- 日本語の形態素解析（grep/awk の部分文字列マッチでよい）
- 古いセッション JSONL のアーカイブ / ローテーション
- マッチ位置中心の snippet 切り出し（snippet は抽出テキスト先頭から固定長で切る。検索語が SNIPPET 内に出現しないケースは仕様として許容）

## 設計方針

### 配置
- `bin/session-search.sh`（hermes-lite の既存 `bin/run-claude.sh` と同居）。`tools/` ディレクトリは存在しないので新規作成しない

### 既存 bin/ 規約との整合
- 既存 `bin/run-claude.sh` は `set -u` のみ（`-e` なし）で実用時の連鎖停止を避けている。`session-search.sh` は対話 CLI で部分失敗時に exit code を出したいので `set -euo pipefail` を採用。`HERMES_HOME` の参照は不要（このスクリプトはレポ独立 CLI）
- 環境変数: `CLAUDE_PROJECTS_DIR`（既定 `$HOME/.claude/projects`）でのみ root 変更可能
- exit code 規約: `0`=成功（マッチ 0 件も含む）, `1`=実行環境エラー（projects dir 不在等）, `2`=usage / 引数エラー
- usage は `-h` / `--help` / 引数なし時に stderr または stdout に出す（`-h` の時は stdout、引数不足の時は stderr）

### 依存
- `jq`, `bash`, `awk`（gawk または mawk、`IGNORECASE` 拡張不要）, `find`, `xargs`。`grep` も `ripgrep` も使わない（依存削減）
- case-insensitive (`-i`) は `tolower()` で実装（gawk 拡張の `IGNORECASE` には依存しない、mawk でも動く）
- `xargs -0 -n BATCH -r ...` の `-r`（empty input なら起動しない）は GNU xargs 拡張。**hermes-lite の対象環境は Linux/gen8 サーバーのみ**（CLAUDE.md 参照）なので採用。macOS/BSD は本 Issue のスコープ外、必要なら follow-up Issue で対応

### 起動時の依存チェック

スクリプト先頭で `for c in jq awk find; do command -v "$c" >/dev/null || { echo "missing dep: $c" >&2; exit 1; }; done` を実行する。依存欠如は exit 1（実行環境エラー）。

### 一段パイプライン（prefilter 廃止）

旧版で検討した `grep -l` prefilter は以下の理由で廃止し、全候補 jsonl を jq に流す一段構成にする:

- **false negative**: raw JSON は本文の `\n` / `\t` / `\uXXXX` / 連続空白を escape 表現で保持するが、抽出後テキストは jq 段で正規化されて文字が変わるため、抽出後ならマッチする QUERY が prefilter で落ちる
- **方言ミスマッチ**: `grep` の BRE と `awk` の ERE は同じ regex でも意味が異なる場合がある（`|`, `(...)`, `+` 等）
- **exit code 混在**: `xargs + grep -l` は GNU xargs で grep の no-match 1 が xargs の 123 にリレーされ、invalid regex (>=2) との分離が壊れる

設計:

1. **jsonl 列挙**: 外側 `for project_dir in "$PROJECTS_DIR"/*/; do ...; done`、内側 `find "$project_dir" -name '*.jsonl'`
2. **jq 抽出**: 各 jsonl について `jq -Rr "$JQ_EXTRACT"` で raw 行から `fromjson?` パース、不正行は skip、抽出テキスト（jq 段で制御文字を空白正規化済み）を `<timestamp>\t<type>\t<text>` で stdout に流す。bash 側で awk wrapper を被せて先頭に PROJECT/DATE/SESSION を付け、5 カラム TSV にしてから集約
3. **第3列判定 (awk)**: 集約された TSV を `awk -F '\t'` で受け、第3列（実カラム位置は EXTRACTED_TEXT = $5）のみに対し fixed string (index) or regex (`~`) を case-sensitive/insensitive 切替で判定。合格行を `PROJECT\tDATE\tSESSION\tTYPE\tSNIPPET` に再整形
4. **件数 cap**: awk 内のカウンタで `c >= max` なら `exit`

このパイプライン全体は subshell + `set +o pipefail` で囲み、SIGPIPE 141 を吸収する。`jq` filter の構文エラーは起動前 compile check で検出（後述）。

- メタ列にマッチする偽陽性は構造的に発生しない（awk が EXTRACTED_TEXT のみ評価）
- 壊れた jsonl 1 行で全体が落ちない（`fromjson?` で null フォールバック）
- 検索意味論は **抽出後テキスト 1 ソースのみ**（false negative なし）

### 起動前のエラー予防

- **jq filter compile check**: `jq -n "$JQ_EXTRACT" >/dev/null` を pipeline 起動前に実行。filter 構文エラーなら stderr `internal: invalid jq filter` で exit 1（普通は起こらない、開発時の防壁）
- **regex QUERY の事前 compile**: `-F` なしのとき、awk の `BEGIN` ブロック内で `"" ~ q` を評価することで動的 regex を強制的に compile させる:
  ```bash
  if [[ $FIXED_STRING -eq 0 ]]; then
    if ! LC_ALL=C awk -v q="$QUERY" 'BEGIN { if ("" ~ q) {} }' </dev/null 2>/dev/null; then
      echo "invalid regex: $QUERY" >&2; exit 2
    fi
  fi
  ```
  `BEGIN { if ("" ~ q) {} }` は入力レコードが 0 件でも `q` が動的 regex として compile され、不正なら gawk/mawk 共に fatal で非 0 終了する。これにより awk の regex fatal は pipeline 実行前に exit 2 として捕まる

### SIGPIPE 対策（精密化）

pipeline 全体を `set +o pipefail` で囲むと、jq/awk/find の異常終了も no-match と同一視されてしまう。これを避けるため:

- **producer 側** (`for ... do emit_extracted ... done`) と **consumer 側** (`match_and_format`) を `( set +o pipefail; producer | consumer )` の subshell に閉じ込めるが、subshell の **直前** に `precompile_filters` を必ず通す
- producer 内の `jq` / `find` の I/O エラー（読めない jsonl 等）は producer の stderr に流れるが、exit code は consumer (awk) の status で決まる仕様にする。これは「読み取り不能ファイルは警告なしで skip」を public contract として明示することで担保
- consumer (awk) の異常終了（141 = SIGPIPE）は許容、それ以外の非 0 終了は subshell の exit status として外側に伝播し、main の exit code として返る
- 具体的には subshell の `$?` を main に返す:
  ```bash
  (
    set +o pipefail
    producer | match_and_format
    rc=$?
    # 141 (SIGPIPE) は match_and_format が cap で exit した時のみ起きる正常パス → 0 として扱う
    [[ $rc -eq 141 ]] && rc=0
    exit "$rc"
  )
  ```

### Public contract（README 代替: `--help` のみ）

`bin/session-search.sh --help` を唯一の public contract とする:
- exit code: 0=正常（マッチ 0 件含む）、1=実行環境エラー（依存欠如、projects dir 不在、読み取り不能ファイルは exit code には影響しない）、2=usage / 引数 / regex エラー
- 読み取り不能 jsonl は warning なしで skip
- 出力順序: 同 jsonl 内は時系列昇順、jsonl 間の順序は非保証
- SNIPPET: 抽出テキストの制御文字（tab/newline/CR）を半角スペース 1 個に正規化したもの。本文中の literal `\t` / `\n` 2 文字シーケンス（バックスラッシュ + 文字）はそのまま残る
- DATE: timestamp が `YYYY-MM-DD` で始まる場合のみ先頭 10 文字を出力、それ以外（非 ISO / 空）は空文字列。`-s`/`-u` 指定時は DATE 空の行は除外される
- project dir 名にタブ・改行を含むことはサポート外（@tsv 経路を信頼する設計上の前提）。サポート対象は Claude Code が `~/.claude/projects/` 配下に生成する path-encoded dir 名のみ

### 抽出 jq filter（`jq -Rr` で raw line を受ける）

```jq
fromjson? as $r
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
  else []
  end
| .[]?
| select(type == "string" and . != "")
| gsub("[\\t\\n\\r]+"; " ")     # 制御文字は jq 段で先に空白化（@tsv エスケープ問題回避）
| gsub("  +"; " ")                # 連続空白も jq 段で潰す
| [($r.timestamp // ""), ($r.type // ""), .]
| @tsv
```

- `fromjson?` で raw 行から JSON パース、parse error の行は `empty` 経由で skip
- `.message.content` の型が string / array / その他 / null すべて branch（旧形式 tolerant）
- text 配列の各要素は `select(type=="object" and ...)` で型ガードしてからアクセス
- **制御文字（tab/newline/CR）は jq の `gsub` で先に空白へ正規化**。これで `@tsv` のエスケープが発動するのは「もともと literal `\t` / `\n` 表記の文字列」だけになり、awk 側で扱う第3列に実タブが混入することはない（5 カラム TSV が常に壊れない）
- 出力: 1 行 = 1 抽出単位の `<timestamp>\t<type>\t<text>` TSV

> spec: 抽出テキストに literal `\t` / `\n` の 2 文字シーケンス（例: コードブロックの中の `\\t`）が含まれていた場合、`@tsv` がそれを `\\t` / `\\n` にエスケープして 4 文字になる可能性がある。SNIPPET 表示で気になる場合は呼び出し側で `sed 's/\\\\\\\\/\\\\/g'` 等で復元する想定。これは public spec として「SNIPPET は jq `@tsv` エスケープ後の文字列」とドキュメント化する。

### 引数
| flag | 意味 | 既定 |
|---|---|---|
| `-p PROJECT_GLOB` | プロジェクトディレクトリ名の glob（`~/.claude/projects/` 直下 dir basename に `[[ "$project" == $PROJECT_GLOB ]]` でマッチ） | `*`（全プロジェクト） |
| `-s YYYY-MM-DD` | この日以降（DATE カラムの文字列比較） | なし |
| `-u YYYY-MM-DD` | この日以前（同上） | なし |
| `-n MAX` | 表示上限（正の整数） | 50 |
| `-c LEN` | snippet の最大バイト長（正の整数、`LC_ALL=C` でバイト数として扱う） | 200 |
| `-i` | case-insensitive | off |
| `-F` | fixed string（regex 解釈しない） | off |
| `-h` / `--help` | usage を stdout に出して exit 0 | — |
| `--` | 以降を QUERY 扱い | 任意 |
| 残り引数 | QUERY（`"$*"` で半角スペース結合して **単一パターン** として awk に渡す） | 必須 |

#### QUERY の先頭ハイフン対応

`getopts` は組み込みオプション以外で stop し、`OPTIND` を進める。先頭ハイフンの QUERY は `--` 区切りで明示するのが標準的:

```bash
session-search.sh -i -- '-foo'   # OK
session-search.sh -- '-foo'      # OK
session-search.sh '-foo'         # NG（getopts が unknown option として exit 2）
```

usage に `--` 区切りの存在を明記する。T16 はこの方針に合わせて `session-search.sh -- '-foo'` で動作確認する形に変更。

### 入力検証
- QUERY 未指定 → usage stderr + exit 2
- `-s` / `-u` の値: `^[0-9]{4}-[0-9]{2}-[0-9]{2}$` の正規表現で形式検証のみ（外部 `date` 不依存）
- `-s` の値 > `-u` の値（文字列比較）→ stderr `since after until` で exit 2
- `-n` / `-c`: `^[1-9][0-9]*$` で正の整数のみ
- `-p` の値: shell glob として `[[ "$project" == $PROJECT_GLOB ]]` 評価に使うため、含まれる文字は `[A-Za-z0-9_*?@.+-]` のみ許容（空白 / `)` / `|` / `$` / バッククォート等は弾く）→ exit 2
- **不正な regex QUERY**: regex モード（`-F` 無し）では、pipeline 起動前に awk の `BEGIN` 内で `"" ~ q` を評価する compile check を実行する。fatal を起こす query は stderr `invalid regex: <query>` で exit 2
- `$CLAUDE_PROJECTS_DIR` が無い、または読めない → stderr `no projects dir: <path>` で exit 1
- 依存コマンド（jq/awk/find）欠如 → stderr `missing dep: <cmd>` で exit 1
- 該当ファイル 0 件 / マッチ 0 件 → exit 0 で何も出さない（「結果 0 件は正常終了として扱う」）

### 出力フォーマット（TSV、5 カラム）

```
PROJECT<TAB>DATE<TAB>SESSION<TAB>TYPE<TAB>SNIPPET
```

- PROJECT: `$PROJECTS_DIR/<dir>` の `<dir>` 名（Claude Code エンコード dir、デコードはしない）
- DATE: `timestamp` の `YYYY-MM-DD`（jq 抽出の第 1 列の先頭 10 文字）
- SESSION: jsonl のファイル basename から `.jsonl` を除いたもの（subagent 階層の場合も basename を採る）
- TYPE: `user` または `assistant`
- SNIPPET:
  - 抽出テキストのタブ・改行・連続空白を半角スペース 1 個に正規化（awk で `gsub("[\t\n\r ]+", " ")`）
  - `LC_ALL=C` 環境で `length($0) > LEN` なら `substr($0, 1, LEN) "…"` で末尾切り（バイト数基準）
  - 「LEN バイトに収まらない場合は末尾に `…` を追加する。文字境界での切断は保証しない」とドキュメントに明記
  - 出力長は最大 `LEN + 3`（`…` は UTF-8 で 3 バイト）

### 出力順序

- jsonl ごとに jq が timestamp 順で出力（jsonl 自体が時系列追記なので自然に昇順）
- jsonl 間の出現順は **外側 `for project in "$PROJECTS_DIR"/*/`** + 内側 `find` の列挙順に従う（**全体での timestamp 厳密ソートはしない**）
- `-n MAX` は上記順序で先頭 MAX 件で打ち切り
- 呼び出し元が依存してよい契約として「**同 jsonl 内は時系列昇順、jsonl 間の順序は非保証**」と plan に明記

### timestamp が空 / 非ISO形式の行の扱い

- jq 抽出で `($r.timestamp // "")` を出す。non-ISO や空の場合は DATE カラム（先頭 10 文字）が `YYYY-MM-DD` 形式にならない
- date filter (`-s`/`-u`) **指定時**: DATE 文字列を SINCE/UNTIL と単純に文字列比較する。空 DATE は `""` なので `""` < `"2026-01-01"` が真になり SINCE 指定だと skip される（事実上の除外で OK）
- date filter **未指定時**: DATE が空でも出力する（呼び出し元が DATE 空文字を受ける可能性あり）

### SIGPIPE 対策（再掲）

```bash
( set +o pipefail
  emit_tsv_pipeline | awk -F '\t' -v max="$MAX_RESULTS" '...'
)
```

awk 内で `c++; if (c >= max) exit` する。subshell の外側では `set -euo pipefail` 維持。

### PROJECT_GLOB の評価 / PROJECT 抽出

PROJECT カラムは「`$PROJECTS_DIR/<project>/...` の `<project>` 部分（root 直下 dir）」と定義する。subagent 階層（`<project>/<uuid>/subagents/agent-X.jsonl`）でも同じ `<project>` が PROJECT になる。

実装は外側で `for project_dir in "$PROJECTS_DIR"/*/; do project=$(basename "$project_dir"); [[ "$project" == $PROJECT_GLOB ]] || continue; ...; done` の二段ループにし、内側で `find "$project_dir" -name '*.jsonl'` する。これにより `subagents` や UUID が PROJECT になることはない。

`case "$project" in $PROJECT_GLOB)` だと shell の構文位置に展開されるためメタ文字（`)`, `|`, 改行）が混ざると構文崩壊する。`[[ "$project" == $PROJECT_GLOB ]]` を使う（`==` の右辺は pattern として扱われ、`|` などはリテラル）。さらに入力検証で許容文字を絞る（上記）。

## 実装対象

実装する成果物:
- `bin/session-search.sh`（実装本体、`chmod +x` 必要、public CLI）
- `features/5-fts5-claude-projects-jsonl-grep/test-spec.md`（手動チェックリスト）
- `features/5-fts5-claude-projects-jsonl-grep/smoke-test.sh`（開発者ローカル assert 用、fixture 自動生成 + 主要ケース実行、CI 非統合）

**既存ファイルは編集しない。`bin/run-claude.sh` / `lib/notify.sh` / 既存 jobs/ など一切触らない。** README / CHANGELOG への追記はスコープ外。public contract は `bin/session-search.sh --help` を唯一のソースとし、escape / 順序 / exit code / DATE 空文字の扱いを help 内に完全記載する。

> 既存関数編集: なし（新規ファイルのみのため before/after コードスニペットは N/A）

骨格（実装の主要部は省略なしで明示）:

```bash
#!/usr/bin/env bash
set -euo pipefail

PROJECTS_DIR="${CLAUDE_PROJECTS_DIR:-$HOME/.claude/projects}"
PROJECT_GLOB='*'
SINCE=''
UNTIL=''
MAX_RESULTS=50
SNIPPET_LEN=200
CASE_INSENSITIVE=0
FIXED_STRING=0
declare -a QUERY_PARTS=()

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

Output (TSV): PROJECT  DATE  SESSION  TYPE  SNIPPET
  - Same-jsonl order is time-ascending; cross-jsonl order is not guaranteed.
  - SNIPPET is the first LEN bytes of the matched extracted text. The query
    string is not guaranteed to appear within SNIPPET (no match-center cut).
  - SNIPPET is the jq @tsv-escaped form of the extracted text (literal \t / \n
    sequences in source text appear as \\\\t / \\\\n).
EOF
}

validate_date()   { [[ "$1" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; }
validate_posint() { [[ "$1" =~ ^[1-9][0-9]*$ ]]; }
validate_glob()   { [[ "$1" =~ ^[A-Za-z0-9_*?@.+-]+$ ]]; }

check_deps() {
  for c in jq awk find; do
    command -v "$c" >/dev/null || { echo "missing dep: $c" >&2; exit 1; }
  done
}

precompile_filters() {
  jq -n "$JQ_EXTRACT" >/dev/null 2>&1 \
    || { echo "internal: invalid jq filter" >&2; exit 1; }
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
  [[ ${#QUERY_PARTS[@]} -gt 0 ]] || { usage >&2; exit 2; }
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
    echo "since after until: $SINCE > $UNTIL" >&2; exit 2
  fi
  [[ -d "$PROJECTS_DIR" ]] || { echo "no projects dir: $PROJECTS_DIR" >&2; exit 1; }
}

JQ_EXTRACT='
  fromjson? as $r
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
  | gsub("[\\t\\n\\r]+"; " ")
  | gsub("  +"; " ")
  | [($r.timestamp // ""), ($r.type // ""), .]
  | @tsv
'

QUERY=""           # set in main

emit_extracted() {
  local jsonl="$1" project="$2"
  local session
  session=$(basename "$jsonl" .jsonl)
  jq -Rr "$JQ_EXTRACT" "$jsonl" 2>/dev/null \
    | awk -F '\t' -v p="$project" -v s="$session" \
        'BEGIN{OFS="\t"} {print p, substr($1,1,10), s, $2, $3}'
}

match_and_format() {
  # ci 時は gawk の IGNORECASE には依存せず、tolower() で揃える（gawk/mawk 共通）
  LC_ALL=C awk -F '\t' \
    -v query="$QUERY" \
    -v ci="$CASE_INSENSITIVE" \
    -v fx="$FIXED_STRING" \
    -v since="$SINCE" \
    -v until="$UNTIL" \
    -v slen="$SNIPPET_LEN" \
    -v max="$MAX_RESULTS" \
    'BEGIN {
       OFS = "\t"; c = 0
       if (ci) q_norm = tolower(query); else q_norm = query
     }
     {
       if (since != "" && $2 < since) next
       if (until != "" && $2 > until) next
       text = $5
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

main() {
  check_deps
  parse_args "$@"
  validate_args
  QUERY="${QUERY_PARTS[*]}"
  precompile_filters

  (
    set +o pipefail
    {
      local project_dir project jsonl
      for project_dir in "$PROJECTS_DIR"/*/; do
        [[ -d "$project_dir" ]] || continue
        project=$(basename "$project_dir")
        [[ "$project" == $PROJECT_GLOB ]] || continue
        while IFS= read -r -d '' jsonl; do
          emit_extracted "$jsonl" "$project"
        done < <(find "$project_dir" -name '*.jsonl' -print0 2>/dev/null)
      done
    } | match_and_format
    rc=$?
    # 141 = SIGPIPE (match_and_format が cap で exit したときに上流が受け取る)。これは正常パス
    [[ $rc -eq 141 ]] && rc=0
    exit "$rc"
  )
}

main "$@"
```

> 注:
> - `find -print0` + `while read -d ''` で空白入りパス対応。`find` 自体の I/O エラーは stderr に出るが、pipeline 全体の exit は subshell + `set +o pipefail` で吸収。
> - `precompile_filters` で jq filter と awk regex を起動前検証。pipeline 内に到達する前に exit code を確定させるため、後段の SIGPIPE/no-match 紛れを構造的に排除。
>
> **実装は性能のため一括 jq 化へ最適化済み。詳細仕様は `bin/session-search.sh` を参照。** Codex final review (loop 1) で以下の差分が入り、骨格と実体が一部乖離している（public contract: 5 カラム TSV / exit code / 出力順序 / SNIPPET 仕様 / DATE 空文字仕様は不変）:
>
> - **PROJECT/SESSION 派生を jq 側に集約**: 骨格は per-file `emit_extracted` + awk で PROJECT/DATE/SESSION を付ける構造だが、実装は `input_filename` と `--arg pdir` で jq 段だけで 5 カラム TSV を直接吐く。awk wrapper 不要。1 ファイル 1 fork ではなく **複数ファイルを 1 jq invocation に流す** ことで起動コスト ×N を排除（T26 5s acceptance）。
> - **xargs バッチ化（H1 対策）**: ファイル数が増えても `getconf ARG_MAX`（Linux 通常 ~2 MB）を超えないよう、`find -print0 | xargs -0 -n 500 jq ...` でバッチ分割。1 batch あたり ~50 KB 程度の argv に収まる。骨格の単一 jq 呼び出しは廃止。
> - **読み取り不能ファイルの事前フィルタ（H4 対策）**: jsonl 列挙時に `[[ -r "$jsonl" ]]` で読めるものだけ通す。`chmod 000` 等のファイルが batch 内の他ファイル処理を巻き込まないようにする。
> - **DATE 正規化（H3 対策）**: jq 側で `timestamp` が `^[0-9]{4}-[0-9]{2}-[0-9]{2}` で始まる場合のみ先頭 10 文字を取り、それ以外は空文字。awk 側で `-s`/`-u` のどちらかが指定されているときは DATE 空の行を skip（lexical 比較で残らないようにする）。
> - **空白正規化を jq から awk へ移動（性能対策）**: 骨格は jq 段で `gsub("[\\t\\n\\r]+"; " ")` していたが、jq の gsub は本ワークロードで awk の ~25× 遅く 5s 予算を破壊するため、awk 側の `gsub` チェーンで sentinel 経由の 4 段正規化に移した。SNIPPET の public contract は help/test-spec.md で「制御文字は半角スペースに正規化、literal `\t` 等は残す」と再記述済み（M5）。
> - **`CLAUDE_PROJECTS_DIR` 末尾スラッシュ正規化（H2 対策）**: スクリプト先頭で `PROJECTS_DIR="${PROJECTS_DIR%/}"`。fixture root を末尾 `/` 付きで渡されても PROJECT カラムが空にならない。
>
> なお project dir 名にタブ・改行を含めることはサポート外（@tsv 経路を信頼する設計上の前提）。サポート対象は Claude Code が `~/.claude/projects/` 配下に生成する path-encoded dir 名（`-home-shohei-...` 形式）のみ。help にも明記。

## テスト計画（手動チェックリスト、fixture ベース）

`project_type: "jobs"` なので自動テストは作らない。`features/$ISSUE/test-spec.md` の手動チェックリストで検証する。**実ユーザログ依存をやめ、`CLAUDE_PROJECTS_DIR` を一時 fixture ディレクトリに切り替えて確定値で検証する**。

fixture 作成手順は test-spec.md に書く（mktemp -d で作る → 既知の jsonl を 2〜3 ファイル書き出す → `CLAUDE_PROJECTS_DIR` で参照）。

| ID | 内容 | 期待値 |
|---|---|---|
| T01_basic_hit | fixture に `Phase 2` を含む user/assistant text を 1 件含めて検索 | 1 件以上の TSV 行が stdout に出る。exit 0 |
| T02_no_match | fixture に該当語の無い QUERY | 0 行 stdout。exit 0 |
| T03_project_filter | fixture に 2 プロジェクト dir を作り `-p '*hermes*'` で片方のみマッチ | PROJECT カラムが `*hermes*` glob に一致する dir 名のみ |
| T04_date_range | fixture に 3 日分の timestamp を入れ `-s 2026-06-23 -u 2026-06-23` | DATE カラムがすべて `2026-06-23` |
| T05_max_limit | fixture に 10 件マッチ、`-n 1` | 行数 1 で打ち切り。exit 0 |
| T06_no_query | 引数なし | usage が stderr。exit 2 |
| T07_help | `-h` | usage が stdout。exit 0 |
| T08_invalid_date | `-s xxxx-xx-xx -- foo` | stderr `invalid date` で exit 2 |
| T09_fixed_string | fixture に `$HOME/.claude` という文字列を含む user message を入れ、`-F '$HOME/.claude'` | 該当行が出る（regex メタ文字エラーなし） |
| T10_snippet_length | 300 バイトの抽出テキストを `-c 50` | SNIPPET カラム長が 50 + `…` 以内（バイト数基準 53 以下） |
| T11_case_insensitive | fixture に `Phase` を含む、`-i PHASE` | 1 件以上 |
| T12_invalid_n | `-n 0 -- foo` / `-n -3 -- foo` / `-n abc -- foo` | stderr `invalid` で exit 2 |
| T13_invalid_c | `-c 0 -- foo` / `-c -3 -- foo` / `-c abc -- foo` | stderr `invalid` で exit 2 |
| T14_since_after_until | `-s 2026-06-30 -u 2026-06-01 -- foo` | stderr `since after until` で exit 2 |
| T15_no_false_positive_tool_use | fixture: user の content array に `tool_result.content` で QUERY 文字列を埋め、本文 text には QUERY なし → 検索 | 該当行が出ない（抽出 jq が `tool_result` を skip するため） |
| T15b_no_meta_match | fixture: timestamp に `2026-06-23` を持つレコード、QUERY=`2026-06-23` | DATE カラムでヒットして本文に無い行が **出ない**（awk が第3列のみ判定） |
| T16_query_dash_prefix | fixture に `-foo` を含む user message、`-- '-foo'` | 該当行が出る |
| T17_max_results_exits_zero | fixture に 1000 件マッチ、`-n 1 -- a` | 1 行で打ち切り、exit 0（SIGPIPE 141 にならない） |
| T18_broken_jsonl | fixture に 1 ファイル中、3 行目を `{not_json` で破損させる | 他の行はマッチし得る、破損行は skip、exit 0 |
| T19_invalid_glob | `-p 'foo|bar'` のように許容外文字 | stderr `invalid` で exit 2 |
| T20_no_projects_dir | `CLAUDE_PROJECTS_DIR=/nonexistent` | stderr `no projects dir` で exit 1 |
| T21_user_string_content | fixture: user の `.message.content` が string のメッセージ | 該当行が出る |
| T22_user_text_block | fixture: user の `.message.content` が `[{type:"text", text:"..."}, {type:"tool_result", content:"..."}]` の混在 | text 部分のみマッチし、tool_result 部分はマッチしない |
| T23_assistant_thinking | fixture: assistant の `.message.content` に `[{type:"thinking", thinking:"..."}]` のみ | thinking 部分でマッチ |
| T24_skip_other_types | fixture: `attachment` / `last-prompt` / `mode` / `queue-operation` レコード | 何もマッチしない |
| T25_subagent_jsonl | fixture: `<proj>/<uuid>/subagents/agent-X.jsonl` の階層 | 抽出対象に含まれる（subagent も検索できる）。PROJECT カラムは root 直下 `<proj>` 名（`subagents` や UUID にならない） |
| T26_perf_acceptance | 実環境 `~/.claude/projects/` に対して `time bin/session-search.sh 'Phase 2' >/dev/null` | **5 秒以内（acceptance criterion）**。超過時は本 plan の一段化を撤回し、本 Issue 内で grep prefilter（false negative 許容仕様で `-F` 限定で復活）または FTS5 切替を検討する。merge までに 5s 以内を満たすこと |
| T27_invalid_regex | regex モードで `'['` のような不正パターンを与える | stderr `invalid regex` で exit 2 |
| T28_text_with_tab_newline | fixture: text 本文に literal tab `\t` (実 0x09) と改行 `\n` (実 0x0A) を含むレコード | 抽出後の TSV 行は **常に 5 カラム**（jq 段の `gsub` で制御文字を空白化済み）。awk が `text ~ query` で誤って列をまたがない |
| T29_assistant_string_content | fixture: `type=assistant` の `.message.content` が string 型（旧形式・移行期形式） | assistant string content の本文でマッチ・抽出される |
| T30_legacy_fail_safe | fixture: `.message` 欠落 / `.message.content=null` / text block の `.text=null` / 非 string `.text` を含むレコード | jq の `select(type == "string" and . != "")` で fail-safe skip。エラーにならず exit 0、他の正常レコードはマッチし得る |

退化 / 境界: T02 / T05 / T06 / T08 / T10 / T12 / T13 / T14 / T15 / T15b / T16 / T17 / T18 / T19 / T20 / T22 / T24 / T27 / T28 / T29 が該当。

### Smoke test script

`features/$ISSUE/smoke-test.sh` を test-spec.md と一緒に置く（手動チェックリストでは自動化しきれない exit code / 5 カラム TSV / SIGPIPE 安全性を確実に検証するため）。CI には組み込まないが、`bash features/$ISSUE/smoke-test.sh` 一発で fixture 作成 → 主要ケース実行 → 期待値 assert ができる雛形:

- fixture jsonl を mktemp -d に書き出し
- `CLAUDE_PROJECTS_DIR=$tmp bin/session-search.sh ...` を主要ケースで呼ぶ
- exit code / 行数 / 5 カラム / SIGPIPE 141 にならないこと、を `[[ ]]` で assert

## Issue body 抜粋

## 目的

`~/.claude/projects/*/` 配下の全セッション JSONL を横断検索し、「前にあの話どこでしたっけ」を即解決できるようにする。本家 Hermes は FTS5 + LLM 要約だが、Hermes-lite はコストゼロ運用が制約なので LLM 要約層は省き、grep / FTS5 のテキスト検索のみで現実解とする。

## 詰めるべき論点 → 本 plan での決着

- 配置: → `bin/session-search.sh`
- インデックス方式: → grep で十分（57MB / 218 file で実測 <1s）。FTS5 は将来 follow-up
- 出力: → TSV（PROJECT / DATE / SESSION / TYPE / SNIPPET）
- 古いセッション: → 絞らず全件対象

## 非スコープ（Issue 再掲）

- LLM 要約 / セマンティック検索
- Web UI
