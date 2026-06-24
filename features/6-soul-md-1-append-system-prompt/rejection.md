# Rejection log for #6

## Codex design loop 1 (2026-06-24)

3 persona aggregate verdict=fail, blocking=6。全件採用して plan を改訂。

### 採用した指摘（plan に反映）

1. **[architect/contrarian/migration, high] Discord 固有文言を全 jobs に流すのは過剰スコープ + 後方互換破壊**
   - 採用: bin/run-claude.sh への組み込みを **本 Issue から外す**。Phase 1 は gateway/discord/claude_runner.py のみ SOUL.md 化。全 jobs への適用は別 Issue（follow-up）に切り出す。

2. **[architect/contrarian/migration, high] rollback の「SOUL.md 退避で旧挙動同等」が成立しない**
   - 採用: rollback 記述を「git revert が必要。SOUL.md 退避は人格無し degrade（旧 ハードコード文言には戻らない）」と修正。

3. **[architect, high] run-claude.sh と claude_runner.py の二重注入リスク**
   - 採用: bin/run-claude.sh を触らないので二重注入は発生しない。今の Discord runner は run-claude.sh を経由せず claude CLI を直接呼んでいる旨を plan に明記。

4. **[architect/contrarian/migration, medium] Python 側の before/after コードスニペットが不足**
   - 採用: claude_runner.py の `_build_cmd()` の before/after を plan に追加。

5. **[contrarian/migration, medium] T05/T06 が破壊的 (mv / : >)、復元失敗時のリスク**
   - 採用: 一時 SOUL.md を別パス（HERMES_HOME を一時 dir に向ける環境変数経由）に置く方式、または monkeypatch ベースのスモークテストに変更。trap 復元手順も明記。

6. **[migration, medium] shell と Python の空判定不一致**
   - 採用: bin/run-claude.sh への組み込みを今回外したので、空判定の二重実装問題自体が無くなる。Python 側だけ `read_text().strip()` で判定。

7. **[architect, medium] SOUL.md と CLAUDE.md 排除条項の命名衝突**
   - 採用: SOUL.md 先頭にも「本家パイプライン生成物ではない / 静的管理 / 更新責任は人間」と明記。CLAUDE.md 側にも 1 行注記を入れる。

8. **[contrarian, medium] より単純な代替案（Discord runner のみ外部ファイル化）を棄却する根拠が無い**
   - 採用: その「より単純な代替案」をそのまま採る。

9. **[contrarian, low] SOUL.md にツール利用方針（WebSearch 積極利用）が入るのは責務違反**
   - 採用: SOUL.md は語調・確認姿勢・応答密度に限定し、ツール利用方針は CLAUDE.md 側（または将来の運用設定）に残す。今回は Discord 固有のツール利用ヒントはコメントとして残しつつ、SOUL.md の役割表記からは外す。

10. **[architect, low] Python 側の missing/empty テスト不足**
    - 採用: SOUL.md 不在 / 空のときに `--append-system-prompt` が cmd に**含まれない**ことを検証するテストを追加。

11. **[migration, low] T04 の期待値が脆い**
    - 採用: SOUL.md 先頭の固定見出し（`# SOUL — hermes-lite`）を期待値にする。

## Codex design loop 2 (2026-06-24)

3 persona aggregate verdict=fail, blocking=7。前回採用の波及指摘と新規論点があり、全件採用して plan を再改訂。

### 採用した指摘（plan に反映）

1. **[architect/migration, high] SOUL.md 不在時に旧 Discord runner の人格が失われる破壊的変更**
   - 採用: Python 側に `_DEFAULT_SOUL` 定数（旧 APPEND_SYSTEM_PROMPT の中身そのまま）を残す。SOUL.md が読めない or 空のときは `_DEFAULT_SOUL` を使う。logger.warning は出す。これで deploy 漏れや一時退避時も旧挙動と同等を維持。
   - 旧挙動への完全 rollback は `git revert` か、`_DEFAULT_SOUL` のままで運用継続。

2. **[architect, high] 「そのまま移植」と「人格・口調に限定」の責務定義が矛盾**
   - 採用: SOUL.md の責務定義を「Discord runner の APPEND_SYSTEM_PROMPT を 1 ファイルに外部化（中身はそのまま）」に書き直す。人格・口調 vs ツール方針の責務分担議論は将来 Issue（Phase 2 以降）で整理する旨を Non-Goal に明記。

3. **[architect, high] SOUL.md ヘッダと注記が prompt として渡り「移植のみ」を破る**
   - 採用: SOUL.md から人間向けの注記を**完全に削除**し、CLAUDE.md 側に集約。SOUL.md には `# SOUL — hermes-lite の人格` の見出し 1 行 + 本文（旧 APPEND_SYSTEM_PROMPT そのまま）だけ。

4. **[architect, high] 「ジョブ作成判別」を SOUL.md に残すのは責務境界違反**
   - 一部採用: 既存 APPEND_SYSTEM_PROMPT にジョブ判定文言が含まれる以上、Phase 1 で**中身を変えない（移植のみ）方針**を優先し、責務再編は将来 Issue に切り出す（Non-Goal を明示）。SOUL.md の責務定義は「Discord runner プロンプトの外部ファイル化」と再定義することで境界違反論点を回避。

5. **[contrarian, high] Issue 目的「1 ファイル集約」と Phase 1 が中途半端**
   - 採用: Issue body 抜粋部分にも Phase 1 縮小を明記。「Phase 1: Discord runner のみ。Phase 2 以降: bin/run-claude.sh + 全 jobs」を明示。

