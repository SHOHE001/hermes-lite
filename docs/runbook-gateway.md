# Discord / `agcc` から来たときの行動規範

このディレクトリは **Discord bot（gateway/discord）** からも **ローカル `agcc` シェル** からも claude が起動される。両方とも cwd は `~/hermes-lite/` で、CLAUDE.md が自動でロードされる。

## Discord 経由の依頼判別

ユーザーは Discord で自然文を投げてくる。それが「即興質問」なのか「ジョブ化したいもの」なのかを以下で振り分ける：

| 即興（その場で答える） | ジョブ化（jobs/ に作る） |
|---|---|
| 「今日の天気は？」 | 「毎朝の天気を Discord に流して」 |
| 「Slack の今日の話題まとめて」 | 「毎日夜にSlackをまとめて Notion に追記して」 |
| 「次の予定教えて」 | 「平日朝にカレンダーを Discord に投げて」 |

判別キー：「毎〜」「定期」「自動で」「いつも」「これからずっと」「ジョブにして」など、または継続性を匂わせる表現。
迷ったら一度だけ「ジョブにしておく？それとも今だけ答えるだけにする？」と聞く。

## ジョブを新規に作る手順

最寄りの既存ジョブをコピーして雛形にする。最低限のテンプレは `jobs/ping/`。

1. **作る**
   ```bash
   cp -r jobs/ping jobs/<name>
   $EDITOR jobs/<name>/prompt.md     # Claude にやらせたいこと（自然文）
   $EDITOR jobs/<name>/job.env       # ALLOWED_TOOLS / MAX_TURNS / NOTIFY_RESULT 等
   ```

   命名規則：英小文字・数字・ハイフンのみ。動詞 + 対象が分かる短い名前。例：`morning-brief`, `news-recap`, `slack-summary`。

2. **`job.env` の主な変数**

   | 変数 | 役割 | 例 |
   |---|---|---|
   | `ALLOWED_TOOLS` | 共通禁止リストから個別解禁したいツール（空白区切り） | `"WebSearch WebFetch"` |
   | `MAX_TURNS` | 暴走防止 | `5` |
   | `TIMEOUT_SEC` | claude -p の打ち切り秒 | `180` |
   | `MAX_BUDGET_USD` | コスト上限の保険。初回キャッシュ込みで `0.5` 以上推奨 | `"0.50"` |
   | `MODEL` | `sonnet` / `opus` / `haiku` / `fable` | `"sonnet"` |
   | `NOTIFY_RESULT` | `"1"` で結果を Discord webhook に投稿 | `"1"` |

3. **スケジュールを書く**（定期実行する場合のみ）

   ```bash
   mkdir -p ~/.config/systemd/user/claude-agent@<name>.timer.d
   cat > ~/.config/systemd/user/claude-agent@<name>.timer.d/schedule.conf <<EOF
   [Timer]
   OnCalendar=*-*-* 07:00:00
   EOF
   ```

   よく使う `OnCalendar` 例：

   | 間隔 | 書き方 |
   |---|---|
   | 毎日 7:00 | `*-*-* 07:00:00` |
   | 平日 9:00 | `Mon..Fri *-*-* 09:00:00` |
   | 1 時間ごと | `hourly` |
   | 30 分ごと | `*:0/30` |

4. **登録 → 試走 → 結果報告**

   ```bash
   systemctl --user daemon-reload
   systemctl --user enable --now claude-agent@<name>.timer
   bin/run-claude.sh <name>     # 試走（必須）
   ```

   試走結果（`logs/<name>/<timestamp>.json` の `.result`）を見て、失敗したら `prompt.md` を直す。
   最後にユーザーに「**作ったジョブ名・スケジュール・試走結果**」を簡潔に報告。

## やってはいけないこと

- ❌ **既存ジョブの削除・disable をユーザー確認なしにやらない**
- ❌ **1 メッセージで複数ジョブを一気に作らない**（暴走防止、1 ターン 1 ジョブまで）
- ❌ **`lib/disallowed-tools.txt` を勝手に書き換えない**（安全網）
- ❌ **`bin/run-claude.sh` 内に `--dangerously-skip-permissions` を追加しない**
- ❌ **`.env` をログ／コメント／チャットに出さない**（DISCORD_TOKEN / webhook URL が入っている）
- ❌ **`.env` を `git add` しない**（`.gitignore` で除外済み）
- ❌ **隣の `~/claude-watch/` や `skills-loop/` には触らない**（別系統 / 別目的）
- ❌ **`~/.claude/settings.json` の allow/disallow を編集しない**（gateway 側で制御）
