# Discord 承認ゲート (#3)

hermes-lite は「Calendar / Notion / Gmail draft / Slack 等の送信系」を default で禁止している (`lib/disallowed-tools.txt`)。本機能は **Discord 経由の事前承認** によって「Calendar.create を 1 件だけ・1 回だけ一時解禁する」基盤。

## 信頼境界 (前提)

承認ゲートは「**hermes-lite 自身の LLM が誤って Calendar に書き込まないようにする**」防護で、「悪意ある攻撃者から保護する」ものではない。

- Hermes-lite のジョブ (proposer) が enqueue した payload が、承認後そのまま executor に渡る
- 承認者は Discord 上で payload を確認してから承認する
- executor は承認済み row を 1 回限り `take()` して `claude -p` を起動する
- LLM 経由なので副作用 (Calendar.create) は **事後検証** のみ (副作用前保証はしない)

## アーキテクチャ

```
+----------------------+        +-----------------------+
| proposer ジョブ      |        | Discord (ユーザー)    |
| jobs/<name>/         |        |  approval approve <id>|
| (Bash で enqueue)    |        |  approval reject  <id>|
+----------+-----------+        +-----------+-----------+
           |                                |
           v                                v
+----------+-----------+        +-----------+-----------+
| var/approvals.sqlite | <----- |  gateway/discord/bot  |
| (state machine)      |  decide|  approval_handler     |
+----------+-----------+        +-----------+-----------+
           ^                                |
           |                       systemd-run --user --no-block
           |                                |
           |                                v
           |                    +-----------+-----------+
           |    take/done/fail  | lib/approvals_executor|
           +--------------------+  claude -p --allowed  |
                                |   mcp__...create_event|
                                +-----------------------+
                                           |
                                           v
                                +----------+----------+
                                |  Google Calendar    |
                                +---------------------+
```

## 副作用後検出

executor は claude -p の `--output-format json` 出力から tool_use evidence を抽出して、payload と完全一致を assert する。違反 (件数 / 別 tool / input mismatch) を検出した場合は `failed_after_side_effect` に倒し、Calendar 側に残った余分な event は **手動 cleanup** する。

`failed_after_side_effect` の意味は次の **どちらか**:

1. tool_use 件数 / 名前 / input の検証で違反を検出 → 副作用 (event 作成) が起きている
2. tool_use evidence が取得不能 (`extract_tool_calls()` が `None` を返した) → 副作用が起きた**可能性**がある (fail-closed)

どちらも自動再試行不可。Calendar 側で event を確認し、不要なら手動削除してから新規 ID で再起票する。

## LLM executor vs 代替案 (採用根拠)

| 案 | 失敗モード保証 | 実装コスト | 採否 |
|---|---|---|---|
| A: LLM executor + 事後検証 (本案) | 副作用後検出のみ | 中 | **採用** |
| B: Discord に exact MCP コマンドを貼って人間が手動 create | 副作用前保証 | 小 | 不採用 (自動化ゴールを満たさない) |
| C: Google API OAuth client を別途構築して直叩き | 副作用前保証 | 大 | 不採用 (Phase 1 超過、将来 Issue) |
| D: Calendar.create を Phase 1 対象外 | — | — | 不採用 (Phase 1 ゴール直接ブロック) |

採用案 A の許容するリスク:

- LLM が `create_event` を 2 回呼ぶ → `failed_after_side_effect` / 余分 event は手動削除
- LLM が summary を改変 → input 検証で検出 (取れる場合) / 取れなければ `failed_after_side_effect`
- LLM が 0 回呼んで終わる → 件数違反として検出 (副作用なしだが status は `failed_after_side_effect`)

## DB schema (sqlite, `var/approvals.sqlite`)

`PRAGMA user_version = 1`。schema 変更時は backup + 再作成 (詳細は本文末「failure recovery」)。

