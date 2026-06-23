# plan: #2 Email gateway: Gmail ポーリングで未読メール検知 → Discord 通知 (rev2)

slug: email-gateway-gmail-discord
milestone: Phase 1
labels: type:feature, batch:feature
depends_on: #1 (closed)
design_loops: 1

## 改訂履歴

- rev1: 初版
- rev2: Codex 3 persona 設計レビューを反映
  - 粒度を thread に統一（label_thread / unlabel_thread を使う）
  - 通知責務を wrapper 側に戻す（Bash(curl *) は ALLOWED から外す）
  - 順序を「ラベル変更先、通知後」に変更
  - 件数上限を 5 thread/サイクルに固定（裁量パッチ、rejection.md 参照）
  - `bin/run-claude.sh` を 2 点改修: `.env` を `set -a; source; set +a` で読む / result が空 or `[NOOP]` のとき投稿スキップ

## In-Scope / Out-of-Scope

| In-Scope | Out-of-Scope |
|---|---|
| `jobs/mail-watch/{prompt.md, job.env}` 新規作成 | カレンダー登録などの後段アクション（Issue #3） |
| `docs/jobs-mail-watch.md` セットアップ手順を新規追加 | mail-watch 以外のジョブの仕様変更 |
| `bin/run-claude.sh` を 2 点改修（下記）| `lib/notify.sh` / `lib/disallowed-tools.txt` / systemd templates の改変 |
| 6h ごと polling（drop-in 例を docs に明記） | テスト自動化フレームワーク導入 |
| Gmail thread ラベル `hermes-lite` → `hermes-lite/done` 付け替え | Calendar / Notion 書き込み |
| 1 Discord 投稿に最大 5 thread 集約（plain） | embed リッチカード |
| 0 件のときは Discord に投稿しない（wrapper 側で空 result を判定） | 既読化済み既存メールの一括移行（手動運用） |

### `bin/run-claude.sh` 改修内容

1. **`.env` の export 強制**: 現在の `source "$HERMES_HOME/.env"` を `set -a; source "$HERMES_HOME/.env"; set +a` に変更し、`KEY=value` 形式でも subprocess（claude プロセス）に環境変数が承継されることを保証する
2. **空 result の Discord 投稿スキップ**: 現在の `notify_discord "[$JOB_NAME] ${RESULT_TEXT:-(no result text)}"` を、`RESULT_TEXT` が空文字 or `[NOOP]` のときは `notify_discord` を呼ばないように変更

これらは全 job に影響するが:
- 改修 1 は「export 付き .env を書けば動く現状」の上位互換（既存 .env は引き続き動作）
- 改修 2 は ping job など「必ず非空 result を返す job」には無影響

## Non-Goals

- 双方向対話（mail-watch 通知に対するユーザー返信ハンドリング）
- Gmail 以外のメールプロバイダ対応
- 添付ファイル取得
- メール本文の長文要約（1 行要約に留める）
- 既読化済み既存メールの自動移行

## 設計方針

### 全体フロー

```
systemd timer (6h)
  → bin/run-claude.sh mail-watch
      → set -a; source .env; set +a    [改修1]
      → claude -p <prompt.md>
          → list_labels で hermes-lite, hermes-lite/done の ID 取得
          → search_threads "label:hermes-lite is:unread"
          → 0 件なら "[NOOP]" を返して終了
          → 最大 5 thread を選び（古い順）、get_thread で本文を取る
          → 各 thread の {差出人, 件名, 1行要約} を抽出
          → 【ラベル変更を先に全件】各 thread に対し
              unlabel_thread(hermes-lite) → label_thread(hermes-lite/done)
          → 【通知本文を整形して最終応答テキストとして返す】
              "[mail-watch] N thread / 6h\n- ...\n..."
      → run-claude.sh は NOTIFY_RESULT=1 で result を Discord に流す
      → result == "[NOOP]" ならスキップ           [改修2]
      → NOTIFY_ON_ERROR=1 で異常終了時のみ FAIL 通知
```

### 粒度: thread 単位に統一

