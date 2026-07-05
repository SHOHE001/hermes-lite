# ROADMAP

hermes-lite は NousResearch/hermes-agent の体験を Claude Max OAuth 枠の `claude -p` 経由で再現する自作プロジェクト。
本ファイルは gloop が消化していくフェーズ・ゴールを定義する。

## Phase 1: 受信→カレンダー半自動登録パイプライン ✅

- Phase Milestone: `Phase 1`
- Goal: メール（および将来 LINE 等）の受信を起点に、予定候補を抽出 → Discord で承認 → Google Calendar に登録、までを通すパイプラインを完成させる。
- 完了条件: Phase 1 milestone の `type:feature` open issue が 0 件。
- 想定構成:
  1. SOUL.md による Hermes 人格定義の一元化（Discord runner と subagent の単一ソース化）
  2. 承認ゲート付き書き込みパターンの確立（job 単位で disallowed 解禁、Discord「yes」で発火する雛形）
  3. Email gateway（IMAP polling job、受信 → Discord 通知）
  4. メール → 予定抽出 → Discord 承認 → Google Calendar create の E2E 接続

## Phase 2: 自己照会・長期目標 🔒

- Phase Milestone: `Phase 2`
- Goal: 過去会話の横断検索と、長期目標 + 周期的 nudge により、エージェント主導の継続的な自己フォローを実現する。
- 完了条件: Phase 2 milestone の `type:feature` open issue が 0 件。
- 想定構成:
  5. Goals + 定期 nudge（`goals.md` + 週次 cron + Discord）
  6. FTS5 全セッション検索（LLM 要約層なしの grep 相当、コストゼロ版）

## Phase 3: 運用基盤の拡張と物理 PC 連携 🔒

- Phase Milestone: `Phase 3`
- Goal: Discord -p セッションの長時間運用を支える基盤を整え、さらに gen8 サーバー単体に閉じていた claude の稼働範囲を、SSH 経由でメイン Windows PC の GUI 操作まで拡張する。
- 完了条件: Phase 3 milestone の `type:feature` open issue が 0 件。
- 想定構成:
  7. Discord -p セッションの自動コンパクション（要約引き継ぎ方式）
  8. PC SSH × Computer Use 基盤（Discord 経由で Windows GUI 操作）

## Phase 4: 家電・IoT 連携 🔒

- Phase Milestone: `Phase 4`
- Goal: SwitchBot Hub / 温湿度計 / スマート家電を hermes-lite から操作できるようにし、Discord 上で自然文からスケジュール登録・即時操作・状態照会までカバーする。
- 完了条件: Phase 4 milestone の `type:feature` open issue が 0 件。
- 想定構成:
  9. SwitchBot 家電スケジュールの自然言語登録・実行（エアコン / LED 照明 / 温湿度計 read）

---

Phase の完了は `gh issue list --milestone "Phase N" --label "type:feature" --state open` が
0 件になったら `🚧 → ✅` に更新する（`loop-phase-close-check.mjs` が自動で行う）。
