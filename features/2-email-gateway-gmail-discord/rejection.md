# Codex 設計レビュー指摘の対応方針（rev2 で裁量採用）

Codex 3 persona から計 8 件の blocking 指摘。Phase 1 MVP として裁量で以下のように対応する。

## 採用（rev2 plan に追記して implementer に伝える）

| Finding | 対応 |
|---|---|
| MAX_TURNS=30 が 33 turn 見積もりに不足 | `job.env` の MAX_TURNS を **40** に上げる。件数上限を **5 thread** に下げて余裕を持たせる |
| ラベル変更先 → 通知後 では回復不可（通知本文がログに残らない） | 順序を **通知先・ラベル変更後** に反転。重複通知を Phase 1 では許容（運用初期の許容コスト） |
| 空 result スキップが全ジョブの public behavior 変更 | `bin/run-claude.sh` 改修 2 を **opt-in** に変更: `job.env` の `SUPPRESS_RESULT_IF` 環境変数で制御。mail-watch のみ `SUPPRESS_RESULT_IF=[NOOP]` を設定 |
| `hermes-lite/done` ラベル未作成時の挙動が曖昧 | prompt.md に **fail-fast**: `list_labels` で `hermes-lite` と `hermes-lite/done` の両方が見つからなければ即異常終了。MCP ツールで `create_label` は実装しない |
| `lib/disallowed-tools.txt` の Calendar entry 確認 | 確認済み（`mcp__claude_ai_Google_Calendar__create_event` は既に登録されている）。docs に「既存禁止リストにより Calendar 書き込みは自動的に拒否される」と明記 |
| `search_threads` の古い順ソート根拠 | `get_thread` で取得した `internalDate` を使って prompt 内で昇順ソートする旨を prompt.md に明記 |

## 棄却（rev2 の方針を維持）

| Finding | 棄却根拠 |
|---|---|
| LLM 任せ設計が複雑すぎる、決定的スクリプトに分けるべき (contrarian) | Hermes-lite の運用思想は「MCP ツールを LLM が使う」を基本とする。Bash+curl で Gmail を直接叩く構成は MCP の意味を消す。Phase 1 では LLM 中心を維持し、運用で問題が出たら別 Issue で見直す |
| thread 単位ラベル変更が既存 message 単位運用と非互換 | 現状 `hermes-lite` ラベル付きメールはユーザーが手動で運用しており、message 単位で付ける現実的なケースは想定していない。docs に「ラベルは thread レベルで付与する」運用を明記 |
| `.env` set -a が全ジョブに環境変数を漏らす | 現在 `.env` には `DISCORD_WEBHOOK_URL` 等の運用必須キーしか入っていない想定。問題発生時に別 Issue で見直す |
| Non-Goals の 1 行要約 vs 設計内の要約抽出が矛盾 | 1 行要約は claude が prompt 指示に従って生成する自然な処理。「長文要約しない」の意図は伝わるので Non-Goals は維持 |
| T08 のエラー試験条件が不安定 | T08 を「`hermes-lite/done` 欠落時の fail-fast 検証」に明確化（list_labels で検証 → 異常終了 → wrapper の NOTIFY_ON_ERROR で通知） |
| set -a の元状態保存 | サブシェル内で行わない理由として、bin/run-claude.sh は単一 invocation で寿命終了するため不要 |
