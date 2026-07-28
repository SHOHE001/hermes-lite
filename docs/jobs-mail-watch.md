# jobs/mail-watch セットアップ

直近 12 時間に届いたメールを claude 自身が読んで重要度を判定し、**重要なものだけ**を 6 時間ごとに Discord へ通知するジョブ。Issue #2 (Phase 1) で「ユーザーが `hermes-lite` ラベルを貼ったメールを通知する」方式として実装し、2026-07-28 に自動判定方式へ書き換えた（経緯は末尾「設計の変遷」）。

## 概要

```
systemd timer (6h)
  → bin/run-claude.sh mail-watch
      → claude -p prompt.md
          → list_labels で hermes-lite/done の ID を取得（無ければ fail-fast）
          → search_threads "newer_than:12h in:inbox -category:promotions -category:social -label:<DONE_ID>"
              pageSize=50 / view=THREAD_VIEW_MINIMAL（差出人・件名・snippet）
          → 0 件なら最終応答 "[NOOP]" で終了
          → 【一次スクリーニング】件名 + snippet だけで重要度判定（本文は取らない）
          → 該当 0 件なら "[NOOP]" で終了
          → 【二次】通知対象（最大 5 件）だけ get_thread で本文を取り 1 行要約
          → 通知本文を内部で組み立てる（最終応答にはまだ返さない）
          → 通知対象にのみ label_thread(hermes-lite/done) を付与
          → 組み立てた通知本文を最終応答テキストとして返す
      → ラッパーが NOTIFY_RESULT=1 で result を Discord へ投稿
      → SUPPRESS_RESULT_IF="[NOOP]" により 0 件時の Discord 投稿はスキップ
      → 異常終了時は NOTIFY_ON_ERROR=1 経路で FAIL 通知が出る
```

`get_thread` は通知する数件にしか呼ばないので、候補が何十件あっても本文取得のコストは通知件数に比例する。

## 事前セットアップ

### 1. Gmail 側のラベル準備（手動）

Gmail Web UI で **`hermes-lite/done` の 1 ラベルだけ** を作成しておく（`hermes-lite > done` のネスト表示になる）。これが「通知済み」の記録で、検索クエリでの除外に使う。

ジョブは起動時に `list_labels` でこれを探し、**見つからなければ fail-fast** で `ERROR: label not found: hermes-lite/done` を返して即終了する（通知済みを記録できないまま走ると重複通知が止まらなくなるため）。

**Gmail 側のフィルタ設定は不要**。重要かどうかの判定はジョブ側で行う。

### 2. `.env` に Discord webhook を設定

`~/hermes-lite/.env` に次の 1 行を追加する:

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

`export` を付けても付けなくても動く。`bin/run-claude.sh` が `set -a; source .env; set +a` で読み込むため、`KEY=value` 形式でも claude subprocess に環境変数として承継される。

### 3. 重要度の基準を自分に合わせる

**このジョブで一番調整が要るのは `jobs/mail-watch/prompt.md` の「重要度の基準」節**。通知する条件（期限・金銭・セキュリティ・個人宛の返信要求・公的機関・予約や配送）と、通知しない条件（メルマガ・SNS 通知・ニュースレター・行動不要の一斉配信）を列挙してある。

運用しながら、通知が来て嬉しくなかったものを「通知しない」側に、見落として困ったものを「通知する」側に追記していく。判定は `MODEL="sonnet"` が行う。

### 4. ラベルの付与単位

ラベルは **thread レベル**（`label_thread`）で付ける。thread 内の既存 message 全部に `hermes-lite/done` が付くため、その thread は次サイクル以降ヒットしなくなる。ただし**新しい返信が届くとその message には done が付いていない**ので再びヒットする。継続中のやり取りに新展開があれば再通知される、という意図した挙動。

## 旧方式（ラベル手動貼り）からの移行

