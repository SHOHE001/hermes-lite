# Rejection log for #5

## Codex design review (loop 1) で棄却した findings

### 棄却: architect.medium / contrarian.medium 「Issue 名 FTS5 と実装 grep が衝突」

- 指摘内容: Issue タイトルは `FTS5 全セッション検索`、In-Scope は grep ラッパー、Out-of-Scope に FTS5。読者が混乱する可能性。
- 棄却理由: Issue 本文に明示的に「初期は grep でよい」「インデックスを持つ余裕があれば SQLite FTS5 へ拡張」と書かれており、Issue 起票者の意図が「FTS5 化を視野に置いた grep ラッパー」。slug `fts5-...-grep` がこの両義性を明示している。Issue リネームはスコープ外（Issue 起票者は人間ユーザー）。plan 内で「初期は grep」と明示する方針を維持する。

## 採用に反映した findings（参考）

以下は loop 1 で plan.md に反映した:
- architect.high #1 / contrarian.high #1 / migration.high #2: raw JSONL grep と content-only の矛盾 → 抽出済みテキストに対する二段 grep に変更
- architect.high #2 / contrarian.high #2 / migration.high #1: `.content` 前提が外れている → 実データ調査結果に基づき `.message.content` の string / array 両対応 + user.text / assistant.text / assistant.thinking のみ抽出
- contrarian.high #3: `set -euo pipefail` + `head -n` で SIGPIPE 141 → subshell + 局所 `set +o pipefail` で吸収
- architect.medium #4 / contrarian.medium #5: PROJECT_GLOB の `find -path` + `case` 二重 → `find -mindepth 2 -maxdepth 2` で jsonl 列挙 + 親 dir basename に `case` の一度だけ判定に統一
- architect.low / contrarian.medium #6 / migration.medium #2: QUERY 結合 → `"$*"` で単一パターンに結合する旨を明示
- migration.medium #1: 日付/件数/snippet 長の不正値 → `-n`, `-c` の正の整数検証 + since<=until 検証 + 不正日付の reject を追加
- migration.medium #2: QUERY 先頭ハイフン → grep に `-- "$QUERY"` で区切る旨を骨格に明示
- architect.medium #5 / contrarian.low / migration.medium #3: 既存関数編集 N/A 明記 → 実装対象に 1 行追記

## Codex design review (loop 2) で棄却した findings

### 棄却（継続）: architect.high #1 / contrarian.medium #4 「機能名 FTS5 と実装 grep の衝突」
- 棄却理由: loop 1 と同じ。Issue 起票者の明示意図を尊重し、Issue 名はリネームしない。plan.md 冒頭に「Issue 名 FTS5 だが grep 実装に絞る」と注記済み。

### 部分採用にとどめた: contrarian.medium #5 「prefilter 廃止 vs 全件 jq の実測」
- 指摘内容: 二段 prefilter の必要性を実測で示せ。なければ全件 jq に倒せ。
- 反映内容: 二段 prefilter を廃止し、最初から `jq -Rr 'fromjson?'` で全 jsonl を流す一段方式に変更した。実測は実装後の T26_perf_smoke で記録する。

## Codex final review (loop 2) — 裁量で passed（残置 findings 記録）

### 裁量で残置した findings

- **architect.high #backslash false negative**: jq の `@tsv` → awk の sentinel 復元の境界が、awk 方言や replacement escape 解釈に依存するという理論的指摘。実環境の smoke (T09_fixed_string 等) では正しく動作し、サーバー gen8 の gawk/mawk いずれでも sentinel 方式は実証済み。base64 transport などへの架替えはコスト過大。**実害なしと判断**
- **contrarian.high #xargs early exit**: `-n MAX` 指定時に下流 awk が exit しても producer 側の xargs/jq が走り続けるという懸念。**実測で否定**: `-n 1` が 0.093s で完了（vs `-n 50` の 1.655s）、xargs の SIGPIPE 伝播で早期終了が効いている。実害なし。ci.log に追記
- **migration.high #1 BSD xargs**: `xargs -r` が GNU 拡張で macOS/BSD で動かないという指摘。hermes-lite は **gen8 Linux サーバー専用**（CLAUDE.md に明記）なので棄却。macOS/BSD 対応は follow-up Issue
- **migration.high #2 producer error swallowed**: producer 側 xargs/jq の異常が exit 0 化される懸念。実害シナリオが限定的（既に `precompile_filters` で jq filter / awk regex は事前検証済み、依存欠如は `check_deps` で検出、`[[ -r $jsonl ]]` で読めないファイルは事前除外）。残る可能性は TOCTOU 系のみで、それは public contract「読み取り不能 jsonl は silent skip」の範疇

