# Skill Auto-Generation Loop 運用ガイド

`~/hermes-lite/skills-loop/` の運用手順とトラブルシュート。

実装プラン: `~/.claude/plans/discord-1-reactive-cocke.md` (タイトル流用、内容は skill loop 用に上書き済み)

## アーキテクチャ (1ページ要約)

> **スコープ変更 (2026-07-20)**: 当初はグローバル `~/.claude/settings.json` の Stop hook で**全セッション**を収穫対象にしていたが、hermes-lite の対話作業セッションのみに縮小した（ユーザー指示。--bare 廃止後、レビュー用子 claude の Stop が notify-pc.sh を二重発火させ通知が連打された件が発端）。hook は**開発クローン** `~/プロジェクト/hermes-lite/.claude/settings.json`（git 管理外、ローカル配置）に登録。稼働クローン `~/hermes-lite/` には置かない — 置くと Discord bot / gloop / jobs の claude -p にも hook が効いてしまうため。

```
[Claude Code ターン終了 (開発クローンでの対話セッションのみ)]
        │ Stop hook
        ▼
~/プロジェクト/hermes-lite/.claude/settings.json (ローカル配置)
   "Stop": [on-stop.sh]
        │
        ▼
~/hermes-lite/skills-loop/bin/on-stop.sh
   - HERMES_SKILL_REVIEW_DISABLE / RUNNING チェック
   - stdin (hook event JSON) を /tmp/hermes-on-stop.XXX.json に保存
   - nohup で on-stop.py を background 起動 → 即 exit 0
        │
        ▼
on-stop.py
   - transcript_path から jsonl 読み込み
   - 直前ターン (最後の人間 user 発話 → 末尾まで) を抽出
   - prompts/skill-review.md (本家 _SKILL_REVIEW_PROMPT 移植) と合成
   - claude -p --output-format json で実行
        │
        ▼
claude -p (HERMES_SKILL_REVIEW_RUNNING=1)
   - Stop hook の再発火は HERMES_SKILL_REVIEW_RUNNING=1 環境変数の再帰ガードで防ぐ
   - (以前は --bare を使っていたが --bare は OAuth/keychain を読まないため Max 認証が通らず 30 日間 subprocess が全滅していた)
   - Edit / Write tool で ~/.claude/skills/hermes-lite/<name>/SKILL.md を直接編集
        │
        ▼
state/runs/on-stop-<ts>.json (実行ログ)
```

毎日 2:30 cron で **usage-tracker.py** が `~/.claude/projects/**/*.jsonl` を全スキャンし、`~/.claude/skills/hermes-lite/.usage.json` を更新。
毎週日曜 3:30 cron で **curator.py** が状態遷移 (active → stale → archived) と archive mv を実行。LLM は使わない。

## 停止と再開

| やりたいこと | コマンド |
|---|---|
| **緊急停止** (Stop hook 走らせない) | `export HERMES_SKILL_REVIEW_DISABLE=1` してから claude 起動 |
| 全プロセスで停止 | `~/プロジェクト/hermes-lite/.claude/settings.json` の Stop 配列から on-stop.sh エントリを削除 |
| 永続停止 | `crontab -e` で hermes-lite の2行を削除 + 上記 settings.json 編集 |
| 再開 | 上記の逆 (環境変数を unset / 設定を戻す) |

## 動作確認

```bash
# 直近のセッション jsonl で dry-run (claude は呼ばない)
LATEST=$(ls -t ~/.claude/projects/*/*.jsonl | head -1)
python3 ~/hermes-lite/skills-loop/bin/on-stop.py --dry-run --transcript "$LATEST" | less

# curator dry-run
python3 ~/hermes-lite/skills-loop/bin/curator.py --dry-run

# usage tracker (実行は冪等)
python3 ~/hermes-lite/skills-loop/bin/usage-tracker.py
```

## ログの場所