- Gmail 側で `hermes-lite` ラベルにフィルタを設定していた場合、**そのフィルタは削除してよい**。ジョブはもう `hermes-lite` ラベルを見ない。
- `hermes-lite` ラベル自体も削除してよい（残っていてもジョブの動作には影響しない）。
- `hermes-lite/done` は**削除してはいけない**。新方式でも通知済みマーカーとして使う。
- 旧方式で `hermes-lite/done` が付いた過去メールは、新方式でも自動的に除外対象になる。

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

**検索窓 12h に対して実行間隔が 6h** なので、各メールは通常 2 回評価される。1 回目で「重要でない」と判定されても 2 回目で拾い直せる冗長性であり、ジョブが 1 回失敗しても取りこぼさない。実行間隔を変える場合、窓（prompt.md の `newer_than:12h`）が間隔の 2 倍になるよう合わせること。

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
- 通知本文の `（候補 M 件・除外 K 件）` を見て、判定が厳しすぎ／緩すぎないか確認する

## 仕様まとめ

| 項目 | 値 |
|---|---|
| 検索クエリ | `newer_than:12h in:inbox -category:promotions -category:social -label:<DONE_ID>` |
| 検索取得上限 | `pageSize=50`、**ページングしない**（50 件到達時は通知本文に注記） |
| 粒度 | thread |
| 一次スクリーニング | 件名 + snippet のみ（`THREAD_VIEW_MINIMAL`）。`get_thread` は呼ばない |
| 二次（本文取得） | 通知対象のみ `get_thread` |
| 1 サイクル通知上限 | **5 件**（重要度の高い順、同程度なら古い順） |
| 通知フォーマット | `[mail-watch] 重要 N 件 / 直近12h（候補 M 件・除外 K 件）\n- 差出人 \| 件名 \| 1 行要約` × N |
| 0 件時 | claude が `[NOOP]` を返し、ラッパーが `SUPPRESS_RESULT_IF` で投稿スキップ |
| ラベル付与 | **通知したものにのみ** `hermes-lite/done`。通知本文を返す前に完了させる |
| Calendar / Notion 書き込み | 禁止（`lib/disallowed-tools.txt` により自動拒否） |
| 失敗時 | `NOTIFY_ON_ERROR=1` で Discord に FAIL 通知 |
| スケジュール | `*-*-* 00,06,12,18:00:00`（6h ごと） |

`job.env` の `ALLOWED_TOOLS` で Gmail 系の 4 ツール（`list_labels` / `search_threads` / `get_thread` / `label_thread`）のみを許可している。**`unlabel_thread` は新方式では不要なので外した**。これに加えて `lib/disallowed-tools.txt` で Calendar 系・Notion 書き込み・Gmail 下書き作成などを wrapper レベルで追加拒否している。

- `--allowed-tools`: Gmail 系の必要ツールだけを明示許可
- `--disallowed-tools`: 共通禁止リストで Calendar / Notion / メール送信などを追加拒否

二段構えにより、prompt 側で誤ってツール名を書いても危険操作は通らない。

## 設計判断

### なぜ「時間窓 + 通知済みラベル」なのか

全メールを読んで判定する方式では、**通知しなかったメールの扱い**が問題になる。処理済みラベルを付けると受信トレイのほぼ全メールにラベルが付いて Gmail が汚れ、付けないと毎サイクル同じメールを再評価してコストが膨らむ。

そこで状態記録を「時間窓」と「通知済みラベル」に分けた:

- **時間窓（`newer_than:12h`）** が評価対象の範囲を決める。通知しなかったメールは窓から出れば自然に対象外になり、ラベルは不要
- **`hermes-lite/done`** は通知したものにだけ付き、重複通知を防ぐ

これで状態ファイルも最終実行時刻の記録も要らない。ジョブが数回落ちても、次に走ったときの直近 12h から再開するだけで復帰する。

### 順序とトレードオフ