| column | 型 | 説明 |
|---|---|---|
| id | TEXT PRIMARY KEY | 8 hex (固定長) |
| proposer_job | TEXT | 起票ジョブ名 |
| executor_job | TEXT | 実行ジョブ名 (= `calendar-create-executor` 固定) |
| action | TEXT | `calendar.create` |
| summary | TEXT | 人間向け要約 |
| payload_json | TEXT | MCP create_event payload (validate 済み) |
| status | TEXT | pending / approved / rejected / executing / executed / expired / failed / failed_after_side_effect |
| created_at / expires_at | INT | unix sec |
| decided_at / decided_by | INT | 承認/却下時の時刻と Discord user_id |
| started_at / finished_at | INT | executor 起動 / 終了時刻 |
| result_text | TEXT | done/fail の結果 (JSON or 自由文) |

## 状態遷移表

| 現 status | 遷移先 | API | 条件 |
|---|---|---|---|
| pending | approved | `decide(id, "approve")` | `id=? AND status='pending' AND expires_at>now` |
| pending | rejected | `decide(id, "reject")` | 同上 |
| pending | expired | `sweep_expired()` | `expires_at<now` |
| approved | executing | `take(id, executor_job)` | `status='approved' AND expires_at>now` |
| approved | failed | `fail_before_executor(id)` | bot の systemd-run 失敗時 |
| approved | failed | `sweep_stale_approved()` | `decided_at<now-600` (10 min) |
| executing | executed | `done(id)` | `status='executing'` |
| executing | failed | `fail_during_executor(id, side_effect=False)` | validate / 副作用前 is_error |
| executing | failed_after_side_effect | `fail_during_executor(id, side_effect=True)` | 副作用後検出 |
| executing | failed | `sweep_stale_executing()` | `started_at<now-1800` (30 min) |

`rejected / executed / failed / failed_after_side_effect / expired` は終端 (遷移不可)。

## 承認コマンド

Discord (DM / 反応チャンネル / mention) で:

```
approval approve <8hex>
approval reject  <8hex>
```

- `#` 任意 (`approval approve #abcd1234` も受ける)
- 大文字小文字区別なし
- regex: `^\s*approval\s+(approve|reject)\s+#?[a-f0-9]{8}\s*$`

## feature flag (opt-in)

承認ゲートは **default 無効** (`HERMES_APPROVAL_COMMANDS_ENABLED=0`)。

有効化手順:

```bash
# bot の systemd unit に環境変数を追加
mkdir -p ~/.config/systemd/user/hermes-lite-discord.service.d
cat > ~/.config/systemd/user/hermes-lite-discord.service.d/approval.conf <<EOF
[Service]
Environment="HERMES_APPROVAL_COMMANDS_ENABLED=1"
Environment="HERMES_APPROVAL_AUTHORIZED_USER_IDS=<discord-user-id>"
EOF
systemctl --user daemon-reload
systemctl --user restart hermes-lite-discord.service
```

`HERMES_APPROVAL_AUTHORIZED_USER_IDS` を明示設定しない場合、bot.py は `ALLOWED_USER_IDS` を `HERMES_APPROVAL_ALLOWED_USER_IDS_FALLBACK` として export するので、承認可能ユーザー = bot に応答可能ユーザー全員になる。

**運用推奨**: `HERMES_APPROVAL_AUTHORIZED_USER_IDS ⊆ ALLOWED_USER_IDS` を保つこと (承認権限を bot 反応権限の部分集合に収める)。

### Migration notice (予約語化)

feature flag を **有効化したとき初めて** `approval approve <8hex>` / `approval reject <8hex>` 形式が予約語となり、通常の質問応答経路 (`_handle`) には流れない。default `0` の状態では従来通り `_handle` (= claude-runner) に流れる。

## TTL / sweep

| TTL | 適用先 | 上書き |
|---|---|---|
| 24h (`pending`) | 期限切れで `sweep_expired()` -> `expired` | `HERMES_APPROVAL_TTL_SEC` |
| 10 min (`approved`) | `sweep_stale_approved()` -> `failed` (executor 起動失敗の救済) | 固定 |
| 30 min (`executing`) | `sweep_stale_executing()` -> `failed` | 固定 |

