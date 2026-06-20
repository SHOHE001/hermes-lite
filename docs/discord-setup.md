# Discord Gateway セットアップ手順

`~/hermes-lite/gateway/discord/` を gen8 で常駐させて、Discord (DM / スレッド / メンション) から `claude -p` を叩けるようにする手順。

実装プラン: `~/.claude/plans/discord-1-reactive-cocke.md`

---

## 1. Discord Developer Portal で App + Bot を作る

1. https://discord.com/developers/applications を開く (claude.ai と同じ Google アカウントでよい)
2. **New Application** → 名前 `hermes-lite` 等で作成
3. 左メニュー **Bot**:
   - **Reset Token** → 表示されたトークンをコピー (一度しか出ない)
   - **Privileged Gateway Intents** → **MESSAGE CONTENT INTENT** を ON
4. 左メニュー **OAuth2** → **URL Generator**:
   - Scopes: `bot`
   - Bot Permissions: `Send Messages`, `Read Message History`, `Create Public Threads`, `Send Messages in Threads`, `Use Slash Commands` (slash は将来用)
   - 生成された URL を開いて、自分の個人 Discord サーバーに招待

## 2. 自分の Discord User ID を取得

1. Discord クライアントで **設定 > 詳細設定 > 開発者モード** を ON
2. 自分のアイコン右クリック → **ID をコピー** → 数字列がコピーされる

## 3. .env を配置

```bash
cd ~/hermes-lite/gateway/discord
cp .env.example .env
chmod 600 .env
# エディタで開いて DISCORD_TOKEN と ALLOWED_USER_IDS を埋める
nano .env
```

`.env` 例:
```
DISCORD_TOKEN=MTI3...(秘密)
ALLOWED_USER_IDS=123456789012345678
HERMES_DISCORD_TIMEOUT_SEC=300
```

## 4. ローカル実行で動作確認

```bash
cd ~/hermes-lite/gateway/discord
set -a; . ./.env; set +a
.venv/bin/python bot.py
```

`logged in as ... allowed user ids: [...]` が出れば接続成功。
Discord で bot に DM を送ると応答が返るはず。Ctrl+C で停止。

## 5. systemd --user で常駐化

```bash
mkdir -p ~/.config/systemd/user
cp ~/hermes-lite/gateway/discord/systemd/discord-gateway.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now discord-gateway

# 確認
systemctl --user status discord-gateway
journalctl --user-unit discord-gateway -f
```

サーバー再起動後も自動起動させたい場合は `loginctl enable-linger shohei` (claude-watch でやってあれば不要)。

## 6. 動作確認チェックリスト

- [ ] DM で `hello` 送る → 応答が返る
- [ ] `~/hermes-lite/gateway/discord/sessions.sqlite` に `dm:<myid>` レコードが入る
- [ ] DM で続けて `さっきの話の続き` → 文脈保持されている (=resume が効いている)
- [ ] 「鎌倉時代を3000字で説明」→ 2〜3 メッセージに分割投稿される
- [ ] 別 Discord アカウントから DM → 無視される (`journalctl` に `unauthorized user=...` の WARN 1行)
- [ ] 親チャンネルで `@hermes-lite` メンション → 反応する
- [ ] スレッドを切る → bot が自動 join → スレッド内の発言に文脈継続で反応
- [ ] `systemctl --user restart discord-gateway` 後も続きが resume できる

## 7. トラブルシューティング

| 症状 | 対処 |
|---|---|
| 起動直後に `DISCORD_TOKEN is not set` | EnvironmentFile が読まれていない。`systemctl --user show discord-gateway -p Environment` で確認 |
| `ALLOWED_USER_IDS is empty - refusing to run` | `.env` の `ALLOWED_USER_IDS=` が空、または systemd 経由で読まれていない |
| 反応が一切ない | (a) MESSAGE CONTENT INTENT 未有効化 (b) bot がサーバーに招待されていない (c) `ALLOWED_USER_IDS` が違う |
| `⚠️ タイムアウト (300s)` | 重い質問。`HERMES_DISCORD_TIMEOUT_SEC` を伸ばす or 質問を分割 |
| 長文で投稿が途中で止まる | Discord rate limit。連続投稿の間に sleep 入れる改修要 |
| `⚠️ exit=1` で `Invalid session ID` 系 | 自動で再フレッシュされるはず。されない場合は `sqlite3 sessions.sqlite "DELETE FROM sessions"` |

## 8. 安全側の運用

- DISALLOWED_TOOLS には Slack/Gmail/Calendar/Notion の **送信系** と **CronCreate** と **破壊的 Bash** が入っている (`claude_runner.py`)。Discord 経由で勝手にメッセージ送信されない
- bot Token が漏れたら Developer Portal で Reset Token → `.env` 更新 → `systemctl --user restart discord-gateway`
- `.env` は `chmod 600` 厳守、git に commit しない (`.gitignore` 済)

## 9. 並列稼働

claude-watch (gen8:8765, iOS Shortcut) と Discord gateway は独立に動く。両方常駐させて構わない。`~/.claude/projects/` のセッションログは共通領域に積まれるため、Discord で始めた会話を後で `claude --resume` で続けることも理屈上は可能 (session_id が分かれば)。
