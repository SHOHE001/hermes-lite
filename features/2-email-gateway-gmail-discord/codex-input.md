# Non-Goals (本 Issue で実装しない項目 — Codex は越権指摘しないこと)
- 双方向対話（mail-watch 通知に対するユーザー返信ハンドリング）
- Gmail 以外のメールプロバイダ対応
- 添付ファイル取得
- メール本文の長文要約（1 行要約に留める）
- 既読化済み既存メールの自動移行

# In-Scope / Out-of-Scope
| In-Scope | Out-of-Scope |
|---|---|
| `jobs/mail-watch/{prompt.md, job.env}` 新規作成 | カレンダー登録などの後段アクション（Issue #3） |
| `docs/jobs-mail-watch.md` セットアップ手順を新規追加 | mail-watch 以外のジョブの仕様変更 |
| `bin/run-claude.sh` を 2 点改修（下記）| `lib/notify.sh` / `lib/disallowed-tools.txt` / systemd templates の改変 |
| 6h ごと polling（drop-in 例を docs に明記） | テスト自動化フレームワーク導入 |
| Gmail thread ラベル `hermes-lite` → `hermes-lite/done` 付け替え | Calendar / Notion 書き込み |
| 1 Discord 投稿に最大 10 thread 集約（plain） | embed リッチカード |
| 0 件のときは Discord に投稿しない（wrapper 側で空 result を判定） | 既読化済み既存メールの一括移行（手動運用） |

### `bin/run-claude.sh` 改修内容

1. **`.env` の export 強制**: 現在の `source "$HERMES_HOME/.env"` を `set -a; source "$HERMES_HOME/.env"; set +a` に変更し、`KEY=value` 形式でも subprocess（claude プロセス）に環境変数が承継されることを保証する
2. **空 result の Discord 投稿スキップ**: 現在の `notify_discord "[$JOB_NAME] ${RESULT_TEXT:-(no result text)}"` を、`RESULT_TEXT` が空文字 or `[NOOP]` のときは `notify_discord` を呼ばないように変更

これらは全 job に影響するが:
- 改修 1 は「export 付き .env を書けば動く現状」の上位互換（既存 .env は引き続き動作）
- 改修 2 は ping job など「必ず非空 result を返す job」には無影響

# Test summary
```json

```

# ci.log (tail 30 lines)
```
syntax: OK (bash -n bin/run-claude.sh passed)
ping regression: skipped (user .env required)

```
