# Runbook: SwitchBot 家電操作（Discord 自然文 → 実機）

Discord で「電気つけて」「エアコン消して」「毎朝7時にライト点けて」等の家電操作を頼まれたときに
**この runbook に従って即実行する**（Issue #12）。SOUL.md からここへ誘導される。

## 大原則

- **即時実行・確認なし**（ユーザー決定 2026-07-04）。「電気つけて」→ その場で実行し、
  実行後に「ライトをつけました」等と**短く1行**報告する。事前確認は挟まない。
- 成功判定は **コマンドの exit 0**。`status` の `power` フィールドは SwitchBot 側の反映遅延が
  あるため、実行直後の読み戻しに依存しない（消灯しても暫く `power:"on"` に見えることがある）。
- 単発（「今」「ちょっと」等）→ その場で `python3 lib/switchbot.py ...` を実行。
- 定期（「毎朝」「毎日」「平日」「いつも」等）→ `bin/sb-schedule add ...` で systemd timer 登録。
- コマンドはすべて **cwd=~/hermes-lite からの相対パス**で呼ぶ（`python3 lib/switchbot.py ...` /
  `bin/sb-schedule ...`）。この形だけが headless 実行で許可されている。
- 認証情報は `switchbot.py` が `.env` から自力で読む。トークンを表示・言及しない。

## 外出トリガー（自動オフ）

「いってくる」「行ってきます」「出かける」「外出する」など**外出を示すメッセージ**を読み取ったら、
確認なしで**エアコンオフ + 電気オフ**を実行する（ユーザー決定 2026-07-05）。

```bash
python3 lib/switchbot.py command 02-202306010006-50181031 turnOff   # エアコン
python3 lib/switchbot.py command E72A34313AB7 turnOff               # 電気
```

実行後「いってらっしゃい。エアコンと電気を消しました」のように短く1行で報告する。
「ただいま」等の帰宅ワードは家電マップのシーン「ただいま」があるので、要望があればそちらを案内する。

## 家電マップ（呼び名 → ID / コマンド）

| 呼び名（揺れ） | 種別 | ID | 操作 |
|---|---|---|---|
| 電気 / ライト / 照明 | Ceiling Light | `E72A34313AB7` | `command <id> turnOn` / `turnOff` / `setBrightness <1-100>` |
| カーテン | Curtain | `D7577389F460` | `command <id> turnOn`（開）/ `turnOff`（閉）※開閉方向は要実機確認 |
| エアコン | IR (Air Conditioner) | `02-202306010006-50181031` | `command <id> turnOn` / `turnOff` / `setAll <temp,mode,fan,power>` |
| 温湿度計（室温） | WoIOSensor | `E96465BDC3F4` | `--json status <id>`（temperature / humidity） |

### シーン（SwitchBot アプリ登録済み）

| 呼び名 | sceneId |
|---|---|
| ナイトルーム | `T02-202308052327-59949881` |
| シアタールーム | `T02-202308052325-66522424` |
| ただいま | `T02-202305312356-52700466` |
| かくせい | `7762aa8c-d516-4a96-a226-34cfaca0d2ae` |

シーン実行: `python3 lib/switchbot.py scene <sceneId>`

### エアコン setAll の書式

`parameter` = `温度,モード,風量,電源` （例 `26,2,3,on`）
- モード: `1`=自動 / `2`=冷房 / `3`=除湿 / `4`=送風 / `5`=暖房
- 風量: `1`=自動 / `2`=弱 / `3`=中 / `4`=強
- 電源: `on` / `off`
- 例（26℃冷房・中風量でオン）: `python3 lib/switchbot.py command 02-202306010006-50181031 setAll "26,2,3,on" command`

エアコンは IR のため状態を SwitchBot 側が保持しない（送りっぱなし）。「消して」は `turnOff`。

