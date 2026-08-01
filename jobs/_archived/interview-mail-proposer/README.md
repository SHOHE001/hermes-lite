# interview-mail-proposer（廃止・2026-08-01）

**このジョブはもう動いていない。動かす予定もない。** 中身を残してあるのは、承認フロー
（proposer → Discord 承認 → executor）を実際に組んだ唯一の実例だからで、似たジョブを
作るときの参考にする以外の用途はない。

## 何をするジョブだったか

Gmail から「面談・面接の日程確定通知」らしきメールを見つけて、Google Calendar への
予定作成を **承認依頼として Discord に起票する** ジョブ。

```
6 時間おき
  → 直近 1 日の受信を広めに検索（スカウトの送信元は除外）
  → 件名 + snippet で「日程確定らしきもの」に絞る
  → 本文から未来日時と件名を取り出す
  → lib/approvals.py enqueue で Calendar.create の承認依頼を起票
  → Discord に「承認しますか？」が出る
  → ユーザーが承認したときだけ lib/approvals_executor.py が Calendar に書き込む
```

**ジョブ自身はカレンダーに書き込まない**。`job.env` の `ALLOWED_TOOLS` に Calendar 系を
入れていないのがその担保で、書き込み権限は承認後に executor が 1 回限り解禁する。
この二段構えの設計自体は `docs/discord-approval.md` に残っており、承認フローの仕組みは
今も生きている（デモは `jobs/approval-demo-proposer/`）。

## 稼働期間と実績

| 項目 | 値 |
|---|---|
| 稼働期間 | 2026-06-26 〜 2026-07-27（コミット `2b75039` で追加） |
| 実行回数 | 193 回 |
| 承認依頼の起票 | **0 件**（`state.json` の `processed_thread_ids` も空のまま） |
| 「曖昧」として保留 | 4 回（会社説明会の案内など、確定通知と紛らわしいもの） |
| 累計コスト | 約 65 USD 相当（Claude Max の OAuth 枠なので実課金はなし） |

つまり **1 件もカレンダーに入れないまま役目を終えた**。面接の日程確定メールが実際に
届く前に就職活動が終わったため。

## なぜ止めたか

内定が出て就職活動が終わり、面接そのものが無くなったため。2026-07-27 の実行を最後に
systemd timer を無効化し、2026-08-01 にユーザー判断で正式に廃止してここへ移した。

同じ理由で `var/mail-watch/rules.md` にも「就職・転職活動関連のメールは通知しない」
という学習ルールが入っている（内定先からの連絡と入社手続きだけは例外で通知する）。

## 稼働中に分かっていた問題

判定が 0 件だったとき、prompt の指示に反して「17 件確認しましたが該当なし」という
報告文を書いたうえで末尾に `[NOOP]` を置くことが多く、`SUPPRESS_RESULT_IF` の完全一致
判定をすり抜けて Discord に無駄な通知が飛んでいた（193 回中 106 回）。
この穴は 2026-08-01 に `bin/run-claude.sh` の抑止判定を末尾一致へ広げて塞いである。
再開する場合、その分は静かになる。

## 再開したくなったら

1. `jobs/_archived/interview-mail-proposer/` を `jobs/` 直下へ戻す
2. `~/.config/systemd/user/claude-agent@interview-mail-proposer.timer.d/schedule.conf` を
   作り直す（`OnCalendar=*-*-* 00,06,12,18:00:00` で動かしていた。廃止時に削除済み）
3. `systemctl --user daemon-reload && systemctl --user enable --now claude-agent@interview-mail-proposer.timer`
4. `state.json` を `{"processed_thread_ids": []}` に戻す

過去の実行ログは `logs/interview-mail-proposer/`（git 管理外）にそのまま残してある。
