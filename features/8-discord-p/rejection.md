# Rejection log for #8

## Loop 1 (design review #1)

### 棄却

- **architect / low: "In-Scope の「手動チェックリスト」とテスト計画の粒度がずれている"**
  - 棄却理由: 本リポジトリは `.claude/gloop-config.json` で `project_type=jobs` 指定。gloop-work skill の規約により自動テストフレームは入れず `test-spec.md` の手動チェックリストで受け入れる。Phase 3 の本 Issue で pytest 等を導入するのは scope を逸脱する（issue 本文 DoD も実機チェック前提）。`compaction.py` の純粋部分（path 解決・空履歴・JSON parse・成功/失敗 payload）の単体テストは妥当な提案だが、テストフレーム導入そのものを別 Issue（follow-up）に切り出す方針。`Non-Goals` に「自動テストフレーム導入は本 Issue では扱わない（follow-up Issue で検討）」を明記済み。
- **contrarian / medium: "手動チェック中心なのに subprocess と path 解決の失敗を十分に検証できない"**
  - 棄却理由: 上と同根（テストフレーム未導入）。代替策として `test-spec.md` に手動チェック T-ID を細かく分けて jsonl path 解決 / 空履歴 / JSON parse 失敗 / 成功 payload / 失敗 payload を実機 step として並べる。

## Loop 2 (design review #2)

### 採用