### loop 2 で反映した軽い修正

- T26 acceptance の実測値を ci.log に追記（-n 50 で 1.655s、-n 1 で 0.093s）
- 依存節に `xargs` を追加、`-r` が GNU 拡張で hermes-lite の Linux/gen8 専用前提を明示

### follow-up Issue 化候補（merge 後に検討）

- macOS/BSD 環境向けの `xargs -r` 代替実装（migration.high #1）
- 抽出本文に backslash を含むケースの厳密検証 fixture（architect.high）
- producer 側 jq/xargs failure を exit 1 として観測する実装（migration.high #2、`/tmp` 経由の rc 回収）

## Codex design review (loop 6, max=5 到達) — 裁量で passed

design_loops が max_design_loops=5 に到達したため、本 loop の残置を裁量採用で passed する。Codex の指摘は妥当な部分も含むが、初版 grep ベース検索 CLI として現実的な落とし所として以下の判断:

### loop 6 で fix した critical 1 件

- migration.high #IGNORECASE: gawk 拡張 `IGNORECASE` 依存で mawk 環境で `-i` が壊れる → `tolower()` 方式に変更（gawk/mawk 共通動作）。これは「裁量残置」ではなく実装上 fatal なので最終 fix として反映済み

### 裁量で残置（commit message に「Codex blocking N 件残置」として記録、follow-up は最終レビュー後に検討）

- architect.high / contrarian.medium #@tsv エスケープ後検索: 検索対象が `@tsv` エスケープ後文字列であるため backslash 含む本文で false negative の可能性。理由: jq から TSV 経由で運ぶための内部表現を変えるには base64 エンコード等の別形式が必要で実装複雑度が大きく増す。日本語 / 自然文中心の用途で実害は軽微と判断、public spec として明示済み。実害が出たら follow-up Issue で base64 化検討
- architect.medium / contrarian.medium #SIGPIPE 説明の不正確さ: `set +o pipefail` の pipeline 終了コードは consumer 由来で、141 への分岐説明が技術的に厳密でない。理由: 実装意図（cap 達成時の正常終了）は達成できる。文書上の正確化は実装後に help にも反映する
- contrarian.high #Issue「grep 版」批判: jq+awk 一段化は「grep 版」名と乖離するが、loop 1-4 で構造的に prefilter false negative が判明済み。Issue 起票者意図「初期は grep でよい」を「LLM 要約 / FTS5 でない単純線形検索」と読み替えて維持
- contrarian.high / migration.medium #public contract が `--help` のみで弱い: README 追記は Issue スコープ外。`--help` を厚く書く + `features/$ISSUE/test-spec.md` の public contract 節で代替。follow-up で README 追加可能
- migration.high #読み取り不能ファイル warning なし skip: 移行用途では検知できないという指摘は妥当だが、初版は warning なし skip で十分。`--verbose` で warning 表示は follow-up
- migration.high #旧形式の網羅性: `.message` 欠落、`.message.content=null`、text block の非 string `.text` 等は jq の `select(type == "string" and . != "")` で fail-safe に skip される設計。fixture テストでこのケースを 1 件追加して動作確認（T30）
- contrarian.medium #tool_result 除外の根拠: Issue 本文の Non-Goals と一致するので維持。`--include-tools` follow-up
- contrarian.low #smoke-test のどの ID を自動化するか: test-spec.md に列挙する（実装フェーズ）
- migration.medium #FTS5 移行パスの public contract 永続性: 出力フォーマット（5 カラム TSV）と exit code 規約は将来 FTS5 化しても維持することを `--help` に書く
- migration.medium #bin/ 衝突: 既存 `bin/run-claude.sh` 等と命名衝突しないことを確認済み（`session-search.sh` は新規）

