# test-spec: #3 承認ゲート付き書き込み (手動チェックリスト + 一部自動)

project_type=jobs のため、`lib/approvals.py` の state machine 部分のみ Python 標準 unittest (`tests/test_approvals.py`) で自動化し、その他は手動 E2E チェックリスト。

## 前提セットアップ (各テスト共通)

- 作業ディレクトリ: `~/hermes-lite/` (= `/home/shohei/プロジェクト/hermes-lite`)
- 環境変数:
  - `DISCORD_WEBHOOK_URL` が `.env` に設定済み
  - `DISCORD_TOKEN` / `ALLOWED_USER_IDS` が systemd unit から渡されている
  - `HERMES_APPROVAL_COMMANDS_ENABLED=1` (default=0 なので明示的に opt-in)
  - `HERMES_APPROVAL_AUTHORIZED_USER_IDS` を ALLOWED_USER_IDS と同じ (or 部分集合) に設定
- DB 初期化: `rm -f var/approvals.sqlite` (各回クリーンスタート可)
- bot 起動: `systemctl --user restart hermes-lite-discord.service`
- proposer 試走: `bin/run-claude.sh approval-demo-proposer`

## 自動テスト一覧 (tests/test_approvals.py で実装)

各テストは tmpfile DB を使い、`HERMES_APPROVALS_DB` を tmpdir に差し替えてから approvals を import する形で隔離。

| ID | 検証内容 |
|---|---|
| T05_expire | TTL 切れ pending を direct insert → `sweep_expired()` → row が expired |
| T06_double_take | approved 1 件 → `take()` 2 回 → 1 回目 row 返却 / 2 回目 None |
| T08_double_decide | pending → decide(approve) → 同 ID に decide(approve) → 2 回目 None |
| T09_invalid_payload | 未知キー / end<=start / 過去日時 / executor_job mismatch → ValueError |
| T12_done_state_guard | pending に直接 `done()` → ValueError |
| T15_schema_version_mismatch | `PRAGMA user_version=99` 後に `get` → RuntimeError |
| T18_stale_executing_sweep | executing で `started_at=now-1900` → `sweep_stale_executing()` → row=failed |
| T20_stale_approved_sweep | approved で `decided_at=now-700` → `sweep_stale_approved()` → row=failed |
| T21_decide_after_expire_atomic | pending で `expires_at < now` → `decide(approve)` → None (sweep 待ち) |
| T23_enqueue_executor_mismatch | `enqueue(executor_job="wrong-job", action="calendar.create", ...)` → ValueError |
| T24_list_cli | 各 status の row を投入 → `list(status="pending")` 等 → 該当 row のみ |
| T26_unauth_handler_call | `HERMES_APPROVAL_AUTHORIZED_USER_IDS=12345` 下で `handle("approval approve abcd1234", user_id=999)` → `unauthorized` 返却 / DB 変化なし |
| T27_id_collision_retry | pre-insert で 1 ID 占有 → `enqueue()` 連発で別 ID に成功 / 5 回連続 collision なら RuntimeError + exit 3 |
| T28_tool_use_evidence_unavailable | `extract_tool_calls()` が None を返す mock proc_result → fail_during_executor(side_effect=True) |
| T29_executor_unit_with_mock | `invoke_claude_p` と `notify_discord` を差し替えた executor 統合自動テスト。create_event 1 回成功 / 2 回 / 別 tool / input mismatch / 0 回 / is_error / ERROR result の各 status 遷移を検証 (Codex 指摘の補完) |

## 手動チェックリスト

各テストの完了は □ を ☑ に変更してチェック。

### T01_enqueue (proposer 起票)

前提: bot 停止 (DB 操作のみ検証)、または bot 起動済みでも可。

```bash
# Calendar が "approval demo" の重複で汚れないよう既存 demo event は事前に手動削除
bin/run-claude.sh approval-demo-proposer
```