「**ラベル付与 → 通知本文を最終応答として返す**」の順で実行する。理由: claude の最終応答を返した時点でツール実行は終了するため、最終応答を返す前にラベル付与を完了させる必要がある。

- **ラベル付与後・通知前にプロセスが死ぬ** → 通知漏れ。発見方法: Gmail 上で `hermes-lite/done` が付いているのに Discord に来ていない thread を探す。再通知したい場合は当該 thread から `hermes-lite/done` を外すと、12h 窓の内側であれば次サイクルで拾われる
- 重複通知（spam）より通知漏れの方が運用負荷が低いと判断

### 判定の非決定性について

フィルタと違い、同じメールが実行ごとに違う判定を受けうる。緩和策:

- prompt に判定基準を具体的に列挙してブレを抑える
- 「迷ったら通知しない」を明示し、窓 12h × 実行 6h で 2 回評価されることで拾い直せるようにする
- 通知本文に `（候補 M 件・除外 K 件）` を出し、**何件を落としたか**が毎回見えるようにする（見落としに気づけるようにするため）

## トラブルシュート

| 症状 | 確認 |
|---|---|
| Discord に何も来ない | (a) `logs/mail-watch/<ts>.json` の `.result` を確認 → `[NOOP]` なら「重要なメール 0 件」で正常。<br>(b) `.stderr` に `Discord post failed` が無いか確認。<br>(c) `.env` の `DISCORD_WEBHOOK_URL` が有効か確認 |
| `ERROR: label not found: hermes-lite/done` | Gmail 側で `hermes-lite/done` ラベルを作成する |
| 重要なメールが通知されなかった | `.result` の `除外 K 件` を確認。`prompt.md` の「重要度の基準」の**通知する側**に条件を追記する |
| どうでもいいメールが通知される | `prompt.md` の「重要度の基準」の**通知しない側**に条件を追記する |
| 同じメールが何度も通知される | (a) `label_thread` が失敗していないか `logs/.../<ts>.json` を確認。<br>(b) 新しい返信が届いた thread は仕様上再ヒットする（新展開があれば再通知する設計） |
| 候補が多すぎて未評価が出る（`※候補が上限に達した`） | `pageSize=50` を超える受信量。`prompt.md` のクエリに `-from:` などの除外条件を足して候補を減らす |
| `is_error: true` で exit code != 0 | `--allowed-tools` に必要な MCP ツールが入っているか、MCP サーバが起動しているか、claude が disallowed ツールを呼ぼうとしていないかを `stderr` で確認 |

## 設計の変遷

- **Phase 1（Issue #2, 2026-07）**: ユーザーが Gmail フィルタで `hermes-lite` ラベルを貼り、その未読 thread（`label:hermes-lite is:unread`）を通知。通知後に `hermes-lite` → `hermes-lite/done` へ付け替えて重複を防いだ。
- **2026-07-28 の書き換え**: 「何を通知するか」の条件を Gmail フィルタで人間が書き下ろす必要があり、条件から漏れたメールは永久に拾われなかった。判定を claude 側に移し、直近 12h の受信を全部評価する方式に変更。`hermes-lite` ラベルと `unlabel_thread` は不要になった。

## 関連ファイル

- `jobs/mail-watch/prompt.md` — claude 向け指示。**重要度の基準はここで調整する**
- `jobs/mail-watch/job.env` — ALLOWED_TOOLS / MAX_TURNS など
- `bin/run-claude.sh` — `.env` の `set -a` 読み込み、`SUPPRESS_RESULT_IF` opt-in を提供
- `lib/disallowed-tools.txt` — Calendar / Notion 書き込みなどを全ジョブ共通で禁止
- `lib/notify.sh` — Discord webhook 投稿ヘルパ（1900 字 truncate 込み）
- `features/2-email-gateway-gmail-discord/{plan.md, rejection.md, test-spec.md}` — Phase 1 の設計と手動テスト（旧方式の記録）
