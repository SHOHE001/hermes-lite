あなたは hermes-lite の `approval-demo-proposer` ジョブです。承認ゲート (#3) の動作確認用に、Google Calendar への書き込みを 1 件 enqueue し、承認依頼本文を最終応答として返してください。

## 役割

LLM はこの prompt 内に書かれた Bash ブロックを **そのまま 1 度だけ** 実行し、その stdout の最終 4 行を整形して最終応答テキストとしてください。判断や言い換えは不要です。それ以外の MCP ツール / 追加 Bash 実行は呼ばないでください。

## 実行すべき Bash ブロック (1 度だけ)

```bash
set -euo pipefail

# payload を python3 で生成 (jq 非依存)
PAYLOAD=$(python3 -c "
import json
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))
# 翌日 14:00-15:00 JST のデモ予定
tomorrow = (datetime.now(JST) + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
end = tomorrow + timedelta(hours=1)

payload = {
    'summary': 'approval demo',
    'start': tomorrow.isoformat(),
    'end': end.isoformat(),
    'timeZone': 'Asia/Tokyo',
    'description': 'hermes-lite 承認ゲート (#3) の動作確認用デモ予定',
}
print(json.dumps(payload, ensure_ascii=False))
")

# enqueue (stdin に payload JSON、stdout に 8 hex id)
AID=$(printf '%s' "$PAYLOAD" | python3 "$HERMES_HOME/lib/approvals.py" enqueue \
  --proposer approval-demo-proposer \
  --executor calendar-create-executor \
  --action calendar.create \
  --summary "approval demo (翌日 14:00 JST)")

# 承認依頼本文を組み立て
SUMMARY=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['summary'])" "$PAYLOAD")
START=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['start'])" "$PAYLOAD")
END=$(python3 -c "import json,sys; print(json.loads(sys.argv[1])['end'])" "$PAYLOAD")

cat <<NOTIFY
🔐 承認依頼 #${AID}
- action: calendar.create
- summary: ${SUMMARY}
- start: ${START}
- end:   ${END}
- timeZone: Asia/Tokyo

承認するなら Discord で:  approval approve ${AID}
却下するなら Discord で:  approval reject  ${AID}

(TTL 24h。期限切れ後は再起票が必要です)
NOTIFY
```

## 最終応答テキスト

上記 Bash ブロックの stdout (`🔐 承認依頼 #...` から始まる本文) を **そのまま** 最終応答テキストとして返してください。`bin/run-claude.sh` のラッパーがこれを Discord webhook に投稿します。前置き・後置きは付けないでください。

エラーが起きた場合は `ERROR: ...` で始まる 1 行を返してください (ラッパーが FAIL 経路として扱います)。
