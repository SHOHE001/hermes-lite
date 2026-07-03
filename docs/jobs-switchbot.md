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
