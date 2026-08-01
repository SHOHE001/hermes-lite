# jobs/mail-watch セットアップ

直近 12 時間に届いたメールを claude 自身が読んで重要度を判定し、**通知は原則 1 日 1 回のまとめに集約する**ジョブ。いますぐ知る必要があるものだけ、検知したその場で割り込み通知する。Issue #2 (Phase 1) で「ユーザーが `hermes-lite` ラベルを貼ったメールを通知する」方式として実装し、2026-07-28 に自動判定方式へ、2026-08-01 に「まとめ 1 回 + 至急のみ即時」の 2 ジョブ構成へ書き換えた（経緯は末尾「設計の変遷」）。

## 概要

検知の `mail-watch` と、まとめ投稿の `mail-digest` の 2 ジョブに分かれる。

```
systemd timer (2h)
  → bin/run-claude.sh mail-watch
      → claude -p prompt.md
          → Read var/mail-watch/notified.json（処理済み thread ID。無ければ空扱い）
          → Read var/mail-watch/pending.json（まとめ待ちの保留キュー。無ければ空扱い）
          → Read var/mail-watch/rules.md（学習した追加ルール。無ければ無視して続行）
          → search_threads "newer_than:12h in:inbox -in:trash -in:spam -category:promotions -category:social"
              pageSize=50 / view=THREAD_VIEW_MINIMAL（差出人・件名・snippet）
          → 0 件なら最終応答 "[NOOP]" で終了
          → 【一次スクリーニング】処理済み・TRASH/SPAM を機械的に捨て、
              残りを件名 + snippet だけで重要度判定（本文は取らない）
          → 該当 0 件なら "[NOOP]" で終了
          → 【二次】取り上げ対象（最大 5 件）だけ get_thread で本文を取り 1 行要約
          → 【振り分け】各件を「至急（即時通知）」と「保留（翌朝まとめ）」に分ける。迷ったら保留
          → Write で pending.json に保留分を追記（7 日より古いものは削除）
          → Write で notified.json を更新（即時・保留の両方を追記、3 日より古いものは削除）
          → 至急が 1 件以上なら通知本文を、0 件なら "[NOOP]" を最終応答として返す
      → ラッパーが NOTIFY_RESULT=1 で result を mail-watch 専用チャンネルへ投稿
          （job.env が DISCORD_WEBHOOK_URL を MAIL_WATCH_DISCORD_WEBHOOK_URL に差し替える）
      → SUPPRESS_RESULT_IF="[NOOP]" により至急 0 件時の Discord 投稿はスキップ
      → 異常終了時は NOTIFY_ON_ERROR=1 経路で FAIL 通知が出る

systemd timer (毎日 08:30)
  → bin/run-claude.sh mail-digest
      → claude -p prompt.md（ツールは Read / Write のみ。メールは読まない）
          → Read var/mail-watch/pending.json
          → 0 件なら "[NOOP]" で終了（「今日は 0 件」通知は出さない）
          → 各エントリの line をそのまま古い順に並べて本文を組み立てる
          → Write で pending.json を {"pending": []} に空化
          → 通知本文を最終応答として返す
      → mail-watch と同じ専用チャンネルへ 1 通投稿
```

`get_thread` は取り上げる数件にしか呼ばないので、候補が何十件あっても本文取得のコストは取り上げ件数に比例する。`mail-digest` は Gmail を触らず、`mail-watch` が作った完成済みの 1 行を並べ直すだけ。

### なぜ 2 ジョブに分けたか

即時通知を成立させるには検知間隔を短くする必要があり（6h では「すぐ」にならない）、一方で通知回数は 1 日 1 回に抑えたい。この 2 つは 1 ジョブでは両立しない。`mail-watch` を 2h ごとに走らせて検知を細かくし、投稿だけを `mail-digest` に切り出して 1 日 1 回に固定した。「いまが朝 8 時半かどうか」を prompt に判定させるより、systemd timer の別インスタンスに任せるほうが確実。

## 事前セットアップ

### 1. 状態ファイルの初期化

```bash
mkdir -p ~/hermes-lite/var/mail-watch
printf '{\n  "notified": []\n}\n' > ~/hermes-lite/var/mail-watch/notified.json
printf '{\n  "pending": []\n}\n' > ~/hermes-lite/var/mail-watch/pending.json
```

