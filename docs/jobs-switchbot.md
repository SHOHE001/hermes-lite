# SwitchBot 家電スケジュール（Issue #12）

Discord の自然文（例:「毎朝7時に電気つけて」）を起点に、SwitchBot API v1.1 経由で家電（LED 照明・エアコン）を
定型スケジュールで on/off する機能。Issue #12 (`gate:human-feel`, milestone `Phase 4`) の実装。

## 現状のスコープ

このドキュメントが書かれた時点で実装済みなのは **CLI 基盤 + スケジューラ** まで。
**Discord の自然文入力から `sb-schedule` を実際に呼び出す配線は未実装（保留）**。
理由: `claude -p` ヘッドレス実行時の Bash 権限検証と実機動作確認が必要で、どちらも
下記「人間必須の手順」が終わってからでないと安全に検証できないため。

現時点でできること:
- `lib/switchbot.py` — SwitchBot API v1.1 を直接叩く CLI（デバイス一覧・ステータス取得・コマンド送信・シーン実行）
- `bin/sb-schedule` — 上記を systemd --user timer として登録/一覧/削除する CLI
- `systemd/switchbot-action@.{service,timer}` — その実体となる oneshot テンプレート unit

## 構成

```
bin/sb-schedule add --name <n> --calendar "<OnCalendar>" -- <switchbot.py 引数...>
  → var/switchbot-schedules/<n>.env に SB_ARGS="..." を保存
  → ~/.config/systemd/user/switchbot-action@.{service,timer} をインストール
    （__HERMES_HOME__ プレースホルダーを実行中の hermes-lite パスへ置換）
  → ~/.config/systemd/user/switchbot-action@<n>.timer.d/schedule.conf に OnCalendar= を書き込み
  → systemctl --user enable --now switchbot-action@<n>.timer

OnCalendar 発火時:
  switchbot-action@<n>.service (oneshot)
    → .env（共通認証情報）+ var/switchbot-schedules/<n>.env（SB_ARGS）を読み込み
    → python3 lib/switchbot.py $SB_ARGS
    → 失敗時のみ notify_discord で Discord に警告（lib/notify.sh 流用）
```

`lib/switchbot.py` は標準ライブラリのみで実装（依存ゼロ）。認証は `SWITCHBOT_TOKEN` /
`SWITCHBOT_SECRET` を環境変数で受け取り、どちらか欠けていれば即エラー終了する（fail-fast）。
値はログにも Discord 通知にも出さない。

### 開発クローンと本番クローンの両対応について

このリポジトリは `~/hermes-lite`（本番稼働ツリー、systemd から実際に読まれる）と
`~/プロジェクト/hermes-lite`（開発ツリー）の2箇所にクローンされている環境で運用されることがある。
`bin/sb-schedule` は自分自身の絶対パスから `HERMES_HOME` を動的解決し、インストールする
unit テンプレート内の `__HERMES_HOME__` プレースホルダーをそこへ置換する。
そのため **`sb-schedule` はどちらのクローンから実行しても、そのクローンを指す unit が生成される**。
本番運用するときは必ず本番ツリー（`~/hermes-lite`）側で `sb-schedule add` を実行すること
（開発ツリー側で登録すると、開発ツリーが消えた際に timer が壊れる）。

## セットアップ手順

### 1. SwitchBot トークン/シークレットを取得（人間必須）

SwitchBot アプリ → プロフィール → 設定 → 「App Version」を連打 → Developer Options が出現
→ Get Token / Get Secret。

### 2. `.env` に認証情報を書く（人間必須）

```bash
cd ~/hermes-lite   # 本番ツリー
cp -n .env.example .env   # 既に .env があれば何もしない
$EDITOR .env
```

`SWITCHBOT_TOKEN=` / `SWITCHBOT_SECRET=` に実値を書く。`.env` は `.gitignore` 済み。