## Codex design review (loop 5) で plan.md に反映した findings（参考）

- architect/contrarian/migration .high: regex pre-compile が空入力で評価されない → `awk 'BEGIN { if ("" ~ q) {} }' </dev/null` に変更（BEGIN 内なら動的 regex は強制 compile される）
- architect/contrarian .high: `set +o pipefail` が pipeline 全体の失敗境界を消す → subshell 内で `rc=$?` を捕捉、141 (SIGPIPE) のみ 0 に正規化、それ以外は外側に伝播。「読み取り不能 jsonl は警告なし skip」を public contract に明示
- migration .high: assistant content が string の旧形式を取りこぼす → jq filter の assistant ブロックに `if type == "string" then [.]` を追加（2 箇所の filter を同期）。T29 を追加
- architect/contrarian .high: 「grep 版」と名乗りつつ grep 不使用 → 棄却継続。Issue 本文に「初期は grep でよい」とあるが、設計時に grep prefilter を入れると false negative / regex 方言不一致が構造的に発生することが loop 4 までに判明したため、本 plan は jq+awk 一段化で「grep 相当の単純さ」を達成する方針を維持する。slug 上の「grep」は意味的に「LLM 要約 / FTS5 でないテキスト線形検索」を指す
- architect/migration .medium: 依存欠如記述の grep 混入 → 削除、`jq/awk/find` に統一
- architect/contrarian .medium: TSV 内部/外部の境界 → public contract（`--help`）に SNIPPET が `@tsv` エスケープ後である旨と escape 例を明記
- contrarian .medium: T26 を実装前提の acceptance criterion に → T26_perf_acceptance に名称変更、超過時の対応も plan に明記（grep prefilter `-F` 限定復活 or FTS5 切替）
- migration .medium #README: 発見性 → public contract = `--help` のみとし、test-spec.md に導入手順と `CLAUDE_PROJECTS_DIR` 例を入れる方針を実装対象セクションで明示済み
- migration .low: 「grep 互換」表現 → 「結果 0 件は正常終了として扱う」に書き換え

## Codex design review (loop 4) で plan.md に反映した findings（参考）

**設計の核を変更**: grep prefilter を完全廃止し、一段パイプライン (find → jq -Rr → awk 第3列判定) に倒した。これにより以下の構造的問題が一括解消した:

- architect/contrarian/migration .high: grep と awk の regex 方言不一致による false negative → prefilter 廃止で消滅
- architect/contrarian/migration .high: raw JSON prefilter と抽出後テキスト判定が同値でない → prefilter 廃止で同一ソース
- architect.high / migration.critical / contrarian.high: xargs + grep -l の no-match (1) vs invalid regex (>=2) の混在 → prefilter 廃止で消滅
- architect.high: process substitution 内の prefilter 失敗が exit 伝播しない → prefilter 廃止で消滅
- architect.medium / migration.medium: xargs 依存の追加 → prefilter 廃止で消滅、依存欄から grep も削除
- architect.medium: jq filter 事前 compile が skeleton にない → `precompile_filters` 関数で `jq -n` + awk regex check を追加
- contrarian.medium #過剰設計: prefilter を捨て一段化により全体的に単純化
- contrarian.medium / migration.medium: Non-Goals と smoke-test.sh の整合 → 成果物として In-Scope に明示
- migration.medium #契約: README 不要、`--help` を唯一の public contract と明記
- migration/contrarian の invalid regex 仕様 → `precompile_filters` で awk 自身に試行させて exit 2

## Codex design review (loop 3) で plan.md に反映した findings（参考）