`notified.json` は処理済み thread ID（即時通知した分と保留に積んだ分の両方）、`pending.json` は翌朝のまとめ待ちキュー。prompt 側は「ファイルが無ければ空リストとして続行」と指示してあるので初回でも動くが、明示的に置いておくほうが確実。`var/*` は `.gitignore` 済みで、git には乗らないランタイムデータ。

**Gmail 側の設定（ラベル作成・フィルタ）は一切不要**。重要かどうかの判定はジョブ側で行い、通知済みの記録もローカルに持つ。

### 2. `.env` に Discord の設定を書く

`~/hermes-lite/.env` に次の 3 行を追加する:

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...          # 全ジョブ共通のフォールバック
MAIL_WATCH_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...  # mail-watch 専用チャンネル
MAIL_WATCH_CHANNEL_IDS=1234567890                                  # 同じチャンネルの ID
```

`MAIL_WATCH_DISCORD_WEBHOOK_URL` は `jobs/mail-watch/job.env` が `DISCORD_WEBHOOK_URL` に再代入する。`bin/run-claude.sh` は `.env`(59 行) → `job.env`(85 行) の順に source し、`notify_discord` は投稿時に変数を評価するので、wrapper 本体を触らずに投稿先を切り替えられる。**未設定なら共通 webhook にフォールバック**し、両方空なら `lib/notify.sh` が WARN を出して投稿だけスキップする（ジョブは落ちない）。

`MAIL_WATCH_CHANNEL_IDS` は Discord bot 側が使う。このチャンネルでの発言だけが `gateway/discord/mail_rules_handler.py` に流れ、通知ルールを編集できる（→ 下の「フィードバックでルールを直す」）。

`.env` は `set -a` **無しで** source されるので、値は claude 子プロセスの環境変数としては渡らない（秘密の継承カット。`docs/wrapper-api.md` の「秘密キーの子プロセス継承カット」を参照）。新しい秘密キーを増やしたら `gateway/discord/claude_runner.py` と `lib/approvals_executor.py` の `_SECRET_ENV_KEYS` にも追加すること。

### 3. 重要度の基準を自分に合わせる

**このジョブで一番調整が要るのは `jobs/mail-watch/prompt.md` の「重要度の基準」節**。通知する条件（期限・金銭・セキュリティ・個人宛の返信要求・公的機関・予約や配送）と、通知しない条件（メルマガ・スカウト・SNS 通知・ニュースレター・GitHub 通知・行動不要の一斉配信）を列挙してある。

運用しながら、通知が来て嬉しくなかったものを「通知しない」側に、見落として困ったものを「通知する」側に追記していく。判定は `MODEL="sonnet"` が行う。

ただし日々の微調整は prompt.md を直接いじらず、次の「フィードバックでルールを直す」を使う。prompt.md は**骨格**（自動では書き換わらない部分）として残す。

### 4. 何を「至急」とみなすかを決める

`prompt.md` の「即時通知の基準」節が、重要と判定したメールを **その場で割り込み通知するか / 翌朝のまとめに回すか** を決める。判断の軸は重要度の高さではなく**時間的な猶予**で、「明日の朝知って間に合うか」に間に合わないものだけが即時になる（不正利用の疑い、失効の早い認証コード、24 時間以内の期限、当日・翌日の予定変更、当日中の返信要求など）。それ以外はすべてまとめ行き、迷ったらまとめ行き。

即時通知が多すぎる／少なすぎると感じたらこの節を調整する。`rules.md`（フィードバック学習分）は**通知するかどうか**にしか効かず、即時かまとめかの振り分けには関与しない。

## フィードバックでルールを直す

mail-watch 専用チャンネルに「これは実は重要じゃない」と書くと、その場で判定ルールが更新される。

```
[mail-digest] 重要メール 2 件
- `1a2b3c4d` paiza | 【スカウト】… | …
- `9f0e1d2c` 三井住友カード | ご利用代金明細 | …
```
↑ の 1 通目に **Discord の返信** をして「これは要らない」と書くと:
```
✅ 通知しない（除外を強める）に追加: paiza の「【スカウト】」求人スカウトメール
（反映は次回 mail-watch 実行から / 全 7 エントリ）
```

- 返信でなくても、通知本文の**短縮 ID**（`` `1a2b3c4d` ``＝`threadId` の先頭 8 文字）で指せる。ID は `notified.json` が保持する 3 日間だけ引ける
- 対象が特定できないフィードバック（「なんか最近うるさい」）は編集されず `❓` で聞き返される
- `rules`（または `ルール`）と打つと現在のルール全文、`undo`（または `戻して`）で直前の変更を取り消す

学習分は **`var/mail-watch/rules.md`**（git 管理外）に溜まり、`prompt.md` の「重要度の基準」に**上乗せ**して適用される。競合したら追加ルールが優先されるが、次の 4 つだけは追加ルールでも打ち消せない（`prompt.md` 側の安全ネット）:

- 決済失敗・不正利用の検知・セキュリティ警告
- 公的機関・金融機関からの個別通知
- 期限が 72 時間以内に迫っているもの
- 人間が個人宛に書いた、返信を求めているメール

安定して効いているルールは、人間が `prompt.md` の骨格側へ手で昇格させてコミットするとよい（`rules.md` は git に乗らないため）。

### なぜ `var/` で git 管理外なのか

gloop が毎サイクル末に `git stash push -u -- . :(exclude)features/` を無条件で実行するため（`~/.claude/skills/gloop/scripts/loop-post-cycle.mjs`）、`jobs/` 配下に置くと bot が書いた学習ルールが次のサイクルで stash に吸われて黙って消える。`stash -u` は untracked を含むが **ignored は含まない**ので、`.gitignore` 済みの `var/*` なら `git status` にすら出ず、gloop の dirty 判定にも stash にも干渉しない（`notified.json` と同じ扱い）。

git 履歴が残らない代わりに、`var/mail-watch/rules.bak/<ts>.md`（直近 20 世代）と `var/mail-watch/rules-audit.jsonl`（誰がいつ何と言ってどう変わったか）で追跡できる。

### 壊れないようにしている仕掛け

ルール調整の claude には **`Write` を渡さず `Edit` だけ**を許可し、MCP も空 config + `--strict-mcp-config` で落としている。`Edit` は `old_string` の完全一致を要求するのでファイルを一撃で全消しできない。加えて Python 側が実行前にバックアップを取り、実行後に「ファイルが存在しサイズ > 0 / 3 つの `<!-- APPEND:* -->` アンカーが各 1 個 / 200 バイト以上縮んでいない」を機械的に検証し、外れたらバックアップから自動復元する。LLM の善意に依存する箇所を残さないための構成。

なお `--allowed-tools` だけでは制限にならない（2026-07-29 実測: `--allowed-tools Read Edit` を渡しても `Write` も `Bash` も実行できた）。逆に `--disallowed-tools '*'` は allowed より優先されて `Read` すら拒否される。**両方を明示列挙する**必要がある。

## systemd timer 登録

検知（2 時間おき）とまとめ投稿（毎日 08:30）で 2 つの timer を登録する。

```bash
mkdir -p ~/.config/systemd/user/claude-agent@mail-watch.timer.d
cat > ~/.config/systemd/user/claude-agent@mail-watch.timer.d/schedule.conf <<'EOF'
[Timer]
OnCalendar=*-*-* 00/2:00:00
EOF

mkdir -p ~/.config/systemd/user/claude-agent@mail-digest.timer.d
cat > ~/.config/systemd/user/claude-agent@mail-digest.timer.d/schedule.conf <<'EOF'
[Timer]
OnCalendar=*-*-* 08:30:00
EOF

systemctl --user daemon-reload
systemctl --user enable --now claude-agent@mail-watch.timer
systemctl --user enable --now claude-agent@mail-digest.timer
```

`mail-digest` を 08:30 にしているのは、08:00 の `jobwatch-review` と重ならないようにするため。

**検索窓 12h に対して実行間隔が 2h** なので、各メールは通常 6 回評価される。一度扱った thread は `notified.json` で除外されるので重複はせず、ジョブが数回失敗しても取りこぼさない。実行間隔を延ばす場合、窓（prompt.md の `newer_than:12h`）が間隔の 2 倍以上あるよう合わせること。

タイマー状態の確認:

```bash
systemctl --user list-timers --all | grep -E 'mail-watch|mail-digest'
systemctl --user status claude-agent@mail-watch.timer
```

## 手動試走

定期実行に組み込む前、あるいは prompt を変更した直後の試走:

```bash
~/hermes-lite/bin/run-claude.sh mail-watch
~/hermes-lite/bin/run-claude.sh mail-digest
```

実行後の確認ポイント:

- `~/hermes-lite/logs/mail-watch/<timestamp>.json` の `.result` に至急通知本文または `[NOOP]` または `ERROR: ...` が入っている
- `~/hermes-lite/logs/mail-watch/<timestamp>.stderr` に `[run-claude]` ログが残る
  - 至急 0 件時は `result matched SUPPRESS_RESULT_IF — skipping Discord post` が出る
- `.is_error == false` かつ exit code 0 が正常終了
- `var/mail-watch/pending.json` に保留分が積まれ、`var/mail-watch/notified.json` に即時・保留の両方が追記されている
- `mail-digest` を走らせると pending の中身が 1 通で投稿され、`pending.json` が `{"pending": []}` に戻る

`mail-digest` だけを試したいときは、`pending.json` に手でエントリを 1 件書いてから走らせるのが早い。同じメールでもう一度 `mail-watch` を試したいときは `notified.json` の該当エントリを消す。

## 仕様まとめ

| 項目 | 値 |
|---|---|
| 検索クエリ | `newer_than:12h in:inbox -in:trash -in:spam -category:promotions -category:social` |
| 検索取得上限 | `pageSize=50`、**ページングしない**（50 件到達時は通知本文に注記） |
| 粒度 | thread |
| 処理済みの記録 | `var/mail-watch/notified.json`（`threadId` + `at`。即時通知分と保留分の両方。3 日より古いエントリは毎回捨てる） |
| 保留キュー | `var/mail-watch/pending.json`（`threadId` + 完成済みの `line` + `at`。7 日より古いエントリは捨てる） |
| まとめ投稿の退避 | `var/mail-watch/pending-sent.json`（`mail-digest` が空化する直前の 1 世代。投稿が落ちた日はこれを `pending.json` に戻す） |
| 一次スクリーニング | 処理済み・TRASH/SPAM を機械的に除外 → 件名 + snippet のみで判定（`get_thread` は呼ばない） |
| 二次（本文取得） | 取り上げ対象のみ `get_thread` |
| 1 サイクル取り上げ上限 | **5 件**（重要度の高い順、同程度なら古い順） |
| 即時 / 保留の振り分け | `prompt.md` の「即時通知の基準」。軸は重要度ではなく**時間的猶予**、迷ったら保留 |
| 即時通知フォーマット | `至急 N 件（保留 P 件は翌朝まとめ）\n- ` + 短縮 ID + ` 差出人 \| 件名 \| 1 行要約` × N（`[mail-watch] ` はラッパーが前置する） |
| まとめ通知フォーマット | `重要メール N 件\n` + 保留した行をそのまま古い順に（`[mail-digest] ` はラッパーが前置する） |
| まとめの表示上限 | **20 件**（超過分もキューからは消し、翌日に持ち越さない） |
| 判定ルール | `prompt.md` の「重要度の基準」（骨格）＋ `var/mail-watch/rules.md`（学習分・上乗せ）。安全ネット 4 項目は上書き不可 |
| 通知先 | `MAIL_WATCH_DISCORD_WEBHOOK_URL`（未設定なら `DISCORD_WEBHOOK_URL`）。2 ジョブとも同じ |
| 0 件時 | claude が `[NOOP]` を返し、ラッパーが `SUPPRESS_RESULT_IF` で投稿スキップ（`mail-watch` は至急 0 件、`mail-digest` は保留 0 件） |
| 記録の更新 | 通知本文を返す**前**に完了させる。`pending.json` → `notified.json` の順（前者が失敗したら後者も更新しない） |
| Calendar / Notion 書き込み | 禁止（`lib/disallowed-tools.txt` により自動拒否） |
| 失敗時 | `NOTIFY_ON_ERROR=1` で Discord に FAIL 通知 |
| スケジュール | `mail-watch` = `*-*-* 00/2:00:00`（2h ごと） / `mail-digest` = `*-*-* 08:30:00`（1 日 1 回） |

`jobs/mail-watch/job.env` の `ALLOWED_TOOLS` は `search_threads` / `get_thread` / `Read` / `Write` の 4 つ。`Read` は `notified.json` / `pending.json` / `rules.md`、`Write` は `notified.json` / `pending.json` に限定してあるが、これはツール単位では絞れないため prompt の指示に依存する。`jobs/mail-digest/job.env` は `Read` / `Write` のみで、Gmail ツールを一切持たない。これに加えて `lib/disallowed-tools.txt` で Calendar 系・Notion 書き込み・Gmail 下書き作成・破壊的 Bash を wrapper レベルで拒否している。

### 実測（2026-07-28）

- `newer_than:12h in:inbox -category:promotions -category:social` の候補は **8 thread**。内訳はスカウト系（paiza / マイナビ）、GitHub 通知、Google ニュース、Quora、メルカリ、Moneytree など。判定の結果、**通知 1 件・除外 7 件**（通知されたのは Moneytree の大口取引検知）。`pageSize=50` は当面十分。
- `in:inbox` を指定しても **全 message が `TRASH` の thread が返る**。クエリに `-in:trash -in:spam` を足したうえで、一次スクリーニングでも `labelIds` を見て捨てる二重の防御にしている。
- 1 回あたりのコストは **0.38〜0.53 USD / 5〜7 ターン**。`MAX_BUDGET_USD="1.00"` に対して余裕は大きくないので、受信が多い日に上限へ当たるようなら引き上げる。
- 2026-08-01 に実行間隔を 6h → 2h にしたので、`mail-watch` は 1 日 4 回から 12 回に増えた（`mail-digest` は 1 日 1 回・0.16〜0.18 USD で、Gmail を叩かないぶん軽い）。Claude Max の OAuth 枠なので金銭的な請求は発生しないが、消費するトークン量は約 3 倍になる。他のジョブが枠を食って困るようなら、まずここの間隔を 3h / 4h に戻す。

## 設計判断

### なぜ「時間窓 + ローカル記録」なのか

全メールを読んで判定する方式では、**通知しなかったメールの扱い**が問題になる。処理済みの印を全件に付けると管理対象が受信トレイ全体に膨れ、付けないと毎サイクル同じメールを再評価してコストが膨らむ。

そこで状態記録を 2 つに分けた:

- **時間窓（`newer_than:12h`）** が評価対象の範囲を決める。通知しなかったメールは窓から出れば自然に対象外になり、記録は不要
- **`notified.json`** には通知したものだけを残し、重複通知を防ぐ

記録に残るのは通知した数件だけなので、ファイルは常に小さい（3 日より古いエントリは毎回捨てる）。ジョブが数回落ちても、次に走ったときの直近 12h から再開するだけで復帰する。

### なぜ Gmail のラベルではなくローカルファイルなのか

当初は `helmeslite-done` ラベルを通知済みマーカーにする設計だったが、**Gmail コネクタが読み取り分のスコープしか持っておらず**、`label_thread` / `create_label` / `update_label` がいずれも `Request had insufficient authentication scopes.` で拒否された（2026-07-28、コネクタ再認可後も同じ）。読み取り系（`list_labels` / `search_threads` / `get_thread`）は通る。

将来コネクタに書き込みスコープが付いたらラベル方式へ戻せるが、ローカル記録でも機能は同じで、Gmail 側に一切変更を加えない分こちらのほうが副作用は小さい。

### 順序とトレードオフ

「**記録の更新 → 通知本文を最終応答として返す**」の順で実行する。理由: claude の最終応答を返した時点でツール実行は終了するため、最終応答を返す前に記録を書き込む必要がある。

- **記録の更新後・通知前にプロセスが死ぬ** → 通知漏れ。発見方法: `notified.json` に入っているのに Discord に来ていない thread を探す。再通知したい場合は該当エントリを消すと、12h 窓の内側であれば次サイクルで拾われる
- 重複通知（spam）より通知漏れの方が運用負荷が低いと判断

### 判定の非決定性について

フィルタと違い、同じメールが実行ごとに違う判定を受けうる。緩和策:

- prompt に判定基準を具体的に列挙してブレを抑える
- 「迷ったら通知しない」を明示し、窓 12h × 実行 6h で 2 回評価されることで拾い直せるようにする
- 通知本文に `（候補 M 件・除外 K 件）` を出し、**何件を落としたか**が毎回見えるようにする（見落としに気づけるようにするため）

### 既知の制限

- `notified.json` の `at` は claude が書くため**実際の実行時刻と数十分ずれることがある**（時刻取得ツールを許可していない）。3 日でエントリを捨てる判定にしか使わないので実害はない。
- 一度通知した thread は、その後に新しい返信が届いても再通知されない。継続中のやり取りを追いたい場合は `notified.json` から該当エントリを手で消す。
- `Read` の対象を `notified.json` と `rules.md` に、`Write` を `notified.json` に限定しているのは prompt の指示だけで、ツール権限としては他のファイルにも触れてしまう（ジョブ側の話。Discord からのルール調整では `Write` を渡していないので事情が違う）。
- `rules.md` が肥大すると一次スクリーニングのコストと判定のブレが増える。ルール調整側は 50 エントリでハードストップし、それ以上は追記せず整理を促す。

## トラブルシュート

| 症状 | 確認 |
|---|---|
| Discord に何も来ない | (a) `logs/mail-watch/<ts>.json` の `.result` を確認 → `[NOOP]` なら「重要なメール 0 件」で正常。<br>(b) `.stderr` に `Discord post failed` が無いか確認。<br>(c) `.env` の `DISCORD_WEBHOOK_URL` が有効か確認 |
| 重要なメールが通知されなかった | `.result` の `除外 K 件` を確認。専用チャンネルで「これは通知してほしかった」と返信するか、`prompt.md` の「重要度の基準」の**通知する側**に条件を追記する。`var/mail-watch/rules.md` に効きすぎた除外ルールが無いかも見る |
| どうでもいいメールが通知される | 専用チャンネルでその通知に返信して「これは要らない」と書く（`rules.md` に追記される）。恒久的な条件なら `prompt.md` 側に書く |
| 通知が旧チャンネルに来る | `.env` の `MAIL_WATCH_DISCORD_WEBHOOK_URL` が空でフォールバックしている。値を入れて再試走する |
| 専用チャンネルに書いても bot が反応しない | (a) `.env` の `MAIL_WATCH_CHANNEL_IDS` にそのチャンネル ID が入っているか。(b) `systemctl --user restart discord-gateway` を忘れていないか。(c) `journalctl --user -u discord-gateway` に `mail-watch feedback enabled` が出ているか |
| `⚠️ ルールファイルの検証に失敗` が返る | `rules.md` の `<!-- APPEND:* -->` アンカーが 3 つ揃っているか確認する。バックアップから自動復元済みなので実害は無いが、繰り返すなら `var/mail-watch/rules-audit.jsonl` を見る |
| 同じメールが何度も通知される | `notified.json` に書き込めているか確認。パーミッションやパスの誤りで Write が失敗していないか `logs/.../<ts>.json` を見る |
| `ERROR: notified.json update failed: ...` | `var/mail-watch/` の書き込み権限を確認。ディレクトリごと消えていたら再作成する |
| `insufficient authentication scopes` が出る | Gmail コネクタの権限不足。読み取り系すら通らない場合は claude.ai 側で Gmail 連携を繋ぎ直す |
| 候補が多すぎて未評価が出る（`※候補が上限に達した`） | `pageSize=50` を超える受信量。`prompt.md` のクエリに `-from:` などの除外条件を足して候補を減らす |
| ゴミ箱のメールが通知される | クエリの `-in:trash` をすり抜けた場合の保険として `prompt.md` 手順 3 で `labelIds` に `TRASH`/`SPAM` を含む thread を捨てている。ここが効いているか `logs/.../<ts>.json` で確認する |
| `is_error: true` で exit code != 0 | `--allowed-tools` に必要なツールが入っているか、MCP サーバが起動しているか、claude が disallowed ツールを呼ぼうとしていないかを `stderr` で確認 |

## 設計の変遷

- **Phase 1（Issue #2, 2026-07）**: ユーザーが Gmail フィルタで `hermes-lite` ラベルを貼り、その未読 thread（`label:hermes-lite is:unread`）を通知。通知後に `hermes-lite` → `hermes-lite/done` へ付け替えて重複を防ぐ設計だった（この 2 ラベルは結局作成されず、実運用されないまま終わった）。
- **2026-07-28 の書き換え**: 「何を通知するか」の条件を Gmail フィルタで人間が書き下ろす必要があり、条件から漏れたメールは永久に拾われなかった。判定を claude 側に移し、直近 12h の受信を全部評価する方式に変更。
- **2026-07-28 の追加修正**: 通知済みマーカーを Gmail ラベル（`helmeslite-done`）で持つ設計にしたが、コネクタのスコープ不足で `label_thread` が使えず断念。ローカルファイル `var/mail-watch/notified.json` に移した。Gmail 側の設定は完全に不要になった。
- **2026-08-01**: 通知が 6h ごとに届いて多すぎたため、**投稿を 1 日 1 回にまとめる**構成へ変更。`mail-watch` は検知と振り分けだけを行い（間隔を 2h に短縮）、重要と判定したメールは原則 `pending.json` に積む。翌朝 08:30 の `mail-digest` が 1 通にまとめて投稿する。即時通知は「明日の朝では間に合わない」ものだけの例外に格下げした（`prompt.md` の「即時通知の基準」）。あわせて、claude が説明文の後ろに `[NOOP]` を置いたときに不要通知が飛んでいた穴（2026-07-31 実測）を `run-claude.sh` の末尾一致判定で塞いだ。
- **2026-07-29**: 通知を専用チャンネルへ分離し（`MAIL_WATCH_DISCORD_WEBHOOK_URL`）、そのチャンネルでのフィードバックから `var/mail-watch/rules.md` を更新する経路を追加。判定基準を「prompt.md の骨格（人間が編集）＋ rules.md の学習分（Discord から更新）」の 2 層にした。通知本文に短縮 thread ID を出すようにしたのもこのとき。

## 関連ファイル

- `jobs/mail-watch/prompt.md` — 検知側の claude 向け指示。**重要度の基準と即時通知の基準はここで調整する**
- `jobs/mail-watch/job.env` — ALLOWED_TOOLS / MAX_TURNS など
- `jobs/mail-digest/prompt.md` — まとめ投稿側の指示。メールは読まず pending の行を並べるだけ
- `jobs/mail-digest/job.env` — ALLOWED_TOOLS は `Read Write` のみ
- `var/mail-watch/notified.json` — 処理済み thread ID（即時通知分＋保留分。git 管理外）
- `var/mail-watch/pending.json` — 翌朝のまとめ待ちキュー（git 管理外）
- `var/mail-watch/pending-sent.json` — まとめ投稿の直前に取る退避（git 管理外）。投稿が Discord 側の障害で落ちた日は、これを `pending.json` に戻せばもう一度まとめられる
- `var/mail-watch/rules.md` — フィードバックで学習した追加ルール（git 管理外）。`rules.bak/` と `rules-audit.jsonl` が併走する
- `gateway/discord/mail_rules_handler.py` — 専用チャンネルの発言を受けて `rules.md` を編集するハンドラ
- `gateway/discord/mail_rules_prompt.md` — そのハンドラが `claude -p` に渡すプロンプト（**呼び出しごとに読み直すので、ここだけの変更なら bot 再起動は不要**）
- `bin/run-claude.sh` — `.env` → `job.env` の順に source、`SUPPRESS_RESULT_IF` opt-in を提供
- `lib/disallowed-tools.txt` — Calendar / Notion 書き込みなどを全ジョブ共通で禁止
- `lib/notify.sh` — Discord webhook 投稿ヘルパ（1900 字 truncate 込み）
- `features/2-email-gateway-gmail-discord/{plan.md, rejection.md, test-spec.md}` — Phase 1 の設計と手動テスト（旧方式の記録）
