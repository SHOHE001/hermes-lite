# gloop / watcher / worker が落ちたときの行動規範

`/gloop` の watcher daemon や worker pane、または `claude-agent@*.service` などのバックグラウンドプロセスが落ちた／pane が消えた／サイクルが進まない、と判明したら、**「とりあえず再起動」をやらない**。先に死因を特定し、再現確認まで取ってから対処する。

## 必ずやる手順

1. **死亡を確認する**（思い込みで動かない）
   - `pgrep -af 'gloop/scripts/loop-tmux-watcher'` で watcher 生死
   - `tmux list-panes -F '#{pane_id} #{pane_current_command}'` で worker pane 生死
   - `tail -50 features/.loop/watcher.log` で watcher 側の最後のメッセージ
   - `jq '{current_cycle, last_cycle_at, recent_cycles: .recent_cycles[-3:]}' features/.loop/state.json` でサイクル進行
2. **死因を仮説立てて再現する**
   - watcher.log / `tmux capture-pane -t <pane>` / journald (`journalctl --user -u claude-agent@<name> -n 100`) で症状を読む
   - 仮説が立ったら、**最小手数で同じ症状を再現する**（例: `tmux split-window` で空 pane を作って claude を起動し、`set remain-on-exit on` で exit 後の画面を捕まえる）
   - 再現できなければ仮説は外れ。別の仮説を立てる
3. **修正してから再起動する**
   - 設定変更・スクリプト修正・環境準備が済んでから `/gloop` を打ち直す
   - 「もう一回 /gloop 打ってみよう」は禁止。同じ理由でまた死ぬだけ
4. **ユーザーに報告**
   - 「死因」「再現コマンド」「採った対処」を 1 メッセージで簡潔に伝える

## なぜこれが重要か

watcher / worker は無人運用が前提なので、症状を残さず再起動すると同じ落とし穴を何度も踏む。落ちた瞬間が一番情報が残っているので、その場で死因を取りきる。これは [[推測禁止ルール]] の延長で、「動かない原因の推測で再起動を選ばない」と同義。

## 既知の落とし穴（順次追記）

- **そもそも tmux 内で起動していない**: `/gloop` / `node loop-tmux-start.mjs` を呼んで `ERROR: $TMUX is not set. Run inside a tmux session.` で弾かれるパターン。呼び元 shell が tmux session の外（素の SSH bash、systemd ユニット、Claude Code のバックグラウンドジョブ shell など）にいると `$TMUX` が継承されず、安全側で起動拒否される。**対処**: 既存の tmux session に attach (`tmux attach -t <session>`) してから claude を起動 → `/gloop` を打つ。新規なら `tmux new -s <name>` で session を作ってその中で立ち上げる。`TMUX` を偽装するのは split-window が同じソケットに張れないと壊れるので非推奨。

- **新規 tmux pane での `claude --dangerously-skip-permissions` 初回プロンプト** (2026-06-24 修正済み): 新しい pane で起動すると Bypass Permissions 同意プロンプト（❯ 1. No, exit / 2. Yes, I accept）が出る。以前は `loop-tmux-start.mjs` が 8 秒後に `/gloop\nEnter` を送るだけで、Enter がデフォルトカーソル位置の「No, exit」を確定させて claude が即終了 → pane 消滅 → watcher が 10s で disappeared 検知して safe stop していた。同意状態を永続化する公式設定キー・抑制フラグ・環境変数は存在しないことを確認済み（`hasTrustDialogAccepted` は別物）。**対処**: `loop-tmux-start.mjs` で `tmux capture-pane` の出力に `Yes, I accept` が含まれていたら `Down` → 待機 → `Enter` を送って同意を通すよう修正した。