bot は 1 時間ごとに 3 種類の sweep を呼ぶ。CLI 直接呼び出しも可。

## CLI Contract

| サブコマンド | 引数 | stdin | stdout (成功) | exit 0 | exit 1 | exit 3 |
|---|---|---|---|---|---|---|
| `enqueue` | `--proposer X --executor Y --action Z --summary S [--ttl N]` | payload JSON | 8hex id | 成功 | validate 失敗 | ID 衝突 5 回超 |
| `decide` | `--id X --decision approve\|reject [--user-id N]` | — | 新 status | 成功 | None (pending でない/期限切れ) | — |
| `take` | `--id X --executor Y` | — | row JSON | 成功 | None | — |
| `done` | `--id X --result-text T` | — | (空) | 成功 | ValueError | — |
| `fail-before` | `--id X --result-text T` | — | (空) | 成功 | ValueError | — |
| `fail-during` | `--id X --result-text T [--side-effect]` | — | (空) | 成功 | ValueError | — |
| `sweep` / `sweep-stale-approved` / `sweep-stale-executing` | — | — | `swept-* N` | 成功 | — | — |
| `get` | `--id X` | — | row JSON | 成功 | 存在しない | — |
| `list` | `[--status pending\|...]` | — | row JSON 配列 | 成功 | — | — |

`enqueue` の exit 3 は ID 衝突 (5 連続) 専用。CLI の other 呼び出しでは出ない。executor (`lib/approvals_executor.py`) は `HERMES_APPROVAL_ID` 未設定時に exit 2 を返す (CLI 表とは別 contract)。

## failure recovery

| 失敗ケース | 起きること | 対処 |
|---|---|---|
| systemd-run 起動失敗 | bot が `fail_before_executor` -> `failed` | 新規 ID で再起票 |
| executor 副作用前失敗 (validate / is_error 0 件) | executor が `fail_during_executor(side_effect=False)` -> `failed` | 新規 ID で再起票 |
| executor 副作用後検出 | `fail_during_executor(side_effect=True)` -> `failed_after_side_effect` | Calendar で event 確認 -> 不要なら手動削除 -> 新規 ID で再起票 |
| executor 即時失敗 (import error 等) | bot は observable でない | `journalctl --user -u hermes-exec-<id>-<ts>` で確認。30 min 後 `sweep_stale_approved` -> `failed` (注: 厳密には bot 経路では既に take() で executing 遷移しているので `sweep_stale_executing` 経路) |
| schema mismatch (DB 破損 / migration) | bot 起動時 `RuntimeError` | `mv var/approvals.sqlite var/approvals.sqlite.bak.$(date +%s)` -> bot 再起動 -> 既存 pending/approved を破棄して新規起票 |

backup 取得は `list` CLI で十分代替可能:

```bash
python3 lib/approvals.py list > /tmp/approvals-backup-$(date +%s).jsonl
```

## セキュリティ注意点

- `lib/disallowed-tools.txt` は **本 Issue で書き換えない**。Calendar.create は default disallowed のまま。executor が `--allowed-tools` で 1 回限り解禁する
- bot プロセスは user systemd unit で動く前提 (悪意ある攻撃者から守る防護ではない)
- DB の `.env` / DISCORD_TOKEN / webhook URL を log / chat に出さない (CLAUDE.md 規約)
- `HERMES_APPROVAL_AUTHORIZED_USER_IDS` を保たないと、bot 反応可能な全ユーザーが承認権限を持つ (fallback 動作)

## ロールバック

1. bot の Environment から `HERMES_APPROVAL_COMMANDS_ENABLED` を削除して reload (機能のみ無効化)
2. または gateway/discord/bot.py の approval 分岐を git revert
3. `var/approvals.sqlite` を rename (DB 破棄)
4. `lib/approvals_executor.py` / `lib/approvals.py` は残存しても害なし (誰も呼ばない)
