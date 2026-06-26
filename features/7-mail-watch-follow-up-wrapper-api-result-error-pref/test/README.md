# Issue #7 integration harness

`bin/run-claude.sh` の wrapper API 整理（`SUPPRESS_EMPTY_RESULT` / `RESULT_ERROR_PREFIX` 追加）の退行検出用 integration harness。

## 実行

```bash
cd ~/hermes-lite
bash features/7-mail-watch-follow-up-wrapper-api-result-error-pref/test/run-harness.sh
```

成功時: 各 T-ID で `PASS: <T-ID>` を出し、最後に `ALL PASSED (N tests)`。
失敗時: `FAIL: <T-ID>: <reason>` を出して exit 1。

## 必要なコマンド

`bash`, `jq`, `mktemp`, `printf`, `diff`, `grep`, `git`（T07 / T08 / T10 で repo の diff / grep を行うため）

## 構造

```
test/
  README.md             # このファイル
  run-harness.sh        # メインエントリ
  fixtures/
    stub-claude.sh      # CLAUDE_BIN stub。$STUB_CLAUDE_JOB_FILE 経由で job ID を受けて固定 JSON を返す
    hermes-home/        # HERMES_HOME として与える隔離 fixtures
      .env              # DISCORD_WEBHOOK_URL=https://stub.invalid + DEFAULT_* defaults
      bin/run-claude.sh # 本体への symlink: ../../../../../../bin/run-claude.sh
      lib/
        notify.sh       # stub。notify_discord は $STUB_DISCORD_LOG に append するだけ
        disallowed-tools.txt  # 本体への symlink
      jobs/
        t01-default-compat/{prompt.md, job.env}
        t02-empty/{prompt.md, job.env}                # SUPPRESS_EMPTY_RESULT=1
        t03-empty-default/{prompt.md, job.env}
        t04-error-default/{prompt.md, job.env}
        t05-error-disabled/{prompt.md, job.env}       # RESULT_ERROR_PREFIX=""
        t06-error-custom/{prompt.md, job.env}         # RESULT_ERROR_PREFIX="[ERR]"
        t09-suppress-bad-value/{prompt.md, job.env}   # SUPPRESS_EMPTY_RESULT="2" (silent false)
```

実行のたびに `mktemp -d` で `$STUB_DIR` を作り、各実行の stderr / discord log / exit code を `$STUB_DIR/<t-id>.{stderr,discord,exit}` に保存する。`trap` で必ず cleanup される。

## drift mitigation（本体と harness の同期規律）

**`bin/run-claude.sh` を変更したら、必ず本 harness を再実行して全 T-ID が PASS することを確認すること**。具体的には:

1. wrapper 変数を追加した場合: `docs/wrapper-api.md` 表に行追加 + 本 harness に fixture job 追加
2. wrapper の通知分岐ロジックを変更した場合: 既存 T-ID の期待値が古くないか確認 + 必要に応じて期待値更新
3. `lib/disallowed-tools.txt` を変更した場合: `fixtures/hermes-home/lib/disallowed-tools.txt` は symlink なので追従されるが、影響範囲を確認

`docs/wrapper-api.md` 末尾の「harness 同期規律」セクションと整合する。

## 関連

- `../plan.md` — 全体設計
- `../test-spec.md` — 期待値チェックリスト（各 T-ID）
- `../rejection.md` — Codex 指摘の採否ログ
- `../../docs/wrapper-api.md` — wrapper API ドキュメント本体
