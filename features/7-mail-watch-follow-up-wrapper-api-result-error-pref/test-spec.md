# test-spec for #7 mail-watch follow-up: wrapper API 整理

project_type=jobs のため自動テストフレームは無し。`features/7-.../test/run-harness.sh` を実行して各 T-ID の結果をチェックする。

## 前提セットアップ

- main から `gloop/7-mail-watch-follow-up-wrapper-api-result-error-pref` ブランチを checkout
- `bin/run-claude.sh` の実装が完了している
- `features/7-.../test/run-harness.sh` および fixtures 配下のファイルが配置済み
- harness 実行に必要なコマンド: `bash`, `jq`, `mktemp`, `printf`, `diff`, `grep`

## コマンド

```bash
cd ~/hermes-lite
bash features/7-mail-watch-follow-up-wrapper-api-result-error-pref/test/run-harness.sh
```

成功時は各 T-ID で `PASS: <T-ID>` を stdout に出し、最後に `ALL PASSED (N tests)` を出す。失敗時はその T-ID で `FAIL: <T-ID>: <reason>` を出して exit 1 する。

## 期待値（チェックボックス）

### T01_default_compat
- [ ] stderr に `OK exit=0` を含む
- [ ] `$STUB_DISCORD_LOG` に `[t01-default-compat] ok` の 1 行（既存挙動）

### T02_empty_suppress
- [ ] stderr に `empty result + SUPPRESS_EMPTY_RESULT=1 — skipping Discord post` を含む
- [ ] `$STUB_DISCORD_LOG` が空ファイル

### T03_empty_default
- [ ] stderr に `OK exit=0` を含む
- [ ] `$STUB_DISCORD_LOG` に `[t03-empty-default] (no result text)` を含む（既存挙動維持）

### T04_error_default
- [ ] stderr に `FAIL via ERROR: prefix in result` を含む（末尾の `(...)` なし、既存 grep 互換）
- [ ] `$STUB_DISCORD_LOG` に `FAIL exit=0` を含み、`ERROR: stub fail` も含む

### T05_error_disabled
- [ ] stderr に `OK exit=0` を含む（prefix 検出が無効化されている）
- [ ] `$STUB_DISCORD_LOG` に `[t05-error-disabled] ERROR: stub fail` を含む

### T06_error_custom_prefix
- [ ] stderr に `FAIL via ERROR: prefix in result (` を含む（`printf %q` 出力で prefix 値 `[ERR]` が `\[ERR\]` のような shell-safe quote 形式で付随）
- [ ] `$STUB_DISCORD_LOG` に `FAIL exit=0` を含み、`[ERR] stub fail` も含む

### T07_mail_watch_dryrun
- [ ] `git diff main -- jobs/mail-watch/` の出力が空（mail-watch は無変更）

### T08_docs_review
- [ ] `git diff main -- docs/jobs-mail-watch.md` に `ログから回復` 削除が含まれる（`-` 行で `.result や stderr で発見可能` が出る）
- [ ] `grep -c '^| `[A-Z_]\+`' docs/wrapper-api.md` で `>= 10`（10 変数記載）
- [ ] `grep` で `SUPPRESS_EMPTY_RESULT` と `RESULT_ERROR_PREFIX` が docs/wrapper-api.md に存在

### T09_suppress_bad_value
- [ ] stderr に `OK exit=0` を含む
- [ ] `$STUB_DISCORD_LOG` に `[t09-suppress-bad-value] (no result text)` を含む（`"2"` は silent false なので既定挙動）

### T10_grep_compat
- [ ] `grep -rn 'FAIL via ERROR' --include='*.md' --include='*.sh' --include='*.py' --include='*.mjs' --include='*.js' .` のヒットが `bin/run-claude.sh` の 1 行のみ（`docs/` と `features/` 配下は plan/test-spec/wrapper-api 等の説明記述で本文言を引用しており、コードの挙動には影響しないため harness 側で除外）
- [ ] `grep -rE '^(SUPPRESS_EMPTY_RESULT|RESULT_ERROR_PREFIX)=' jobs/ features/` の出力が空（本 Issue で追加する `features/7-mail-watch-follow-up-wrapper-api-result-error-pref/` 配下は harness 側で除外）

## 実行戦略

light flow 運用のため、harness は 1 回実行して全 T-ID を順次検証する。失敗時は該当 T-ID と stderr/discord log を保持し、`bin/run-claude.sh` を再修正後に再実行。
