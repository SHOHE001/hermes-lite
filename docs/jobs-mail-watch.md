# jobs/mail-watch セットアップ

Gmail ラベル `hermes-lite` を貼った未読 thread を 6 時間ごとに検出し、Discord に通知するジョブ。Issue #2 (Phase 1) の実装。

## 概要

```
systemd timer (6h)
  → bin/run-claude.sh mail-watch
      → claude -p prompt.md
          → list_labels で hermes-lite / hermes-lite/done の ID を取得
          → search_threads "label:hermes-lite is:unread"
          → 0 件なら最終応答 "[NOOP]" で終了
          → 1 件以上なら get_thread で詳細取得、internalDate 昇順で最大 5 thread を処理
          → 通知本文を内部で組み立てる（最終応答にはまだ返さない）
          → 各 thread に対し label(hermes-lite/done) → unlabel(hermes-lite) を実行（順序逆だと部分失敗で thread が消失する）
          → 組み立てた通知本文を最終応答テキストとして返す
      → ラッパーが NOTIFY_RESULT=1 で result を Discord へ投稿
      → SUPPRESS_RESULT_IF="[NOOP]" により 0 件時の Discord 投稿はスキップ
      → 異常終了時は NOTIFY_ON_ERROR=1 経路で FAIL 通知が出る
```

## 事前セットアップ

### 1. Gmail 側のラベル準備（手動）

Gmail Web UI で次の **2 ラベル** を事前に作成しておく:

- `hermes-lite`（未処理メールに付けるラベル）
- `hermes-lite/done`（処理済みメールに付け替えるラベル）

ラベル名はそのままドット区切りでもネスト表示でも構わない（Gmail 上は `hermes-lite/done` が `hermes-lite > done` のネスト扱いになる）。MCP の `list_labels` がこの 2 ラベルを返せる状態にしておくこと。

ジョブは起動時に `list_labels` でこの 2 つを探し、**片方でも見つからなければ fail-fast** で `ERROR: label not found: hermes-lite/done (or hermes-lite)` を返して即終了する（重要なラベル変更を未作成のまま走らせないため）。

### 2. `.env` に Discord webhook を設定

`~/hermes-lite/.env` に次の 1 行を追加する:

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

`export` を付けても付けなくても動く。`bin/run-claude.sh` が `set -a; source .env; set +a` で読み込むため、`KEY=value` 形式でも claude subprocess に環境変数として承継される。

### 3. ラベル運用ガイド（既読化済み既存メールの扱い）

検索クエリは `label:hermes-lite is:unread` 固定なので、すでに **手動で既読化されてしまった** `hermes-lite` ラベル付きメールは対象外。次のどちらかの方法で運用すること:

- (a) Gmail 上で手動でラベルを外す
- (b) Gmail 上で手動で `hermes-lite/done` に移す（`hermes-lite` ラベルだけ外しても良い）

ジョブは「未読 thread のみ」を処理対象とする。

### 4. ラベルの付与単位

ラベルは **thread レベル** で付ける運用とする（message 単位ではない）。MCP の `label_thread` / `unlabel_thread` を使い、thread 内全 message が `hermes-lite/done` に切り替わる。

## systemd timer 登録

```bash
mkdir -p ~/.config/systemd/user/claude-agent@mail-watch.timer.d
cat > ~/.config/systemd/user/claude-agent@mail-watch.timer.d/schedule.conf <<'EOF'
[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
EOF

systemctl --user daemon-reload
systemctl --user enable --now claude-agent@mail-watch.timer
```

これで 6 時間おき（00:00 / 06:00 / 12:00 / 18:00 JST）に走る。

タイマー状態の確認:

```bash
systemctl --user list-timers --all | grep mail-watch
systemctl --user status claude-agent@mail-watch.timer
```

## 手動試走

定期実行に組み込む前、あるいは prompt を変更した直後の試走:

```bash
~/hermes-lite/bin/run-claude.sh mail-watch
```

実行後の確認ポイント:

- `~/hermes-lite/logs/mail-watch/<timestamp>.json` の `.result` に通知本文または `[NOOP]` または `ERROR: label not found: ...` が入っている
- `~/hermes-lite/logs/mail-watch/<timestamp>.stderr` に `[run-claude]` ログが残る
  - 0 件時は `result matched SUPPRESS_RESULT_IF — skipping Discord post` が出る
- `.is_error == false` かつ exit code 0 が正常終了

## 仕様まとめ

