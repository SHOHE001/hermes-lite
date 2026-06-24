# debug-spec: #6 final review 裁量採用の残置指摘

## Codex final review loop 1 (2026-06-24) — 裁量で passed

3 persona aggregate: architect=fail(1), contrarian=pass(0), migration=fail(1)。
blocking 2 件は**いずれも「過去の fail review artifacts が diff に混在」**で、実装本体への blocking は無し。これは gloop が `features/` を履歴管理する運用設計上の構造的事象であり、squash merge 後は 1 commit にまとまるので Issue 自体の品質には影響しない。**裁量で passed**。

### 残置指摘（実装上の意識として）

- **[architect, high / migration, high] 古い codex-final-*.yaml が diff に混入**
  - 構造的事象。STEP 8 の squash merge で全 artifact が 1 commit に固まるので、後段の自動判定が混乱することは無い。
- **[architect, medium] feature 管理ファイルが本体変更と同コミット**
  - gloop の運用設計（finalize-feature.mjs が features/ を git に add する）に従ったもの。承認済み運用。
- **[contrarian, medium] codex-input.md の test summary 欄が空**
  - build-codex-input.mjs が test-summary.json の中身を取り込まない実装になっている（11 セクションは認識したが Test summary が空）。これは build-codex-input.mjs 自体の改善余地で、本 Issue のスコープ外。
- **[contrarian, medium] _DEFAULT_SOUL と SOUL.md の二重管理**
  - plan.md / rejection.md で議論済み。Phase 2 で削除条件を決める前提。T02 でドリフト検知済み。
- **[contrarian, low] `.rstrip('\n')` の方が外部ファイル化の意味に沿う**
  - 現状の prompt には末尾改行が無いので実害無し。将来 SOUL.md を編集して末尾改行を意図的に含めたいケースが出たら別 Issue で対応。
- **[migration, medium] APPEND_SYSTEM_PROMPT alias の monkeypatch 動作**
  - 旧実装で `claude_runner.APPEND_SYSTEM_PROMPT = "..."` のように monkeypatch していたコードがある場合、`_load_soul()` 経由になったため挙動が変わる。grep で確認:
    ```bash
    grep -rn 'APPEND_SYSTEM_PROMPT' . --include='*.py' --exclude-dir='.git'
    ```
    → 本リポジトリ内では `gateway/discord/claude_runner.py` 以外に参照無し。よって実害無し。
- **[migration, medium] test-summary.json と codex-input.md の不整合**
  - build-codex-input.mjs の改善余地（contrarian と同根）。本 Issue スコープ外。