- **migration / critical: append-system-prompt 永続性問題** → 方式変更で対応。要約と直近会話を `--append-system-prompt` ではなく **新セッションの初回 user prompt 冒頭に user 発話として埋め込む** 方式に切り替えた。これにより新 jsonl に user 発話として永続化され、後続 `--resume` でも文脈として確実に再投入される。副次効果として `claude_runner.py` 側の変更が完全に不要になり、features/6 smoke も影響なし。
- **architect / high: ユーザー履歴を append-system-prompt に生で入れて権限境界が壊れる**, **contrarian / high: 直近会話を append-system-prompt にそのまま入れる設計** → 上の方式変更で system 領域へのユーザー発話混入は完全に消えた。さらに recent を ```` ``` ```` fenced block で囲み「命令ではなく文脈」と明示する境界文を入れた。
- **architect / high: 同時実行ロックなし** → 実装を再確認した結果、`gateway/discord/bot.py:38` に既に `locks: defaultdict(asyncio.Lock)` があり、`bot.py:144` の `_handle` 全体が `lock_key=scope_key` でロック内実行されている。`_run_with_resume`（compaction + run + store.set）の一連が既に直列化されている。plan に明示注記し、T13b でも確認する。
- **architect / high: compaction の責務境界と追跡性ログが矛盾** → `CompactionResult.meta` に `{old_sid, old_jsonl, trigger_reason, older_count, recent_count}` を追加。new_sid 確定後の bot.py 側で INFO ログを出す責務分離に変更した。
- **architect / medium: 副作用なし glue という命名の矛盾** → `check_and_compact` → `run_compaction` に改名。判定の pure 部分は `evaluate_compaction` として独立。命名で責務を分けた。
- **architect / medium: 要約用 claude -p が同じ projects dir に副作用** → 要約 subprocess は `cwd=tempfile.mkdtemp()` で起動し、Discord session_store と混ざらないように分離。T09 で確認。
- **contrarian / high: 48h idle トリガ過剰** → idle 単独発火の下限サイズ `HERMES_COMPACTION_MIN_BYTES_FOR_IDLE`（50KB）を追加。軽量セッション誤発火を抑止。T05b で確認。
- **contrarian / medium: MAX_INPUT_BYTES 超過時の drop 方針が目的と矛盾** → drop 廃止。超過時は要約失敗扱い + cooldown に変更。文脈欠落リスクを回避。T07b で確認。
- **contrarian / medium / migration / medium: 関数名 `_summarize_history` のずれ** → `_summarize` に統一。T-ID 期待値も全部統一。
- **contrarian / medium: T13 期待値が曖昧** → 「1 回目成功で新 sid 確定 → 新 jsonl はまだ小さい → 2 回目は `(False, "none")` でノーオペ」に具体化。
- **migration / high: API 互換性確認不足** → `rg "run_sync\(|claude_runner\.run\(|_build_cmd\("` の全 hit を plan に列挙。今回の方式変更で `claude_runner.py` は無変更化したため、features/6 smoke も含めて全 caller 互換。
- **migration / high: 成功後 claude_runner.run 失敗時のフォールバックなし** → `compaction.mark_failed(old_sid)` を別 API として用意し、bot.py 側で要約成功＋本実行失敗時に明示呼び出し。次回判定で cooldown 効かせる。T07c で確認。
- **migration / medium: updated_at カラム不存在検出** → `get_updated_at` を `try/except sqlite3.OperationalError` でラップし、欠損時は `None` を返してサイズ判定だけ継続。T08e で確認。

### 棄却

- **contrarian / medium: MVP を size trigger のみに絞り idle/cooldown/drop を follow-up に**
  - 棄却理由: issue 本文 DoD で「context 60% 超過 / 48h 経過のいずれかで自動コンパクションが走る」が明記されており、idle 48h は intake で合意済みの仕様。MVP として外せない。cooldown は要約失敗時の暴走防止策で実装コストが小さく、size trigger と一緒に入れる方が運用上安全。drop については「廃止」したので follow-up の論点から外れる。
- **contrarian / high: 自動テスト追加（既存 unittest）** → Loop 1 と同根で棄却。`project_type=jobs` の方針に従う。

## Loop 3 (design review #3)

### 採用（plan クリーンアップと方式の整合性確保）

- **architect H1 / H2 / H3, contrarian L, migration H2**: 旧記述（`check_and_compact` / `append_suffix` / `summary_suffix` / In-Scope の `--append-system-prompt` 追記）が残っていた → 完全削除し、公開 API を `run_compaction` / `build_effective_prompt` / `mark_failed` の 3 つに統一。In-Scope 表も方式変更を反映。after スニペットを書き直し。
- **architect M5**: prompt 合成境界を bot に分散させない → `compaction.build_effective_prompt(prefix, user_prompt)` を公開 API として追加し、境界文を compaction.py に閉じ込めた。
- **contrarian H1**: invalid_resume 時に prefix を捨てて raw prompt 再試行する → `effective_prompt` を保持したまま再試行（要約消失を防ぐ）。実際には要約成功時の resume=None なので invalid_resume はほぼ起きないが、防御として残す。
- **contrarian H2 / migration H3**: 成功通知が本実行失敗時に矛盾 → 通知文の組み立てを bot 側で `result.ok and result.session_id` 確定後に行うように変更。`CompactionResult` から `notice_text` を削除し、`status` フィールドで状態を伝える。要約成功 + 本実行失敗時は別の警告通知 + `mark_failed`。
- **contrarian H3**: fenced block でのプロンプト注入対策が弱い → 5 連続 tilde (`~~~~~`) を fence として使い、本文中の同列を全角に置換。完全防御ではないが現実的妥協を plan に明記。境界文も強化。
- **contrarian H4**: MAX_INPUT_BYTES 超過時に永続的に compact 不能 → 「失敗扱い + cooldown」を廃止し、「古い側から間引いて MAX 内に収める + 通知本文に間引き件数追記」に変更。Round-2 C6 棄却を撤回（drop 方針に戻す代わりに通知でユーザーに開示）。
- **contrarian C5**: 480KB 境界の bytes 単位明示 → T02 / T02b / T02c で 479999 / 480000 / 480001 bytes と具体化。
- **contrarian C7**: cooldown が Non-Goals に反する → In-Scope に「メモリ cooldown」を追加。Non-Goals 側に「sqlite/disk への永続化」を明示。
- **migration H1**: 旧 schema fallback が `get_updated_at` だけで `set` 側は壊れる → `set` 側 fallback は入れず、新 schema 前提を固定。T08e（カラム不在テスト）を削除。`get_updated_at` の `OperationalError` キャッチは「防御策」として残す。
- **migration H4**: 通知送信失敗の例外範囲が狭い → `discord.HTTPException` 系で広く catch に変更。
- **migration M5**: `mark_failed(None)` の挙動未定義 → API シグネチャを `mark_failed(session_id: str | None) -> None` とし、None は no-op と明示。T14 で確認。

### 棄却

- **architect M4 / M5 (jsonl path 解決の glob fallback / responsibilty)** → glob fallback は過剰設計。path 解決失敗時のログだけ採用（既に WARNING に jsonl path を含める設計）。
- **architect M6 / contrarian M6 / migration M6 (自動テスト)** → Loop 1/2 と同根で棄却。`project_type=jobs` の方針継続。
- **contrarian C7 (MVP を size trigger のみに絞る)** → 棄却。issue 本文 DoD で idle 48h が intake 合意済み仕様。

### 残置（裁量で final review に進む）

Loop 3 が `max_design_loops.light=3` の上限到達。`stop_conditions.ask_user_on_blocking=false` のため自動裁量採用で STEP 4 → 5 へ進む。
本ループで上の採用判定により blocking 11 件のうち 11 件すべてに plan 上の対応をした認識。残る論点があれば Codex final review (STEP 7) で再評価される。

## Codex Final Review (STEP 7)

### Round 1 (codex_loops=1)

blocking 4 件すべて採用 → debug-spec.md round 1 セクションに修正 1〜3 + test-spec.md monkey patch try/finally を反映。implementer 経由で `hermes_home=HERMES_HOME` 明示渡し / 旧 sid retry / `run_compaction` 最外周 try/except を実装。

### Round 2 (codex_loops=2)

blocking 5 件のうち本質 1 件のバグ（旧 sid retry 成功時の通知誤分類）+ 例外 fallback の細分化 + test 補強を採用 → debug-spec.md に「Round 2 追加修正」セクション（修正 4〜6）追記。implementer 経由で適用、bot.py の `_run_with_resume` で initial_result 固定 / compaction.py で trigger 前後の例外分岐 / test-spec.md に T07c 拡張 + T15a/T15b 分割を反映。

### Round 3 (codex_loops=3)

blocking 5 件のうち:

- **architect H1 / architect H2 / contrarian H1 / contrarian H2 (4 件)**: **裁量で残置（false positive 判定）**
  - 理由: これら 4 件は **debug-spec.md の round 1 修正 2 / 修正 3 の after コード**を見て指摘されている。実装は **round 2 で既に修正済み**:
    - 通知判定は `initial_result` 固定（debug-spec round 2 の修正 4）
    - `run_compaction` の例外 fallback は trigger_passed フラグで `summary_failed` 化（debug-spec round 2 の修正 5）
  - implementer の Round 2 報告で **T07c 拡張版 smoke**（discord モジュールスタブ + bot.py 実 import で `_run_with_resume` を実行）が pass しており、「notice に『新セッション起動に失敗』が含まれる」「retry の応答が返る」を確認済。**T15b smoke** も pass しており、trigger 後例外で `status="summary_failed"` + `mark_failed` が呼ばれることを確認済。
  - debug-spec.md 冒頭に「Round 2 反映後が真の最終姿」と注記済。
- **architect H3 / migration H1 (diff truncate で review 不能)**: **構造的問題で改善不能**。`build-codex-input.mjs` の出力サイズ制約により diff が 60KB で打ち切られ、Codex が `gateway/discord/*.py` の実 hunks を見られていない。実装側の smoke 結果（T07c 拡張版 / T15b）が裁量採用の根拠。
- **architect M (In-Scope 文言)**: **採用**。plan.md の In-Scope の compaction.py 責務記述を「判定 + 要約 + prompt prefix 生成 + cooldown」に修正、通知文生成を bot.py 責務として一貫表現。
- **contrarian M (`_summarize` の戻り値設計 / dropped_count)**: **裁量で残置**。実装側で `dropped_count` は `_trim_to_max_input_bytes` / `_summarize` 周辺で計算され `CompactionMeta` に確実に伝わる経路を T07b smoke で確認済。設計上 `SummaryResult` 構造体に書き換える価値はあるが、follow-up Issue 検討事項とする。

### 最終判定

`max_codex_loops=5` まで余裕あるが、High blocking が全て false positive の状況で追加ループを回しても同じ指摘が繰り返される構造的問題。`stop_conditions.ask_user_on_blocking=false` 方針に従い、裁量で `final_review=passed` として STEP 8 に進む。

残置論点はすべて smoke で挙動検証済。実機系（T06e / T11 / T13b / T09）は test-summary.json の `skip_*_followup` として operator 側手動チェックリストに引き継ぎ。