### 3. デバイス ID / シーン ID を確認（人間必須・実機操作を伴う）

```bash
cd ~/hermes-lite
python3 lib/switchbot.py devices   # LED・温湿度計などの deviceId を確認
python3 lib/switchbot.py scenes    # SwitchBot アプリで登録済みのシーン（エアコン等）の sceneId を確認
```

エアコンは Hub Mini 経由の赤外線家電のため、個別コマンドではなく **SwitchBot アプリ側で
シーンとして事前登録**し、そのシーン ID を `sb-schedule` から呼ぶ想定（Issue #12 の決定事項）。

### 4. 動作確認（人間必須・実機で on/off が起きる）

```bash
# 単発実行で確認してからスケジュール登録する
python3 lib/switchbot.py command <LED の deviceId> turnOn
python3 lib/switchbot.py command <LED の deviceId> turnOff
python3 lib/switchbot.py scene <エアコンシーンの sceneId>
```

## `sb-schedule` の使い方

### 登録

```bash
# 毎日 7:00 に LED 点灯
bin/sb-schedule add --name led-morning --calendar "*-*-* 07:00:00" -- command <deviceId> turnOn

# 平日 22:00 にエアコン暖房シーンを実行
bin/sb-schedule add --name aircon-night --calendar "Mon..Fri *-*-* 22:00:00" -- scene <sceneId>

# 毎週日曜 21:00
bin/sb-schedule add --name weekly-sun --calendar "Sun *-*-* 21:00:00" -- command <deviceId> turnOff

# 毎月1日 9:00
bin/sb-schedule add --name monthly-1st --calendar "*-*-01 09:00:00" -- command <deviceId> turnOn
```

`--calendar` の書式は `man systemd.time` の `OnCalendar=` 相当（`systemd-analyze calendar "<式>"` で事前検証可能）。

### 一覧

```bash
bin/sb-schedule list
```

`name` / `calendar` / `active`（systemd timer の状態）/ `args` を表示する。

### 削除

```bash
bin/sb-schedule remove --name led-morning
```

## 温湿度計の read（「今の室温は」応答への転用）

```bash
python3 lib/switchbot.py status <温湿度計の deviceId>
python3 lib/switchbot.py status <温湿度計の deviceId> --json   # temperature/humidity を機械可読で取得
```

Discord から「今の室温は」と聞かれて答える別ジョブ（`jobs/<name>/`）への組み込みは、
自然文配線と合わせて保留中。

## エラーハンドリング

- SwitchBot API 呼び出し失敗時、`lib/switchbot.py` は exit 1 + stderr にエラー理由を出す。
- `switchbot-action@<n>.service` はこれを拾って `notify_discord` で
  `⚠️ SwitchBot schedule <n> 失敗 (SB_ARGS=...)` を Discord へ通知する（`lib/notify.sh` 流用）。
- ラッパー（service 側）自体は常に `exit 0` 相当で終わるため、1回の失敗で timer 連鎖が壊れることはない
  （`bin/run-claude.sh` と同じ設計方針）。

## 人間必須の手順（このドキュメントで完結しないもの）

1. SwitchBot アプリでトークン/シークレット発行 → `.env` に実値記入。
2. `switchbot.py devices` / `scenes` で LED・温湿度計の `deviceId`、エアコンの `sceneId` を確定。
3. `sb-schedule add` で実機に対して 1 本動作確認（LED on/off が実際に動くこと）。
4. （保留機能）Discord 自然文 → `sb-schedule` 呼び出しの配線、および `claude -p` ヘッドレスからの
   Bash 実行権限の検証。

## Discord 自然文配線の設計（保留機能・未実装）

「Discord に自然文を投げると SwitchBot 操作になる」部分の設計メモ。実装は上記「人間必須の手順」
1〜3 が終わり実機確認が取れてから着手する。決定済みの点と **要確認**（ユーザーに聞く必要がある点）を
分けて記す（推測禁止ルール準拠）。