6. **[contrarian, high] 空ファイル時の warning 仕様と実装が不一致**
   - 採用: `_load_soul()` で「不在 / 空 / OSError」のいずれでも warning を出す。空のときは `_DEFAULT_SOUL` にフォールバックする（warning 経由）。

7. **[architect/contrarian/migration, high+] T04 の Python one-liner で `rmdir` が NameError**
   - 採用: shell 側 `trap 'rm -rf "$SOUL_TMP"' EXIT` で後始末し、Python 側からは `rmdir` を削除。

8. **[architect, medium] HERMES_HOME がリポジトリルートを指す前提が未検証**
   - 採用: plan に既存定義 `HERMES_HOME = Path(__file__).resolve().parents[2]`（claude_runner.py:17）を引用し、systemd unit の WorkingDirectory も確認する旨を記載。

9. **[contrarian, medium] より単純な代替案を退ける根拠が無い**
   - 一部採用: 「SOUL.md 追加のみで実装変更を後続」案 vs 「Discord runner も今回変える」案を plan に明記し、後者を採る理由（人格の存在意義は読み込み経路の確立とセット）を書く。

10. **[contrarian, medium] Discord 固有文脈を SOUL.md に残す判断**
    - 採用: 4 と同じく Phase 1 では移植のみ、責務再編は Phase 2 以降と明示。

11. **[migration, medium] logger.warning が stderr に出る前提が未検証**
    - 採用: T04/T05 の主判定は `_build_cmd` の戻り値検証に変更（`--append-system-prompt` の有無）。warning 検証は補助。`logging.basicConfig(level=logging.WARNING)` を Python one-liner に明示。

12. **[migration, medium] Issue body 抜粋と Phase 1 実装対象の食い違い**
    - 採用: 5 で対応済み。

13. **[migration, medium] resume_session_id 付きの呼び出しが未検証**
    - 採用: T08 として `_build_cmd('hi', 'abc-resume')` のケースを追加。`--resume abc-resume` と `--append-system-prompt` の両方が同時に含まれることを確認。

14. **[contrarian, low] Before/After スニペットが省略記号を含む**
    - 採用: APPEND_SYSTEM_PROMPT の全文を plan に引用し、移植粒度を明確にする。

## Codex design loop 3 (2026-06-24) — max_design_loops (light=3) 到達

3 persona aggregate verdict=fail, blocking=8。max_design_loops 到達のため**裁量で passed**。

### 採用した指摘（plan に反映）

A. **[architect/contrarian/migration, high] SOUL.md 見出し `# SOUL — hermes-lite の人格` が prompt に混入し旧挙動互換を破る**
   - 採用: SOUL.md の見出しを**完全削除**。SOUL.md の中身 = 旧 APPEND_SYSTEM_PROMPT の Python 連結結果と**バイト完全一致**。

B. **[architect/contrarian, high] SOUL.md と _DEFAULT_SOUL の二重保持がドリフトの温床**
   - 一部採用: 二重保持自体は migration 観点から残すが、**T02 をドリフト検知テスト**に変更。SOUL.md 本文と `_DEFAULT_SOUL.strip()` が一致しないと CI ですぐ気付く。

C. **[architect, high] In-Scope 表で「責務再編」が in/out 両方に書かれていて破綻**
   - 採用: In-Scope 行から「責務再編」を削除し、代わりに「後方互換 alias」の行に置き換え。

D. **[migration, high] `APPEND_SYSTEM_PROMPT` 削除が既存 import を破壊し得る**
   - 採用: `APPEND_SYSTEM_PROMPT = _DEFAULT_SOUL` の互換 alias を残す。T06 を「alias 残存確認」に変更。

E. **[migration, high] `UnicodeDecodeError` を捕捉しない**
   - 採用: `except (OSError, UnicodeError)` に拡張。T05b として UTF-8 壊れファイルの境界テスト追加。

F. **[architect/contrarian, medium] CLAUDE.md 注記が Phase 2 を先取り**
   - 採用: CLAUDE.md 注記から「Phase 2 で広げる予定」を削除。事実だけ（現状の Discord runner 限定 + fallback）に修正。

### 裁量で残置した指摘（実装時の意識として残す）

- **[architect, medium] `.strip()` でバイト一致が崩れる**
  - 残置理由: 旧 APPEND_SYSTEM_PROMPT 末尾改行が無いので `.strip()` 後と一致。T02 のドリフト検知も `.strip()` 後で比較するので実害無し。
- **[contrarian, medium] テストが内部関数寄りで実経路を検証していない**
  - 残置理由: project_type=jobs で自動テストフレームが無い。手動チェックリストで `_build_cmd` の戻り値検証までで十分（subprocess.run の monkeypatch は過剰）。
- **[contrarian, low] warning 文言の grep 依存テスト**
  - 残置理由: 主判定は `--append-system-prompt` の有無、grep は補助。文言変更時はテスト側も同時に直す。
- **[migration, medium] Rollback で Python API 面（`_load_soul` 導入など）が戻らない**
  - 残置理由: 互換 alias を残すので、`APPEND_SYSTEM_PROMPT` の import 経路は壊れない。`_load_soul` の新規追加は破壊的ではない（既存呼び出しなし）。

**裁量採用の根拠**: max_design_loops=3 (light) に到達。重要な構造問題（A〜F）はすべて反映済み。残置は実装ノイズに近い細部か、テストフレーム前提の差。Codex final review で diff レビューを行うのでさらに blocking が出ればそこで対処する。