- 検索: `search_threads` （クエリ: `label:hermes-lite is:unread`）
- 取得: `get_thread`
- ラベル変更: `label_thread` / `unlabel_thread`
- 通知の N は **thread 数**（同一スレッド内の複数メッセージは 1 件として扱う）

これによりラベル変更の対象範囲が明確になる（thread 内全 message に hermes-lite/done が付与される）。ユーザー視点でも「この thread は処理済み」が直感的。

### 件数上限 5 thread/サイクル

- prompt 側で `search_threads` の結果のうち先頭 5 件のみ処理（古い順）
- 6 件以上ある場合、残りは次サイクル（6h 後）に持ち越し
- ラベル変更を先にするため、処理対象 5 thread は「次サイクルでは確実に拾われない」状態になる

### 順序: ラベル変更先、通知後

trade-off:
- ラベル変更先 + 通知失敗 → 通知漏れ（ログから手動回復可能）
- ラベル変更後 + 通知先 → 重複通知（user-visible spam）

Phase 1 では **通知漏れを許容** する。理由: 重複通知は運用負荷が高く、通知漏れは `logs/mail-watch/<ts>.json` に最終応答が残るため発見・回復可能。

> Note: 完全な idempotency は `processing` 中間ラベルなどが必要だが、Phase 1 では Out-of-Scope。

### 通知責務: wrapper 側に統一

- **claude prompt は通知本文を生成して標準応答に返すだけ**
- `bin/run-claude.sh` が `notify_discord` (lib/notify.sh) 経由で投稿
- `Bash(curl *)` は ALLOWED_TOOLS から外す（汎用送信口を持たない）
- 1900 文字 truncation は `lib/notify.sh` が既に対応済み

### ALLOWED_TOOLS

`Bash(curl *)` を含めない。Gmail 読み取り＋ラベル操作のみ。

```
ALLOWED_TOOLS="
  mcp__claude_ai_Gmail__list_labels
  mcp__claude_ai_Gmail__search_threads
  mcp__claude_ai_Gmail__get_thread
  mcp__claude_ai_Gmail__label_thread
  mcp__claude_ai_Gmail__unlabel_thread
"
```

### DISCORD_WEBHOOK_URL の引き継ぎ

- `bin/run-claude.sh` の `.env` 読み込みを `set -a; source ...; set +a` に改修（改修 1）
- これにより `.env` が `KEY=value` 形式でも subprocess に承継される
- export 付き `.env` も引き続き動作（後方互換）

### 0 件時の振る舞い

- claude は最終応答に `[NOOP]` を返す（空文字ではなく明示マーカー）
- `bin/run-claude.sh` が `[NOOP]` を判定して `notify_discord` を呼ばない（改修 2）
- 結果は `logs/mail-watch/<ts>.json` には残るのでデバッグ可能

### MAX_TURNS / TIMEOUT_SEC

- MAX_TURNS=40 を初期値（裁量パッチで余裕を取った）（list_labels 1 + search 1 + 5 thread × 3 (get_thread + unlabel + label) + 整形 1 ≒ 18 ターン想定だが、claude は複数操作を 1 ターンにまとめる場合もあるため 30 で開始、不足したら次回 inc。実装では 40 に設定済み）
- TIMEOUT_SEC=300（5 分）

### 既読化済み既存メールの扱い

- 検索クエリは `label:hermes-lite is:unread` 固定
- 既に既読化されている `hermes-lite` ラベル付きメールは対象外
- 移行運用: ユーザーが Gmail 上で手動で（a）ラベルを外す、または（b）`hermes-lite/done` に手動移動する
- `docs/jobs-mail-watch.md` に明記

## 実装対象

### 改修対象（implementer teammate に依頼）

- `bin/run-claude.sh` の 2 点改修（前述）
- `jobs/mail-watch/prompt.md`（新規）
- `jobs/mail-watch/job.env`（新規）
- `docs/jobs-mail-watch.md`（新規）

### 変更しない

- `lib/notify.sh`
- `lib/disallowed-tools.txt`
- `systemd/claude-agent@.{service,timer}`
- `gateway/discord/*`

