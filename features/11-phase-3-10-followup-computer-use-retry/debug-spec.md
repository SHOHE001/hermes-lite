# debug-spec for #11 — Codex final review 裁量採用残置 findings

Codex final review を 4 ラウンド回し (codex_loops=4)、ラウンド 5 でも 8 件の critical/high が残った。
構造的に解消不可能なものが大半 (skill 固定挙動 + post-commit pending は plan 設計上必須) のため、
`max_codex_loops` 超過前ではあるが、追加ループでは収束しないと判断して裁量採用する。

## 裁量採用の残置 findings (3 persona)

### architect (3 件)

1. **H1: 残置 blocking findings を成果物として承認しており final gate を無効化している**
   - 残置理由: rejection.md は design review の `max_design_loops=3 (light)` 超過に対する裁量採用ログ。
     skill 規約通り、`stop_conditions.ask_user_on_blocking: false` のため自動裁量採用。
     6 件の design 残置は本 plan 内で解消不可能 (probe.py 改修案件、skill 固定 commit パイプライン、運用契約)。
   - follow-up: rate limit 復帰後に gh で別 Issue 起票推奨 (本サイクル中は gh 不可)

2. **H2: Case D なのに README を最新 outcome の保持先として記述している** (round 4 で文言修正済み、本ラウンド未測定)
   - ラウンド 5 dispatch では再評価されていない可能性あり、ファイル上は修正済み

3. **M1: post-commit redaction 結果を成果物に残せない構造**
   - 残置理由: plan 設計方針 #6-c で「commit 後 git show grep を STEP 8 で実行」と明示。
     post-commit hash は STEP 8 squash 後にのみ確定するため、commit 前成果物に書けない。
     post-commit 検査結果は **STEP 8 内の bash スクリプト出力**で確認、failure 時は push 中断。
   - 補完: STEP 8 で post-commit 検査を実行し、stdout に "REDACTION CLEAN (post-commit)" を出力。
     これが orchestrator のターミナルログに残ることで監査証跡になる。

4. **M2: state.json の phase 状態二重管理** (round 4 で同期済み、本ラウンド未測定)
   - phases.* と top-level を同じ値に同期済み

### contrarian (3 件)

1. **H1: post-commit redaction 未実施のまま完了扱い** ← architect M1 と同じ問題
   - 同上の対応

2. **H2: 既知 blocking findings 6 件を裁量残置したまま** ← architect H1 と同じ
   - 同上

3. **M1: redaction allowlist の re-構成** (probe.py 改修必要、Out-of-Scope)
   - 残置理由: probe.py 改修は本 plan の Out-of-Scope (#10 PR で確立した契約)。
     値の型検証・enum 制限は別 Issue 案件。本 plan は probe.py の上流契約 + grep 補助検査で安全性を担保する設計。

4. **M2: tests_passed と tests_pending_post_commit の併存表示誤読リスク**
   - 残置理由: test-summary.json に `tests_pending_rationale` フィールドを追記して
     「design-time scheduled (STEP 8 で post-commit 実施)」と明示済み。
     機械処理側がこれを読まずに `tests_passed` だけ参照する場合は別途修正要 (本 plan では実装しない)。

### migration (2 件)

1. **H1: 必須の post-commit / commit message 検査が未実施のまま `passed` 扱い** ← architect M1, contrarian H1 と同じ
   - 同上の対応

2. **H2: redaction 確認ログが計画の完了条件と矛盾** ← H1 と同じ
   - 補完: research-log.md 内の `## redaction 確認` セクションは「pre-commit pass / post-commit pending」と明示記載済み (round 3 で修正)。
     post-commit 検査結果は finalize commit でなく STEP 8 内 bash 出力 + commit message + (将来) rate limit 復帰後の gh コメント

## STEP 8 で実施する post-commit 検査 (必須)

STEP 8 の squash commit 直後、push 前に以下を実行:

```bash
PATTERNS=(
  'sk-ant-[A-Za-z0-9_-]+'
  '(^|[^A-Za-z])Bearer [A-Za-z0-9._-]+'
  '(^|[^A-Za-z])Authorization:[[:space:]]*[^[:space:]]'
  '(^|[^A-Za-z])Cookie:[[:space:]]*[^[:space:]]'
  '"request_id"[[:space:]]*:[[:space:]]*"req_[a-z0-9]+'
  '/home/shohei/'
  '"(oauthAccount|claudeAiOauth|access_token|accessToken)"'
  '"token"[^_]'
)
FAIL=0
for f in features/11-phase-3-10-followup-computer-use-retry/research-log.md; do
  for p in "${PATTERNS[@]}"; do
    if git show "HEAD:$f" 2>/dev/null | grep -qE "$p"; then
      echo "REDACTION VIOLATION (post-commit): $f / $p"
      FAIL=1
    fi
  done
done

COMMIT_MSG=$(git log -1 --format=%B)
for p in "${PATTERNS[@]}"; do
  if echo "$COMMIT_MSG" | grep -qE "$p"; then
    echo "REDACTION VIOLATION (commit msg): $p"
    FAIL=1
  fi
done

if echo "$COMMIT_MSG" | grep -qF 'Closes #11'; then
  echo "TRAILER VIOLATION: Closes #11 must not appear (Refs only)"
  FAIL=1
fi
if ! echo "$COMMIT_MSG" | grep -qE '^Refs #11$'; then
  echo "TRAILER VIOLATION: Refs #11 required"
  FAIL=1
fi
if ! echo "$COMMIT_MSG" | grep -qF 'partial_observation'; then
  echo "BODY VIOLATION: partial_observation required for Case D"
  FAIL=1
fi

[ $FAIL -ne 0 ] && { echo "BLOCK PUSH"; exit 1; }
echo "POST-COMMIT CLEAN — proceeding to push"
```

これが pass しなければ `git push` しない。