- [ ] exit 0
- [ ] `var/approvals.sqlite` に pending row 1 件 (`sqlite3 var/approvals.sqlite "SELECT id, status FROM approvals WHERE proposer_job='approval-demo-proposer' ORDER BY created_at DESC LIMIT 1"`)
- [ ] Discord に承認依頼本文 (`🔐 承認依頼 #<8hex>` から始まる) が投稿された
- [ ] 本文に `approval approve <8hex>` の形式で承認コマンドが含まれている

### T02_approval_executes (yes 承認 → executor 起動 → Calendar 作成)

前提: T01 実行後、bot 起動済み、`HERMES_APPROVAL_COMMANDS_ENABLED=1`。

```
Discord で: approval approve <id>
```

- [ ] bot が `✅ [OK] #<id> 承認 → executor 起動 (unit=hermes-exec-<id>-<ts>)` を返信
- [ ] `systemctl --user status hermes-exec-<id>-<ts>` が 30 秒以内に "Active: inactive (dead)" + ExitCode=0 (完了)
- [ ] `journalctl --user -u hermes-exec-<id>-<ts>` に `[OK approval #<id>]` を含む行がある
- [ ] Calendar 側に「翌日 14:00 デモ予定 (approval demo)」イベントが 1 件作成された
- [ ] sqlite で `status='executed'` (`sqlite3 var/approvals.sqlite "SELECT status, finished_at FROM approvals WHERE id='<id>'"`)
- [ ] Discord に `[approval #<id>] [OK] ...` 通知

### T03_approval_rejects (no 却下)

前提: 新しい pending row を T01 で起こす。

```
Discord で: approval reject <id>
```

- [ ] bot が `❌ [REJECTED] #<id> 却下` を返信
- [ ] sqlite で `status='rejected'`、`decided_at` セット
- [ ] executor は起動しない (`systemctl --user list-units | grep hermes-exec-<id>` が空)
- [ ] Calendar に新規 event は作成されない

### T04_unauth_user (認可外ユーザー)

前提: ALLOWED_USER_IDS に含まれない別アカウントから DM / mention で投稿する手段がある場合のみ。

```
別ユーザーが Discord で: approval approve <id>
```

- [ ] bot は応答しない (既存の _should_react で弾かれる)
- [ ] bot ログ (`journalctl --user -u hermes-lite-discord.service`) に `unauthorized user=<id>` 警告
- [ ] DB は変化なし

### T07_unknown_id (DB に無い ID)

前提: bot 起動済み、認可ユーザー。

```
Discord で: approval approve deadbeef
```

- [ ] bot が `⚠️ [WARN] #deadbeef は不明 (期限切れ or タイポ)` を返信
- [ ] DB は変化なし

### T10_disallowed_unchanged (disallowed-tools.txt 不変)

```bash
git stash && BEFORE=$(sha256sum lib/disallowed-tools.txt | cut -d' ' -f1)
git stash pop
AFTER=$(sha256sum lib/disallowed-tools.txt | cut -d' ' -f1)
echo "before=$BEFORE"; echo "after=$AFTER"; [ "$BEFORE" = "$AFTER" ] && echo "OK"
```

- [ ] BEFORE == AFTER (sha256 完全一致)

### T11a_question_fallback (approval prefix なしの "yes" は通常質問応答)

前提: bot 起動済み、`HERMES_APPROVAL_COMMANDS_ENABLED=1`。

```
Discord で: yes
```

- [ ] bot は通常の `_handle` に流し、Claude が「yes って何のことですか？」のような応答を返す
- [ ] DB は変化なし

```
Discord で: yes abcd1234
```

- [ ] 上と同様 (approval prefix が付いていないので予約語化されない)

### T11b_unknown_id_no_fallback (approval prefix 付きで DB miss → fallback しない)

```
Discord で: approval approve deadbeef
```

- [ ] bot が `⚠️ [WARN] #deadbeef は不明` を返信 (T07 と同じ)
- [ ] claude-runner には流れない (bot ログに claude-runner 起動の痕跡なし)

### T11c_regex_variations (大小文字、`#` 任意、空白差分)

前提: 同じ pending ID `abcd1234` を T01 で起票。

各メッセージで個別の pending を用意するか、同 ID に対して decided な response をテスト。

```
Discord で: APPROVAL APPROVE   ABCD1234
```