### `bin/run-claude.sh` の before/after

**改修 1: `.env` 読み込み**

```bash
# before (line ~60)
source "$HERMES_HOME/.env"

# after
set -a
source "$HERMES_HOME/.env"
set +a
```

**改修 2: result 空判定**

```bash
# before (line ~140)
if [[ "$NOTIFY_RESULT" == "1" ]]; then
  notify_discord "[$JOB_NAME] ${RESULT_TEXT:-(no result text)}"
fi

# after
if [[ "$NOTIFY_RESULT" == "1" ]]; then
  if [[ -z "$RESULT_TEXT" || "$RESULT_TEXT" == "[NOOP]" ]]; then
    echo "[run-claude] result is empty or [NOOP] — skipping Discord post" >&2
  else
    notify_discord "[$JOB_NAME] $RESULT_TEXT"
  fi
fi
```

## テスト計画

**前提**: Hermes-lite は jobs/ を claude -p で動かす。自動テストフレーム未整備のため手動試走チェックリストで運用する。

| ID | 内容 | 期待値 |
|---|---|---|
| T01_zero | Gmail に `hermes-lite` 未読が 0 件のとき `bin/run-claude.sh mail-watch` を試走 | Discord に何も投稿されない。`logs/mail-watch/<ts>.json` の `.result == "[NOOP]"`。`is_error == false`。stderr に "skipping Discord post" |
| T02_one | `hermes-lite` 未読 thread 1 件で試走 | Discord に 1 投稿。フォーマット `[mail-watch] 1 thread / 6h\n- 差出人 \| 件名 \| 要約`。対象 thread は `hermes-lite/done` に付け替え済み。`logs/.../.result` に "[mail-watch] 1 thread..." |
| T03_multi | `hermes-lite` 未読 thread 3 件で試走 | Discord に 1 投稿（3 行）。3 thread ともラベル付け替え済み。 |
| T04_cap | `hermes-lite` 未読 thread 7 件のとき | Discord に 1 投稿（5 行）。古い 5 thread のみ done に移動。残り 2 thread は `hermes-lite` のまま次サイクル待機。 |
| T05_env_compat | `.env` に `DISCORD_WEBHOOK_URL=https://...`（export なし）で書いて T02 を実行 | T02 と同じ結果（改修 1 で subprocess に承継される） |
| T06_disallowed_calendar | `bin/run-claude.sh mail-watch` 実行時に `--disallowed-tools` 引数に `mcp__claude_ai_Google_Calendar__create_event` が含まれることをコマンド出力で確認 | run-claude.sh が `lib/disallowed-tools.txt` をパースして claude へ正しく渡している（既存仕様の回帰確認） |
| T07_ping_regression | `bin/run-claude.sh ping` を試走 | 既存通り `[ping] 稼働確認OK` が Discord に投稿される（改修 1/2 が ping を壊していないことを確認） |
| T08_error | Gmail に `hermes-lite/done` ラベルが事前作成されていない状態で T02 を試走 | claude が label_thread に失敗。`run-claude.sh` の `NOTIFY_ON_ERROR=1` 経路で FAIL 通知が Discord に出る。`logs/.../.is_error == true` または `exit_code != 0` |

T06 は実装時に `bin/run-claude.sh` の `echo "[run-claude] ..."` ログを `set -x` などで吐かせるか、`logs/mail-watch/<ts>.stderr` を grep して `--disallowed-tools` の引数列に `Calendar__create_event` が含まれることを確認する。

## 受け入れ基準

- 全 T01〜T08 が手動チェックリストで pass
- `bin/run-claude.sh ping` の既存挙動が変わらない（T07）
- `docs/jobs-mail-watch.md` で第三者がセットアップ可能（ラベル事前作成・systemd timer 登録・試走手順を含む）
- thread 単位で粒度が統一されている（findings 1 への対応）
- `Bash(curl *)` が ALLOWED_TOOLS に含まれない（findings 3 への対応）
- 件数上限 5 thread が prompt.md に明記されている（findings 5 への対応）

## Issue body 抜粋

(元 Issue 本文は git 履歴で確認可能)