| 項目 | 値 |
|---|---|
| 検索クエリ | `label:hermes-lite is:unread` |
| 粒度 | thread |
| 1 サイクル処理上限 | **5 thread**（超過分は次サイクル持ち越し） |
| ソート | `internalDate` 昇順（古い順）から処理 |
| 通知フォーマット | `[mail-watch] N thread / 6h\n- 差出人 \| 件名 \| 1 行要約` × N |
| 0 件時 | claude が `[NOOP]` を返し、ラッパーが `SUPPRESS_RESULT_IF` で投稿スキップ |
| ラベル変更タイミング | **通知本文を返す前**（Phase 1 は通知漏れ許容、重複通知より優先） |
| Calendar / Notion 書き込み | 禁止（`lib/disallowed-tools.txt` により自動拒否） |
| 失敗時 | `NOTIFY_ON_ERROR=1` で Discord に FAIL 通知 |
| スケジュール | `*-*-* 00,06,12,18:00:00`（6h ごと） |

mail-watch の `job.env` の `ALLOWED_TOOLS` で Gmail 系の 5 ツールのみを許可している。これに加えて `lib/disallowed-tools.txt` で Calendar 系・Notion 書き込み・Gmail 下書き作成などを wrapper レベルで追加拒否している。

- `--allowed-tools`: Gmail 系の必要ツールだけを明示許可
- `--disallowed-tools`: 共通禁止リストで Calendar / Notion / メール送信などを追加拒否

二段構えにより、prompt 側で誤ってツール名を書いても危険操作は通らない。

## 順序とトレードオフ

Phase 1 では「**ラベル変更 → 通知本文を最終応答として返す**」の順で実行する。理由: claude の最終応答を返した時点でツール実行は終了するため、最終応答を返す前にラベル変更を完了させる必要がある。

トレードオフ:

- **ラベル変更後・通知前にプロセスが死ぬ** → 通知漏れ。`logs/mail-watch/<ts>.json` の `.result` や stderr で発見可能。Gmail 側で `hermes-lite/done` を `hermes-lite` に戻せば次サイクルで再通知できる
- 重複通知（spam）より通知漏れの方が運用負荷が低いと判断

完全な idempotency（`processing` 中間ラベルなど）は Phase 1 では Out-of-Scope。

## 受信トレイ内の hermes-lite ラベル付け運用

メール受信時に自動で `hermes-lite` ラベルを付与したい場合、Gmail 側のフィルタを使う（このジョブの責務外）:

- Gmail 設定 → 「フィルタとブロック中のアドレス」 → 「新しいフィルタを作成」
- 条件を設定し、「ラベルを付ける」で `hermes-lite` を選択
- これにより条件に合致したメールに `hermes-lite` ラベルが自動付与される

mail-watch ジョブはラベルが付いた **未読 thread** を 6h ごとに検出して通知する役割のみを持つ。

## トラブルシュート

| 症状 | 確認 |
|---|---|
| Discord に何も来ない | (a) `logs/mail-watch/<ts>.json` の `.result` を確認 → `[NOOP]` なら 0 件で正常。<br>(b) `.stderr` に `Discord post failed` が無いか確認。<br>(c) `.env` の `DISCORD_WEBHOOK_URL` が有効か確認 |
| `ERROR: label not found: ...` が返る | Gmail 側で `hermes-lite` / `hermes-lite/done` の両ラベルを事前作成する |
| 同じメールが何度も通知される | ラベル変更が失敗している。`logs/.../<ts>.json` を読んで `label_thread` / `unlabel_thread` のエラーを確認 |
| `is_error: true` で exit code != 0 | `--allowed-tools` に必要な MCP ツールが入っているか、MCP サーバが起動しているか、claude が disallowed ツールを呼ぼうとしていないかを `stderr` で確認 |

## 関連ファイル

- `jobs/mail-watch/prompt.md` — claude 向け指示
- `jobs/mail-watch/job.env` — ALLOWED_TOOLS / MAX_TURNS など
- `bin/run-claude.sh` — `.env` の `set -a` 読み込み、`SUPPRESS_RESULT_IF` opt-in を提供
- `lib/disallowed-tools.txt` — Calendar / Notion 書き込みなどを全ジョブ共通で禁止
- `lib/notify.sh` — Discord webhook 投稿ヘルパ（1900 字 truncate 込み）
- `features/2-email-gateway-gmail-discord/{plan.md, rejection.md, test-spec.md}` — 設計と手動テスト
