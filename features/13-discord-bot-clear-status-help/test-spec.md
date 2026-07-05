# test-spec: #13 Discord スラッシュコマンド機構

`project_type: jobs` のため手動チェックリスト形式。ただし本 Issue は Python コード + `unittest` の自動テストを持つハイブリッド。**自動（`tests/test_commands.py`）** と **手動（discord 実機）** の 2 系統で担保する。

## 自動テスト（implementer が実装・実行）

`tests/test_commands.py`（system python3 unittest, discord 非依存）。実行:

```bash
cd ~/hermes-lite && python3 -m unittest tests.test_commands -v
```

期待: T01〜T16 全 pass。

| ID | 検証内容 |
|---|---|
| T01_dispatch_help | `/help` 応答に `/clear` `/status` `/help` を全て含む |
| T02_clear_deletes_session | 実 `SessionStore.set/get` でセッション書込 → `/clear` → 別インスタンス & 長寿命インスタンスの両方で `None`（WAL 反映）+ `✅` |
| T03_clear_no_scope | `scope_key=None` → DB 未変更 + `ℹ️`、例外なし |
| T04_unknown_command | `/foobar` → `❓` + `/help` 案内（`UNKNOWN_COMMAND_MESSAGE`） |
| T05_help_lists_all_registry | `render_help(COMMANDS)` が全 name を含む |
| T06_handler_exception_fixed | custom registry に例外 handler → `COMMAND_ERROR_MESSAGE`、global `COMMANDS` 不変 |
| T07_status_renders_cycle | tmpdir に `features/.loop/state.json`(cycle=12) → `/status` に `12` と `cycle` |
| T08_status_missing_files | ファイル無し → 例外なし・`N/A` フォールバック |
| T09_is_command_true_false | `is_command("/help")=True` / `is_command("hello")=False` / `parse("hello")=None` |
| T10_parse_slash_with_args | `parse("/status verbose")=("status","verbose")`、handler が `args="verbose"` 受領 |
| T11_status_skips_broken_json | `broken.json` skip・`good.json`(result 有) 採用、例外なし |
| T12_status_ignores_jsonl | `.jsonl` のみ → 直近ジョブ=`N/A`、例外なし |
| T13_slash_namespace_boundary | `is_command` で `/tmp/foo` `//x` `/ 相談` `/?` `/`→False、`/clear` `/a-b_c`→True |
| T14_classify_routing_order | 2 引数 `classify(approval文,True)="approval"` / `("/clear",False)="slash"` / `("hello",False)="handle"` / `("/tmp/foo",False)="handle"` |
| T15_parse_trailing_ws | `parse("/help   ")=("help","")` / `parse("/status  verbose ")=("status","verbose")` |
| T16_import_safe_no_files | 任意 cwd / gloop ファイル不在で `import commands` 成功 → `/help` 応答返る |

## 手動テスト（discord 実機。人間が STEP 8 hold 後に実施）

### 前提セットアップ

- [ ] `commands/` 実装 + `bot.py` 分岐 + `session_store.py` context manager 化がマージ（or PR ブランチ）済み
- [ ] `systemctl --user restart discord-gateway.service` で bot 再起動
- [ ] `journalctl --user -u discord-gateway.service -f` でログ監視

### コマンド

Discord で以下を送信して応答を確認する。

### 期待値（チェックボックス）

- [ ] DM で plain `/help` → コマンド一覧（`/clear` `/status` `/help`）がコードブロックで返る
- [ ] 通常 guild channel で `@bot /help` → 一覧が返る
- [ ] 通常 guild channel で mention 無し `/help` → **無視**される（bot が反応しないスコープ）
- [ ] `/clear` → `✅ セッションをクリアしました` → 直後に自然文発話 → **過去会話を忘れている**（新セッション）
- [ ] `/status` → cycle / 直近 pause / watcher alive・pid / 直近ジョブ が箇条書きで返る
- [ ] `/unknown-command` → `❓ 未知のコマンド。/help で一覧`
- [ ] 通常文（`/` 始まりでない）→ 従来通り claude 応答（退化なし）
- [ ] `/tmp/foo` → 従来通り claude に渡る（コマンド横取りされない）
- [ ] （flag on 時）`approval approve #xxxx` → 従来通り approval 処理（slash より優先）
- [ ] handler 内部エラーを意図的に起こしても bot が落ちない（`⚠️ コマンド実行に失敗しました…` 固定文言、journalctl に詳細）
