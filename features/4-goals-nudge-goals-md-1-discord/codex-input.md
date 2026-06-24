# Non-Goals (本 Issue で実装しない項目 — Codex は越権指摘しないこと)
- 双方向対話による目標更新（Discord で「進捗報告」を返したら goals.md に追記する系）
- 「最終 nudge 日」の自動更新（前回 nudge から N 日経ったかの判定）
- 目標達成時の自動 archive / 移動
- goals.md のスキーマ厳密検証（壊れていても可能な範囲で nudge し、parse 不能セクションは本文に「⚠ parse 失敗: <タイトル>」と 1 行出すだけにする）
- Calendar / Notion / Slack 等 Discord 以外の出力チャネル
- 旧形式（frontmatter / `最終 nudge 日`）への自動変換

# In-Scope / Out-of-Scope
| In-Scope | Out-of-Scope |
|---|---|
| `goals.md` を hermes-lite repo root 直下に 1 枚作る（雛形 + コメント付き） | 複数ファイル化（`goals/<theme>.md`）はしない（YAGNI、必要になったら拡張） |
| `jobs/goals-nudge/` を新規追加し、`goals.md` を読み込んで Discord に nudge を投げる | ユーザー返信を受けて goals.md を書き換える双方向対話 |
| 週 1 回（毎週日曜 20:00 JST）の systemd timer 登録**手順**を `docs/jobs-goals-nudge.md` に書く（既存 `docs/jobs-mail-watch.md` と同じ温度感。drop-in ファイル本体は repo 管理せず、user 環境の `~/.config/systemd/user/claude-agent@goals-nudge.timer.d/` 配下に手動で配置する） | 多言語化、TZ パラメータ化、systemd version 別の `Timezone=` 採用 |
| 期限・状態フィルタ・件数上限・本文整形・NOOP 判定は **prompt.md の自然文指示**で Claude にやらせる（hermes-lite の不変ルール: `claude -p` を subprocess で呼ぶ形を基本） | deterministic な parser/formatter スクリプト（不変ルールに反する。CLAUDE.md「課金経路」と「ビルド方針」参照） |
| `状態: active` の目標のみを通知対象とし、`achieved`/`paused` は除外（値は **trim + lowercase 正規化**して比較） | LinearなどのタスクツールとのSync |
| 期限が当日〜7 日以内の目標は本文で強調、超過しているものは「期限超過 N 日」と明示。期限が今日と同日のものは「あと 0 日」+ `⚡` | 個別目標ごとの頻度設定（全目標まとめて週 1） |
| 対象 0 件 (`goals.md` 無し / active が 0 件) なら `[NOOP]` を返して Discord 投稿スキップ | リマインドの応答文を分析する LLM judge 層 |
| active 表示の上限 10 件、超過分は「ほか N 件」と表示（変数名 `total_active` / `overflow_count` で本文 §3 内に区別） | 件数上限のユーザー設定（10 固定で十分） |
| 旧形式（先頭の `---` frontmatter ブロック、`最終 nudge 日:` 行）は **除去 / 無視**してパースする（積極エラーにしない） | 旧形式を新形式へ自動変換する migration スクリプト |
| `docs/jobs-goals-nudge.md` にセットアップ手順を書く（gen8 が `Asia/Tokyo` であることを前提として明記。**既存 `goals.md` がある場合は上書きせず内容確認** の手順も含める） | Calendar / Notion / Slack 等 Discord 以外の出力チャネル |
| `ALLOWED_TOOLS` を `Read Bash(date:*)` のように **明示的に最小許可** に絞る | 共有 runner (`bin/run-claude.sh`) の挙動変更（責務境界を保つため、本 Issue では一切編集しない） |

# Test summary
```json
"3/17 cases auto-verified via dry-run (T01_setup, T01, StepC_active_path_and_date_dash_d). All Discord-posting cases (T02..T11) are user_manual_required because the codebase deliberately routes through bin/run-claude.sh which posts to Discord on success; sending to a real channel without user approval would violate the CLAUDE.common.md 'pre-confirmation for outbound messages' rule. Step C dry-run used NOTIFY_RESULT=0 as a temporary guard and verified Bash(date:*) accepts both 'date +' and 'date -d' invocations (permission_denials=[]). MAX_TURNS raised from 5 to 20 after Codex round 1 to fit active 10件 + per-goal date validation."
```

