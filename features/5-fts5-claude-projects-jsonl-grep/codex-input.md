# Non-Goals (本 Issue で実装しない項目 — Codex は越権指摘しないこと)
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

# In-Scope / Out-of-Scope
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

# Test summary
```json

```

# ci.log (tail 30 lines)
```
ok: T01_basic_hit (4 lines)
ok: T02_no_match
ok: T06_no_query
ok: T07_help
ok: T08_invalid_date
ok: T12_invalid_n
ok: T14_since_after_until
ok: T15_no_false_positive_tool_use
ok: T15b_no_meta_match
ok: T16_query_dash_prefix
ok: T17_max_results_exits_zero
ok: T18_broken_jsonl
ok: T20_no_projects_dir
ok: T22_user_text_block
ok: T27_invalid_regex
ok: T29_assistant_string_content
ok: T30_legacy_fail_safe
ok: T03_project_filter (3 lines)
ok: T04_date_range
ok: T05_max_limit
ok: T11_case_insensitive
ok: T25_subagent_jsonl
ok: T28_text_with_tab_newline
ok: T31_non_iso_timestamp
ok: T32_unreadable_file
ok: T33_many_files
ALL PASS

```