### 全体像

```
Discord 「毎朝7時に電気つけて」
  → gateway/discord（claude -p, cwd=~/hermes-lite, CLAUDE.md ロード済み）
  → runner が意図を解釈:
      即興（今つけて）      → その場で python3 lib/switchbot.py command <id> turnOn
      定期（毎朝つけて）    → bin/sb-schedule add --name ... --calendar ... -- command <id> turnOn
  → 実機 on/off（SwitchBot API v1.1）
```

### 決めるべき3つの軸

#### 1. Bash 権限の解禁（技術的な核心・保留理由そのもの）

現状 `gateway/discord/claude_runner.py` は `ALLOWED_TOOLS = ["WebSearch", "WebFetch"]` のみ。
Bash 自体は `claude -p` の既定ツールだが、**ヘッドレス実行では承認プロンプトに応答できない**ため、
allowlist に無い Bash 呼び出しは実行時に弾かれる（これが「Bash 実行権限の検証」の中身）。

配線するには runner に以下いずれかを許可する必要がある:

- 案A（最小権限）: `Bash(bin/sb-schedule:*)` と `Bash(python3 lib/switchbot.py:*)` だけを
  `ALLOWED_TOOLS` に追加する。switchbot 以外の任意 Bash は引き続き弾かれる。**推奨**。
- 案B（広い）: `Bash` を丸ごと許可。他ジョブと共通の runner なので影響範囲が広く、非推奨。

→ 実装前に「案A の allowlist 形式で `claude -p` が実際に `bin/sb-schedule` を通すか」を
最小テストで検証する（`claude -p --allowed-tools 'Bash(bin/sb-schedule:*)' ...` で1本叩く）。
**allowlist のマッチ書式（`Bash(cmd:*)` か `Bash(cmd *)` か）が claude CLI の版で違う可能性があり、要実機確認。**

#### 2. 「電気」「エアコン」→ ID の解決（要確認）

runner は自然文の家電名を `deviceId` / `sceneId` に変換する必要がある。マップの置き場所が未決定。

- 候補: `var/switchbot-devices.json`（人間が手順2の `devices`/`scenes` 出力を見て記入）。
  例: `{"電気": {"kind":"device","id":"ABC123"}, "エアコン暖房": {"kind":"scene","id":"xyz"}}`
  runner はこれを読んで解決し、未登録の名前は「その家電は未登録です」と返す。

→ **要確認**: この JSON 方式でよいか / 家電の呼び名の揺れ（「電気」「照明」「ライト」）をどこまで吸収するか。

#### 3. 即興実行と承認ゲートの扱い（要確認）

Issue #12 には `gate:human-feel` ラベルが付いている。実世界の家電を勝手に on/off する操作なので、
既存の Discord 承認ゲート基盤（コミット `a69fe14` の Calendar.create 承認と同じ仕組み）を通すか判断が要る。

- 即興「今つけて」: 即実行してよいか、それとも「電気をつけます。OK?」と一度承認を挟むか。
- 定期「毎朝つけて」: `sb-schedule add`（スケジュール登録）を承認ゲート必須にするか。

→ **要確認**: gate:human-feel を「実行前に Discord で一度確認」と解釈してよいか。夜間の誤操作
（寝室の電気を勝手に点ける等）のリスクを踏まえ、少なくとも即時実行系は承認を挟むのが無難だが決めるのはユーザー。

### 実装順序（合意後）

1. 軸1 の allowlist 書式を最小テストで確定 → `claude_runner.py` に switchbot 用 Bash を追加。
2. 軸2 の名前→ID マップ（`var/switchbot-devices.json`）を実装、runner に解決ロジック。
3. 軸3 の承認ゲート方針に沿って即興/定期の分岐を CLAUDE.md（または runbook）に行動規範として記述。
4. Discord から「今つけて」「毎朝つけて」を1本ずつ実機で通し確認。