- [ ] handler が小文字化して同じ ID として処理
- [ ] (pending なら) bot が `✅` 返信、(approved なら) bot が `⚠️ ... はすでに approved` 返信

```
Discord で: approval approve #abcd1234
```

- [ ] 上と同様 (# を任意で受ける)

### T13_db_path_consistency (bot 経路と CLI 経路で同一 sqlite)

前提: bot 起動済み。proposer で 1 件 enqueue 直後に CLI で get 試行。

```bash
bin/run-claude.sh approval-demo-proposer
# Discord に出た本文から ID を取る
AID="<8hex>"
python3 lib/approvals.py get --id "$AID"
```

- [ ] CLI 側 get の出力 JSON が bot 側の `proposer_job='approval-demo-proposer'` row と完全一致
- [ ] `lsof | grep "approvals.sqlite" | awk '{print $9}' | sort -u` で参照されている path が 1 つだけ (bot プロセスと CLI プロセスが同じ inode)

### T14_systemd_run_failure (systemd-run が無い)

前提: bot を **一時的に** `HERMES_SYSTEMD_RUN_BIN=/nonexistent` 環境変数を追加して再起動。

```bash
# 一時 override (gen8 の場合)
mkdir -p ~/.config/systemd/user/hermes-lite-discord.service.d
cat > ~/.config/systemd/user/hermes-lite-discord.service.d/test.conf <<EOF
[Service]
Environment="HERMES_SYSTEMD_RUN_BIN=/nonexistent"
EOF
systemctl --user daemon-reload && systemctl --user restart hermes-lite-discord.service
# テスト後に rm して reload
```

```
Discord で: approval approve <id>  (T01 で起票したもの)
```

- [ ] bot が `⚠️ [WARN] #<id> 承認は記録したが executor 起動失敗 → failed に変更` を返信
- [ ] sqlite で `status='failed'`、`result_text` に `systemd-run failed: ...` を含む

### T16_tool_use_count_violation (mock claude で 2 回呼び出し)

前提: `CLAUDE_BIN` を mock スクリプトに差し替えた状態で executor を直接起動する手動テスト。

```bash
# mock スクリプト (tests/mock_claude_double.sh などに置く)
cat > /tmp/mock_claude_double.sh <<'EOF'
#!/usr/bin/env bash
# claude -p ... の最後の引数は無視し、固定 JSON を返す
cat <<JSON
{
  "result": "[OK approval #abcd1234] dummy → htmlLink=https://example.com/evt1",
  "is_error": false,
  "tool_uses": [
    {"name": "mcp__claude_ai_Google_Calendar__create_event", "input": {}},
    {"name": "mcp__claude_ai_Google_Calendar__create_event", "input": {}}
  ]
}
JSON
EOF
chmod +x /tmp/mock_claude_double.sh

# pending → approve まで CLI で進めておく
AID=$(echo '{"summary":"mock","start":"2026-06-25T14:00:00+09:00","end":"2026-06-25T15:00:00+09:00","timeZone":"Asia/Tokyo"}' \
  | python3 lib/approvals.py enqueue --proposer test --executor calendar-create-executor --action calendar.create --summary "mock")
python3 lib/approvals.py decide --id "$AID" --decision approve

# executor を mock 起動
HERMES_APPROVAL_ID="$AID" CLAUDE_BIN=/tmp/mock_claude_double.sh python3 lib/approvals_executor.py
```

- [ ] executor exit 1
- [ ] sqlite で `status='failed_after_side_effect'`、`result_text` に `tool_use violation: create_event=2 other=[]` + `event_links` を含む
- [ ] Discord に `[WARN]` + `Created events:` + htmlLink リスト + 手動 cleanup 指示が投稿

### T17a_run_claude_export_ping (既存 ping ジョブ回帰なし)

```bash
bin/run-claude.sh ping
```

- [ ] exit 0
- [ ] `logs/ping/<ts>.json` の `.result` が `"稼働確認OK"` を含む
- [ ] cost.csv に新規行 (`is_error=false`)

### T17b_run_claude_export_mail_watch (既存 mail-watch ジョブ回帰なし)

```bash
bin/run-claude.sh mail-watch
```

- [ ] exit 0
- [ ] `logs/mail-watch/<ts>.json` の `.result` が 0 件時 `"[NOOP]"`、1 件以上時は通常本文
- [ ] Gmail ラベル `hermes-lite` → `hermes-lite/done` の遷移が起きている (該当 thread があれば)

### T19_handler_disabled_reservation (handler 不在時の予約語捕捉)

前提: bot 起動時に handler を読み込めない状態を作る。

```bash
mv gateway/discord/approval_handler.py gateway/discord/approval_handler.py.bak
systemctl --user restart hermes-lite-discord.service
```

- [ ] bot は起動成功 (`systemctl --user status hermes-lite-discord.service` Active)
- [ ] `journalctl --user -u hermes-lite-discord.service` に `approval_handler import failed; approval feature disabled` 警告

```
Discord で: approval approve abcd1234
```

- [ ] bot が `⚠️ [WARN] approval feature disabled (import failed; see journalctl)` を返信
- [ ] `_handle` には流れない (claude-runner が起動した痕跡なし)

後始末:
```bash
mv gateway/discord/approval_handler.py.bak gateway/discord/approval_handler.py
systemctl --user restart hermes-lite-discord.service
```

### T22_tool_use_input_mismatch (mock claude で input 改変)

前提: T16 と同じ mock 経路。input を payload と異なる summary に。

```bash
cat > /tmp/mock_claude_input_mismatch.sh <<'EOF'
#!/usr/bin/env bash
cat <<JSON
{
  "result": "[OK approval #abcd1234] altered → htmlLink=https://example.com/evt1",
  "is_error": false,
  "tool_uses": [
    {"name": "mcp__claude_ai_Google_Calendar__create_event", "input": {"summary": "ALTERED", "start": {"dateTime": "2026-06-25T14:00:00+09:00", "timeZone": "Asia/Tokyo"}, "end": {"dateTime": "2026-06-25T15:00:00+09:00", "timeZone": "Asia/Tokyo"}}}
  ]
}
JSON
EOF
chmod +x /tmp/mock_claude_input_mismatch.sh

# pending → approve まで進める (payload は summary="original")
AID=$(echo '{"summary":"original","start":"2026-06-25T14:00:00+09:00","end":"2026-06-25T15:00:00+09:00","timeZone":"Asia/Tokyo"}' \
  | python3 lib/approvals.py enqueue --proposer test --executor calendar-create-executor --action calendar.create --summary "original")
python3 lib/approvals.py decide --id "$AID" --decision approve

HERMES_APPROVAL_ID="$AID" CLAUDE_BIN=/tmp/mock_claude_input_mismatch.sh python3 lib/approvals_executor.py
```

- [ ] executor exit 1
- [ ] sqlite で `status='failed_after_side_effect'`、`result_text` に `input mismatch` + `diff` を含む
- [ ] Discord に WARN + diff + htmlLink

### T25_feature_flag_off (default=0 で既存挙動完全互換)

前提: `HERMES_APPROVAL_COMMANDS_ENABLED` を bot 環境から外す (= default `"0"`)。

```bash
# bot service の Environment から HERMES_APPROVAL_COMMANDS_ENABLED= 行を削除
systemctl --user restart hermes-lite-discord.service
```

- [ ] bot 起動ログに approval 関連の import / regex / sweep が一切出ない (`journalctl --user -u hermes-lite-discord.service -n 50 | grep -i approval` が空)

```
Discord で: approval approve abcd1234
```

- [ ] bot は通常の `_handle` に流し、Claude が「approval って何のことですか？」のような応答
- [ ] DB は変化なし

### 後始末 (各テスト完了後)

```bash
# テスト中に作った余分な systemd unit override を削除
rm -rf ~/.config/systemd/user/hermes-lite-discord.service.d/test.conf
systemctl --user daemon-reload
systemctl --user restart hermes-lite-discord.service

# Calendar 側のテスト用 event を手動削除 (デモ予定 / mock / altered)

# テスト用 mock スクリプトを削除
rm -f /tmp/mock_claude_*.sh
```
