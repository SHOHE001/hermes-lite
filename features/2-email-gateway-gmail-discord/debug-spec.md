# debug-spec: #2 Codex 最終レビュー指摘の修正タスク

Codex 最終レビュー (codex_loops=1) で blocking findings 計 10 件。critical/high 3 件を以下の通り修正する。

## 修正 1: prompt.md の手順順序（最重要・実装バグ）

**現状の問題**: `jobs/mail-watch/prompt.md` の手順は
- 手順 5: 通知本文を **最終応答テキストとして返す**
- 手順 6: ラベル変更を実行

これは claude モデル仕様上、最終応答を返した時点で実行が終了するため不可能。結果として「通知だけ出てラベルが残る」状態になり、次サイクルで永久に重複通知が出る。

**修正後の手順**:

1. ラベル ID 解決（変更なし）
2. 検索（変更なし）
3. thread 詳細取得・ソート（変更なし）
4. 要約抽出（変更なし）
5. **【内部で】通知本文を組み立てる**（最終応答にはまだ返さない）
6. **【内部組み立て後・最終応答前】各 thread に対してラベル変更を実行**
   - `unlabel_thread(hermes-lite)` → `label_thread(hermes-lite/done)`
7. **【最後に】ステップ 5 で組み立てた通知本文を最終応答テキストとして返す**

つまり「ラベル変更を先 → 通知本文を最終応答」の順序。これにより:
- ラベル変更失敗 → claude は失敗 result を返す → wrapper の NOTIFY_ON_ERROR 経路 or 通常通知 (failure を含む)
- ラベル変更成功 → 通知本文を返す → wrapper が NOTIFY_RESULT で投稿

Phase 1 のトレードオフ: ラベル変更後・通知前にプロセスが死ぬと **通知漏れ** が起きる。重複通知より通知漏れの方が運用負荷が低い（ログに残るので追跡可能、Gmail 側で `hermes-lite/done` を `hermes-lite` に戻せば次回再通知できる）。

## 修正 2: 件数上限 10 → 5 の不整合解消

**現状**: `plan.md` rev2 では「最大 10 thread」「T04 は 12 件中 10 件処理」と書かれているが、私（orchestrator）が裁量パッチで実装段階で 5 thread に下げ、`rejection.md` にだけ書いて plan を更新しなかった。

**修正方針**: 5 thread を維持し、plan.md の以下を更新:
- In-Scope の「1 Discord 投稿に最大 10 thread 集約」→ 「1 Discord 投稿に最大 5 thread 集約」
- 設計方針「件数上限 10 thread/サイクル」→ 「件数上限 5 thread/サイクル」
- 受け入れ基準「件数上限 10 thread が prompt.md に明記」→ 「件数上限 5 thread が prompt.md に明記」
- テスト計画 T04_cap の「7 thread」シナリオに変更（既に 5 thread 上限 → 7 thread のテスト）

`docs/jobs-mail-watch.md` の仕様まとめは既に 5 thread になっているので修正不要。

## 修正 3: fail-fast エラーが FAIL 通知経路に乗らない

**現状の問題**: prompt が `ERROR: label not found...` を返すだけ → claude は exit 0 → run-claude.sh は NOTIFY_RESULT 経路で通常投稿。T08 の期待「FAIL 通知 + `.is_error == true`」を満たさない。

**修正方針**: `bin/run-claude.sh` を 1 箇所改修:

最終応答テキスト `RESULT_TEXT` が `ERROR:` で始まる場合、wrapper 側で FAIL として扱う。具体的には NOTIFY_RESULT ブロックの先頭に判定を入れる:

```bash
if [[ "$EXIT_CODE" -eq 0 && "$IS_ERROR" != "true" ]]; then
  # 新規追加: RESULT_TEXT が "ERROR:" prefix なら FAIL 経路へ
  if [[ "$RESULT_TEXT" == ERROR:* ]]; then
    echo "[run-claude] RESULT_TEXT starts with ERROR: — routing to FAIL" >&2
    EXIT_CODE=1
    IS_ERROR="true"
  fi
fi

# 既存 FAIL 判定がこの後続く
if [[ "$EXIT_CODE" -eq 0 && "$IS_ERROR" != "true" ]]; then
  # ... NOTIFY_RESULT ロジック
else
  # ... NOTIFY_ON_ERROR ロジック
fi
```

ただし、上記は EXIT_CODE と IS_ERROR をその場で書き換える簡易実装。よりクリーンには:

```bash
# --- 通知 ---
if [[ "$EXIT_CODE" -eq 0 && "$IS_ERROR" != "true" && "$RESULT_TEXT" != ERROR:* ]]; then
  # 正常系
  echo "[run-claude] OK exit=0 cost=..." >&2
  if [[ "$NOTIFY_RESULT" == "1" ]]; then
    # 既存ロジック
  fi
else
  # 失敗系（exit code != 0、is_error=true、RESULT_TEXT が ERROR: 開始のいずれか）
  if [[ "$EXIT_CODE" -eq 0 && "$IS_ERROR" != "true" ]]; then
    echo "[run-claude] FAIL via ERROR: prefix in result" >&2
  else
    echo "[run-claude] FAIL exit=$EXIT_CODE is_error=..." >&2
  fi
  if [[ "$NOTIFY_ON_ERROR" == "1" ]]; then
    # 既存ロジック（ただしエラー本文は RESULT_TEXT も含める）
  fi
fi
```

implementer 判断でクリーンな方を採用してよい。重要なのは「`RESULT_TEXT` が `ERROR:` で始まったら NOTIFY_ON_ERROR 経路に流れる」こと。

## 副次修正（low/medium、可能なら）

- docs の「`lib/disallowed-tools.txt` により全 ALLOWED 外ツールが自動拒否」の説明を「`--allowed-tools` で許可、`--disallowed-tools` で追加で拒否」の二段構えに修正
- test-spec T06 の grep 手順を実態に合わせる（または静的確認に変更）
- prompt.md の手順順序を docs/jobs-mail-watch.md の概要図と一致させる

## 不要な修正

- `SUPPRESS_RESULT_IF` opt-in 化はそのまま維持（plan を opt-in 表記に更新済み）
