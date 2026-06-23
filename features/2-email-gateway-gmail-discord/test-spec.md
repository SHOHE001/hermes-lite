# test-spec: #2 mail-watch（手動チェックリスト）

Hermes-lite は自動テスト基盤が無いため、`bin/run-claude.sh mail-watch` 実機試走で確認する。

## 前提セットアップ

実機テスト前に以下を整える:

1. Gmail 側で 2 ラベル作成: `hermes-lite`, `hermes-lite/done`
2. `.env` に `DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...` を 1 行追加（export 付きでも無しでも OK）
3. `bin/run-claude.sh` が以下の改修済みであること（実装時に確認）:
   - `set -a; source $HERMES_HOME/.env; set +a`
   - 末尾の `notify_discord` 直前に `SUPPRESS_RESULT_IF` チェック

## チェックリスト

### T01_zero — 0 件時は何も流さない

```bash
# 前提: Gmail に `hermes-lite` 未読が 0 件
bin/run-claude.sh mail-watch
```

期待:
- [ ] Discord に何も投稿されない
- [ ] `logs/mail-watch/<ts>.json` の `.result == "[NOOP]"`
- [ ] `.is_error == false`
- [ ] `logs/mail-watch/<ts>.stderr` に `result matched SUPPRESS_RESULT_IF — skipping Discord post` が出る

### T02_one — 1 thread 通知 → done 移動

```bash
# 前提: Gmail に `hermes-lite` ラベル付き未読 thread 1 件
bin/run-claude.sh mail-watch
```

期待:
- [ ] Discord に 1 投稿。本文 `[mail-watch] 1 thread / 6h\n- 差出人 | 件名 | 1行要約`
- [ ] 対象 thread から `hermes-lite` が外れ、`hermes-lite/done` が付与されている
- [ ] `logs/mail-watch/<ts>.json` の `.result` に "[mail-watch] 1 thread..." を含む

### T03_multi — 3 thread を 1 投稿に集約

```bash
# 前提: Gmail に `hermes-lite` ラベル付き未読 thread 3 件
bin/run-claude.sh mail-watch
```

期待:
- [ ] Discord 投稿は 1 件（3 行）
- [ ] 3 thread すべてが done に移動

### T04_cap — 上限超過は次サイクル持ち越し

```bash
# 前提: Gmail に `hermes-lite` 未読 thread 7 件（上限 5 超過）
bin/run-claude.sh mail-watch
```

期待:
- [ ] Discord 投稿は 1 件（5 行）
- [ ] 古い 5 thread が done に移動
- [ ] 新しい 2 thread は `hermes-lite` のまま残る
- [ ] 次回 `bin/run-claude.sh mail-watch` で残り 2 thread が処理される

### T05_env_compat — export 無し .env でも動く

```bash
# .env に DISCORD_WEBHOOK_URL=... を export なしで記述
bin/run-claude.sh mail-watch
```

期待:
- [ ] T02 と同じ結果（set -a で subprocess に承継される）

### T06_disallowed_calendar — Calendar 書き込みが拒否される

`bin/run-claude.sh mail-watch` 実行時に stderr ログを確認:

```bash
bin/run-claude.sh mail-watch 2>&1 | grep -E "disallowed-tools.*Calendar"
```

期待:
- [ ] `--disallowed-tools` 引数列に `mcp__claude_ai_Google_Calendar__create_event` が含まれる（既存 `lib/disallowed-tools.txt` 機構が機能していることの回帰確認）

### T07_ping_regression — ping ジョブが壊れていない

```bash
bin/run-claude.sh ping
```

期待:
- [ ] 既存通り `[ping] 稼働確認OK` が Discord に投稿される
- [ ] `bin/run-claude.sh` 改修（set -a / SUPPRESS_RESULT_IF）が ping を壊していない

### T08_label_missing — hermes-lite/done 未作成時の fail-fast

```bash
# 前提: Gmail に `hermes-lite` ラベルだけ存在、`hermes-lite/done` は未作成
# Gmail 未読は 1 件以上
bin/run-claude.sh mail-watch
```

期待:
- [ ] claude が list_labels の結果から `hermes-lite/done` 不在を検知し、ラベル変更 / 通知本文整形を一切行わず最終応答に `ERROR: label not found: hermes-lite/done (or hermes-lite)` を返して終了
- [ ] claude プロセス自体は exit 0 / `.is_error == false` で正常終了するが、`.result` が `ERROR:` で始まる
- [ ] `bin/run-claude.sh` が `RESULT_TEXT == ERROR:*` を検知し、stderr に `[run-claude] FAIL via ERROR: prefix in result` を出す
- [ ] Discord に NOTIFY_ON_ERROR 経路で FAIL 通知が出る（本文に ERROR: 文が含まれる）
- [ ] 既存の未読 thread のラベルは変更されない