| ファイル | 内容 |
|---|---|
| `~/hermes-lite/skills-loop/state/runs/on-stop-*.json` | Stop hook 1回ごとの実行レポート (session_id, exit_code, stdout/stderr 一部) |
| `~/hermes-lite/skills-loop/state/runs/curator-*.json` | curator 1回ごとの transitions / archives |
| `~/hermes-lite/skills-loop/state/on-stop.log` | on-stop.sh が wrapper として出す stderr |
| `~/hermes-lite/skills-loop/state/usage-tracker.log` | cron からの usage-tracker 標準出力 |
| `~/hermes-lite/skills-loop/state/curator.log` | cron からの curator 標準出力 |
| `~/hermes-lite/skills-loop/state/curator_state.json` | last_run_at, run_count, last_run_summary |
| `~/.claude/skills/hermes-lite/.usage.json` | skill 別 last_used_at, use_count, state |

## トラブルシュート

| 症状 | 確認 / 対処 |
|---|---|
| Stop 後に何も書かれない | `tail -f ~/hermes-lite/skills-loop/state/on-stop.log` で wrapper エラー確認。次に `state/runs/` に新ログが出ているか |
| `[on-stop] recursion guard hit` ばかり出る | 親プロセスが `HERMES_SKILL_REVIEW_RUNNING=1` を持っている。再帰してないか `pstree -p $$` で確認 |
| skill ファイルが生成されない | `state/runs/on-stop-*.json` の `claude_stdout` を確認。`"Nothing to save."` なら正常 (本家プロンプトはこれを許容) |
| 既存手動 skill (agy-review 等) が編集された | プロンプト遵守失敗。Issue 化して prompts/skill-review.md の「Protected」節を強化 |
| Max枠を気にする | `state/runs/` の件数 = 1日のレビュー回数。多すぎる場合は `HERMES_SKILL_REVIEW_DISABLE=1` で一時停止 |
| archive されすぎる | `state/runs/curator-*.json` の archives を確認。閾値は `bin/curator.py` の `ARCHIVE_DAYS=90` |
| .usage.json が空 | usage-tracker.py を手動実行。それでも空なら hermes-lite skill が一つも生成されていないだけ |

## LLM Consolidation を後で ON にしたい場合

今は OFF (本家 default 同様)。ON にしたいときの手順:
1. 本家 `agent/curator.py` `_CURATOR_REVIEW_PROMPT` を取得して `prompts/curator-review.md` に保存
2. `bin/curator.py` に `--consolidate` フラグ追加、claude -p で curator-review.md を呼ぶ branch を実装 (--bare は使わない。Max OAuth が通らないため)
3. 週次 cron に `--consolidate` を追加

このプロジェクトの目的 (= Max枠で軽く回す) を考えると、しばらくは OFF のままで十分。

## ファイル一覧

```
~/hermes-lite/skills-loop/
├── bin/
│   ├── on-stop.sh             Stop hook 入口 (再帰防止 + background fork)
│   ├── on-stop.py             skill review 本体
│   ├── curator.py             7日サイクル状態遷移 (LLM 不使用)
│   └── usage-tracker.py       全 jsonl スキャンで .usage.json 更新
├── lib/
│   ├── usage_store.py         .usage.json CRUD
│   ├── skill_io.py            SKILL.md frontmatter 判定 (PyYAML 不要)
│   └── session_log.py         jsonl 直前ターン抽出
├── prompts/
│   └── skill-review.md        本家 _SKILL_REVIEW_PROMPT verbatim + hermes-lite 適応指示
├── state/                     (gitignore)
└── .gitignore
```

## 参考

- 本家プロンプト出典: https://github.com/NousResearch/hermes-agent/blob/65561e9d/agent/background_review.py#L45-L149
- 本家 Curator 出典: https://github.com/NousResearch/hermes-agent/blob/main/agent/curator.py
- Claude Code Stop hook 仕様: 公式 docs (https://docs.claude.com/) を参照
