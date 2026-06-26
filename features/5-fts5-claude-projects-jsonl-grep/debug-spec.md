# debug-spec: #5 Codex final review (loop 1) で指摘された修正項目

implementer に再委譲する修正項目。**実装の出力フォーマットや CLI 引数は変えず**、内部のロバスト性と仕様文の整合を直す。

## 修正項目（severity 順）

### H1. ARG_MAX 問題（contrarian.high #1 / migration.high #1）

- 症状: 現在 `find` の結果を bash 配列 `files` に貯めて `jq ... "${files[@]}"` で一括起動している。ファイル数が増えると OS の argv サイズ上限 (`getconf ARG_MAX`、Linux 通常 ~2MB) を超えて jq の exec が `Argument list too long` で失敗する。`set +o pipefail` 配下なので producer 失敗が consumer に伝播せず、サイレントに 0 件を返す
- 修正: `find -print0 | xargs -0 -n <BATCH_SIZE>` 相当でバッチ分割する。`BATCH_SIZE=500` を目安にする（典型パス長 ~100 バイトで 50KB/batch、ARG_MAX の 1/40）。または `find` の結果を `while read -d ''` で stream 処理し、1 batch につき 1 jq 起動
- 検証: 大量ファイル fixture（1000+ jsonl）を smoke に追加し、`ARG_MAX` を超えないことを実測

### H2. CLAUDE_PROJECTS_DIR の末尾スラッシュ（contrarian.high #2）

- 症状: `CLAUDE_PROJECTS_DIR=/path/to/projects/` のように末尾 `/` 付きで渡すと、jq の `($pdir + "/")` が `/path/to/projects//` になり、`ltrimstr` が失敗。PROJECT カラムが空 or 誤った dir 名になる
- 修正: スクリプト先頭で `PROJECTS_DIR="${PROJECTS_DIR%/}"` で末尾スラッシュを正規化
- 検証: smoke に `CLAUDE_PROJECTS_DIR=$tmp/` ケースを追加

### H3. 非 ISO timestamp の DATE 正規化（contrarian.high #3 / migration.high #2）

- 症状: help は「timestamp が missing/non-ISO の場合 DATE は空文字、`-s`/`-u` 指定時は除外」と書いてあるが、実装は `($r.timestamp // "")[0:10]` をそのまま使う。`zzzzzzzzzz` のような非 ISO 文字列はそのまま DATE になり、`-u 2026-01-01` でも文字列比較で残る
- 修正: jq 側で DATE を `if ($ts | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}")) then $ts[0:10] else "" end` で正規化。awk 側で `-s`/`-u` のどちらかが指定されているときは DATE 空の行を skip
- 検証: smoke に T31_non_iso_timestamp を追加（fixture で `"timestamp":"zzz"` と `"timestamp":""` の行を入れ、`-u 2026-01-01` で除外されることを確認）

### H4. 読み取り不能 jsonl の silent skip 契約（architect.high #2 / migration.high #1）

- 症状: help/plan は「ファイル単位で silent skip」と書いてあるが、現在は全ファイルを単一 jq invocation に渡すため、jq が途中ファイルの open/read error で全体中断する可能性がある（pipeline は `set +o pipefail` で exit 0 になるが、読める後続ファイルもサイレントに truncate）
- 修正: 候補 jsonl 列挙時に `[[ -r "$jsonl" ]]` で読み取り可能なものだけ通す。H1 のバッチ分割と組み合わせれば、batch 内で 1 ファイル fail しても他 batch は走る
- 検証: smoke に T32_unreadable_file を追加（`chmod 000 a.jsonl` で読めなくし、`b.jsonl` のヒットが残ることを確認）

### M5. SNIPPET の help 表現と実装のズレ（migration.medium #4）

- 症状: help は「SNIPPET is jq @tsv-escaped form (literal `\t`/`\n` sequences appear as `\\t`/`\\n`)」と書くが、実装は SOH sentinel 経由で `\t`/`\n`/`\r` を空白化し backslash を復元している
- 修正: help を実装に合わせて書き換える: 「SNIPPET is the extracted text with control characters (tab/newline/CR) normalized to single spaces. Literal backslash sequences (e.g. `\\t` in source) are preserved as-is.」

### M6. plan.md と実装の乖離（architect.medium #3）

- 症状: plan.md の `## 実装対象` の骨格は per-file `emit_extracted` 構造だが、実装は一括化されている
- 修正: plan.md の骨格を **実装に追従させて更新**（あるいは update した plan.md の骨格セクションに「実装は性能のため一括 jq 化へ最適化済み、詳細は `bin/session-search.sh` 参照」と注記）

### M7. smoke-test の範囲拡大（architect.medium #4 / contrarian.medium #4 / migration.high #3）

- 症状: ci.log は smoke の主要 ID（T01/T02/T06/T07/T08/T12/T14/T15/T15b/T16/T17/T18/T20/T22/T27/T29/T30）のみで、public contract の主要機能（project filter / date range / case-insensitive / subagent / tab-newline）が未検証
- 修正: smoke-test に T03 / T04 / T05 / T11 / T25 / T28 を **追加**（既存テスト範囲に統合）。ci.log を再生成
- 加えて、上記の修正で追加した T31_non_iso_timestamp / T32_unreadable_file も smoke に含める

### M8. PROJECT/SESSION の @tsv エスケープと public contract（architect.high #1）

- 症状: jq が `[$project, date, session, type, text] | @tsv` で出力するため、project/session に tab/newline が含まれる場合 @tsv エスケープされる。Claude Code の通常 dir 名（`-home-shohei-...`）にはタブ・改行は入らないが、`CLAUDE_PROJECTS_DIR` 経由で fixture root に異常名を渡されると壊れる
- 部分対応: help と plan.md に「project dir 名にタブ・改行を含めることはサポート外。サポート対象は Claude Code が生成する dir 命名規約のみ」と明示。実装変更はしない（追加コストに見合わない）

## 各修正対応後の検証

1. `bash -n bin/session-search.sh` で syntax check
2. `bash features/5-fts5-claude-projects-jsonl-grep/smoke-test.sh` で全 case PASS
3. 拡大した ci.log を `features/5-fts5-claude-projects-jsonl-grep/ci.log` に上書き
4. `time bin/session-search.sh 'Phase 2' >/dev/null` が依然 5 秒以内

## 報告

最後に以下を出力:

```
- fixes applied: H1/H2/H3/H4/M5/M6/M7/M8
- new smoke cases: T31, T32 (and added T03/T04/T05/T11/T25/T28 to smoke)
- ci.log result: ALL PASS (NN/NN)
- T26_perf re-measure: XX.X s
- plan.md updated: yes/no
- help updated: yes/no
```