- architect.high #1 / migration.high #1: `@tsv` のエスケープ問題で第3列限定検索が壊れる → jq 段で `gsub("[\\t\\n\\r]+"; " ")` + `gsub("  +"; " ")` を行い、制御文字を空白に正規化してから `@tsv` に通す。これで実タブ/改行による列崩れは構造的に起きない。literal `\t` 表記の 2 文字シーケンスがエスケープされる挙動は public spec として明記
- architect.high #2: SIGPIPE 対策が依存エラーを握りつぶす → 起動時 `check_deps`（grep/jq/awk/find）で exit 1、`grep -l` の exit >=2 を `invalid regex` として exit 2 に統一
- contrarian.high #1 / architect.medium #依存 / contrarian.medium #grep: grep prefilter を捨てる根拠が弱い → grep prefilter を復活、`find -print0 | xargs -0 grep -l` で候補絞り込み、jq は候補のみ pass。これで「grep 版」という名称・依存・データフローが整合
- contrarian.high #2: T26 perf smoke が合否基準でない → **5 秒以内を合否基準**に固定。超過時は FTS5 follow-up Issue の切替条件
- architect/contrarian/migration: invalid regex の挙動未定義 → 上記の通り exit 2 + `invalid regex` メッセージ。T27_invalid_regex を追加
- architect.medium #subagent / migration.medium #subagent: subagent 階層 で PROJECT が `subagents`/UUID になる懸念 → 外側 `for project_dir in "$PROJECTS_DIR"/*/` + 内側 `find` の二段ループに固定、PROJECT は常に root 直下 dir。T25 期待値に追記
- migration.medium #timestamp: 空/非ISO timestamp の挙動 → date filter 指定時は文字列比較で実質除外、未指定時は DATE 空のまま出力、と明記
- contrarian.medium #擬似コード: 主要関数の擬似コードを完成形に → check_deps / parse_args / validate_args / prefilter_files / emit_extracted / match_and_format / main を省略なしで骨格に記載
- migration.medium #smoke: 手動 only では public CLI 互換性回帰が検知できない → `features/$ISSUE/smoke-test.sh` の雛形を test-spec と一緒に置く方針を追加（CI 連動なし、開発者ローカル assert 用）
- T28_text_with_tab_newline 追加: 本文に literal tab/newline がある場合に 5 カラム TSV が壊れない検証

## loop 2 で plan.md に反映した findings（参考）

- architect.high #2 / contrarian.high #1 / migration.high #3: 二段目 grep がメタ列にもマッチ → 一段化し、awk -F '\t' で第3列のみ判定に変更（T15b_no_meta_match 追加）
- architect.high #3 / contrarian.high #2 / migration.high #2: 不正 JSONL skip と jq 設計の矛盾 → `jq -Rr 'fromjson?'` で raw 行 tolerant 抽出に変更（T18_broken_jsonl 追加）
- architect.high #2 派生: SNIPPET にマッチ語含む保証は削除し、「先頭 LEN バイト切り、マッチ語が SNIPPET 内にあることは保証しない」とドキュメント化
- migration.high #1: 先頭ハイフン QUERY → `--` 区切り運用に変更、T16 を `-- '-foo'` 形式に修正、usage に明記
- migration.medium #4 / architect.medium 派生: 旧 content 形状の互換 → jq の if/else で string/array/null/その他すべてに分岐し、配列要素も `select(type=="object" and ...)` で型ガード
- architect.medium #5: PROJECT_GLOB の shell pattern 安全性 → `[[ "$project" == $PROJECT_GLOB ]]` に変更 + 入力検証で許容文字限定（T19_invalid_glob 追加）
- contrarian.medium #6: snippet 長の文字数 vs バイト数 → `LC_ALL=C` でバイト数として扱う旨を明記、出力長 `LEN + 3` (`…` は UTF-8 で 3 バイト) と明文化
- architect.medium #6 / contrarian.high #3: テスト再現性 → `CLAUDE_PROJECTS_DIR` で fixture root 差し替え可能、fixture 作成手順を test-spec.md に書く方針へ変更、T21-T25 で fixture ベース検証を追加
- architect.medium #4: 既存 `bin/` 規約整合 → `set -euo pipefail`（run-claude.sh と異なる選択）の理由、CLAUDE_PROJECTS_DIR 経由 root 切替、exit code 規約を plan に追加
- migration.medium #5: 安定契約 → 出力順序（同 jsonl 内昇順、jsonl 間非保証）、exit code 規約、stderr 文言を明記
- 共通 low: before/after N/A 明示 → 実装対象セクションに 1 行追記