**デフォルトモードは除湿（モード `3`）**（ユーザー決定 2026-07-05）。「エアコンつけて」等でモード指定が
無いときは冷房ではなく除湿で `setAll` する。温度・風量の指定が無ければ直近の値を踏襲するか、無ければ
温度は指定値／風量は自動（`1`）でよい。「冷房で」「暖房で」と明示されたときだけそのモードにする。

## 家電の状態確認

「家電の状態は？」「今どうなってる？」「電気ついてる？」「カーテン開いてる？」等の
状態問い合わせは **`bin/sb-status`** を使う（温湿度計・電気・カーテンを一括取得）。
エアコンは IR 送信のみで SwitchBot 側が状態を保持しないため、この一覧では取得不可と
明示される（既知の制約、混乱しないこと）。

### ショートカット: `/home`

Discord で **`/home`** とだけ送られたら、確認なしで `bin/sb-status` を実行し、
出力をコードブロックに包んで返す（ユーザー決定 2026-07-05、`bin/` と打つのを省くため）。
「家電」「状態」「今どう」など曖昧な問い合わせのときも `sb-status` を叩いてよい。

```bash
bin/sb-status              # 人間可読で全機器
bin/sb-status --json       # JSON でまとめて（機械処理向け）
bin/sb-status E72A34313AB7 # 単一デバイスの status
```

出力例（Discord への短報告用にそのまま貼ってよい）:

```
温湿度計  室温 24℃ / 湿度 67%   電池 100%
電気      ON  明るさ 5%
カーテン  position 0 / 100  battery 15%
エアコン  IR 送信のみ（状態取得不可）
```

## よくある操作の例

```bash
# 電気をつける / 消す
python3 lib/switchbot.py command E72A34313AB7 turnOn
python3 lib/switchbot.py command E72A34313AB7 turnOff
# 電気を30%に調光
python3 lib/switchbot.py command E72A34313AB7 setBrightness 30
# 室温を答える
python3 lib/switchbot.py --json status E96465BDC3F4   # temperature / humidity
# ナイトルームのシーンにする
python3 lib/switchbot.py scene T02-202308052327-59949881
# 毎朝7時に電気を点ける（定期）
bin/sb-schedule add --name led-morning --calendar "*-*-* 07:00:00" -- command E72A34313AB7 turnOn
# 平日22時に暖房シーン
bin/sb-schedule add --name aircon-night --calendar "Mon..Fri *-*-* 22:00:00" -- scene T02-...
# 登録済みスケジュール一覧 / 削除
bin/sb-schedule list
bin/sb-schedule remove --name led-morning
```

## スケジュール登録時の注意

- `--name` は英数字・ハイフン・アンダースコアのみ。依頼内容から分かりやすい名前を付ける
  （例: 朝の点灯 → `led-morning`）。
- `--calendar` は `man systemd.time` の `OnCalendar=` 書式。毎日=`*-*-* HH:MM:SS`、
  平日=`Mon..Fri *-*-* HH:MM:SS`、毎週日曜=`Sun *-*-* HH:MM:SS`。
- 登録したら「毎朝7時にライトを点けるよう登録しました」と報告し、`list` の該当行を確認に添えてもよい。

## やってはいけないこと

- 承認を待つ挙動（このユーザーは即時実行を選択済み。聞き返さない）。
- 家電名が家電マップに無いのに推測で ID をでっち上げる → 「その家電は未登録です。SwitchBot アプリで
  確認して登録が要ります」と返す（推測禁止ルール）。
- トークン/シークレットの表示・ログ出力。

## 将来拡張（未実装・メモ）

- **カレンダー連携**: 「今月の旅行中は在宅演出で夜だけ点灯」等、Google Calendar の予定に応じた
  条件付きスケジュール。現状は固定時刻の `sb-schedule` のみ。予定連動は別ジョブ（jobs/<name>/）として
  カレンダー読み取り → その日の sb-schedule 動的登録、の形が候補。着手時に設計合意する。
