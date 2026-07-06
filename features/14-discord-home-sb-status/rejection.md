# Rejection log for #14

## design review loop 1 (2026-07-06)

blocking 5 件（high 5）はすべて plan.md に反映（採用）。以下の medium 指摘は棄却または部分棄却。

### 棄却: contrarian「部分失敗の合成は Issue 仕様から外れた拡張 — exit != 0 は失敗応答だけにせよ」(medium)

- 根拠: `sb-status` の CLI 公開契約（docstring）が「1機器でも取得失敗があれば exit 1」であり、部分失敗が定常的に起こり得る設計。Issue の失敗フォーマットだけだと 2/3 機器の正常値が Discord に届かず、人間完了条件「SwitchBot API 障害時の失敗応答が読める」の実用性が下がる。合成は成功/失敗フォーマットの単純連結でありテスト 1 件（T07）で固定できる。
- ただし architect 指摘（内部関数名 `_collect`/`_print_human` への依存記述）は採用し、根拠を CLI の観測可能な契約（exit code / stdout / stderr）に書き換えた。

### 棄却: contrarian「truncation を Non-Goal にするか後続 Issue に分離」(medium 相当の suggestion)

- 根拠: migration persona が逆に「handler 戻り値の 2000 字以下保証を固定せよ」(high) と要求しており、放置すると `--json` 出力の肥大時に Discord 送信 API が 400 を返す実害経路がある。分離せず、本 plan で「警告行込み全体 ≤ 2000 字保証・切り詰めはコードブロック内部のみ・stderr 1 行目は 200 字で切る」まで仕様を固定して解消した。

### 部分棄却: migration「help 順序を期待値に含めよ」(medium)

- 既存テストは help 出力の存在のみ検証（順序期待なし）であることを確認し plan に明記した。順序アサーションの追加は既存 UX に順序契約が無い以上、過剰な固定化になるため追加しない。

## design review loop 2 (2026-07-06)

blocking 6 件（high 6）。今回は loop 1 の自分の判断を 2 点撤回した。

### 採用（loop 1 判断の撤回）: contrarian「部分失敗合成は Issue 仕様の上書き」(high)

- loop 1 では「情報を捨てない」を理由に棄却したが、Issue 決定事項「失敗（exit != 0）: ⚠️ + stderr 1行目」を handler 側の裁量で上書きする拡張であることは否めず、推測禁止ルール（合意なき仕様追加をしない）とも整合しないため撤回。exit != 0 は stdout の有無に関わらず ⚠️ 行のみに戻した（T07 で固定）。stdout 併記の改善は Issue 側の受け入れ条件変更を伴う follow-up 候補として Out-of-Scope に記載。

### 採用（loop 1 判断の変更）: architect + contrarian「2000 字対策を home.py 固有にするな」(high ×2)

- architect は「transport 制約が handler に逆流」、contrarian は「送信境界での共通 truncate で十分」と、別 persona が同一の代替案（dispatch/送信層の共通 clamp）に収束したため採用。`dispatch()` の return 直前に全コマンド共通の `_clamp`（単純末尾切り詰め + truncated 注記）を追加し、home.py から切り詰めロジックを排除した。

### 採用: migration「UnicodeDecodeError 未定義」(high) → `errors="replace"` を追加

### 採用: migration「--json 切り詰めの契約」(high) → `/home --json` を表示専用契約と Non-Goals に明記（機械可読は SSH で直接 sb-status）

### 部分棄却: architect「sb_status_path を CommandContext に持たせよ」(high)（loop 2 時点の記録、下記 loop 3 でも維持）

- パス解決の明文化要求は採用（設計判断セクション追加）。ただし `CommandContext` へのフィールド追加は棄却: `hermes_home` は types.py の docstring で「handler がファイルを読む基点」と定義済みの契約で、status.py に repo 相対パス組み立ての前例がある。コマンド 1 個のために bot.py の ctx 構築コードまで波及させるのは過剰。所在変更時は home.py のモジュール定数 1 箇所で追従。

## design review loop 3 (2026-07-06)

blocking 6 件（high 6）。dispatch 出口 clamp 案（loop 2 で採用）が 3 persona 全員から「dispatch の公開契約を壊す / transport 層に置け」と否決され、方針を再転換した。

### 採用（loop 2 判断の撤回）: 全 persona「clamp は bot.py 送信層に置け」(high ×3)

- 調査の結果、bot.py には既に `_split_for_discord`（bot.py:108、limit=1900、改行位置優先分割）が存在し claude 応答経路で稼働実績があること、slash 経路（bot.py:367）だけが生 send で長文時に HTTPException になる既存の穴があることを確認。dispatch への clamp 追加を撤回し、slash 送信を既存分割送信に乗せ換える方針に変更（新規ロジックゼロ、dispatch 契約不変）。

### 解消: contrarian + migration「--json が invalid JSON になる」(high ×2)

- clamp（切り詰め）から split（分割送信）への変更で内容欠落自体が消滅。JSON 本体は失われない。コードブロックの見た目崩れのみ許容として Non-Goals に明記。

### 棄却: architect「T08 注入 registry のテスト設計不備」(high)

- dispatch clamp 自体を撤回したため T08/T09（clamp テスト）ごと削除。指摘対象が消滅。

### 棄却: contrarian「sb-status を subprocess でなく import 呼び出しする案の比較がない」(medium)

- Issue 決定事項が「subprocess で `~/hermes-lite/bin/sb-status` を実行」と明記しており、実行方式は合意済み。bot プロセスに switchbot lib を import すると SwitchBot API 障害が bot 本体に波及する面もあり、プロセス分離は妥当。

## design review loop 4 (2026-07-06)

blocking 5 件（high 5）。

### 採用: 全 persona「bot.py 送信変更が無テスト — helper に切り出してテスト可能にせよ」(high ×3)

- 3 persona の suggestion が「送信部を小さな helper に分離して fake channel/send でテスト」に一致したため採用。discord 非依存の `gateway/discord/transport.py` を新設し、`split_for_discord`（bot.py:108 から移設）+ `async send_chunks(send, text)` を置く。テストは fake send で T10-T13 を追加（短文 1 回送信の互換固定・長文分割・途中失敗の例外伝播・移設パリティ）。config.py が env 未設定でも import 可能なことは実機確認済み。
- migration の「全 slash コマンドへの波及」も、これを全コマンド共通 transport 変更として明示し T10（短文不変）で互換を固定することで対応。

### 棄却（明記で対応）: contrarian「/home 連打の同時実行制御がない」(high)

- suggestion の「採らないなら想定頻度・API 制限・同時実行時の期待挙動を明記」の側を採用。単一ユーザー運用（ALLOWED_USER_IDS）・SwitchBot API 日次上限に対する 3 桁の余裕・20 秒 timeout による自然回収を設計方針に明記した。rate limit 実装は単一ユーザー bot には過剰。

## design review loop 5 (2026-07-06)

blocking 5 件（high 5）。細部の整合性指摘に収束。

### 採用: architect「transport が config import しており stdlib のみと矛盾」(high)

- transport.py はローカル定数 `DEFAULT_MESSAGE_LIMIT = 1900` を持ち config に依存しない形に修正。実 limit は bot.py が `config.MAX_DISCORD_MESSAGE` を引数注入する。

### 採用: contrarian + migration「『内容欠落なし』と T11 の『改行欠落を除く』が矛盾」(high ×2)

- 内容保持契約を「チャンク境界に選ばれた改行のみ除去、他の文字は完全保持」と正確化。旧実装の `lstrip("\n")` は claude 応答経路の互換優先でそのまま移設（挙動変更しない）。T11/T13 の期待値もこの契約に固定。改行欠落の可能性は `/home --json` を表示専用契約とする根拠の一つとして Non-Goals に接続。

### 採用: migration「bot.py after が未定義の transport を参照」(high)

- `import transport` を bot.py 変更点として明示（3 箇所に整理: import 追加 / 旧関数削除と claude 経路の置換 / slash 送信の置換）。

### 棄却: contrarian「transport 切り出しと全 slash 送信変更は過剰スコープ」(high)

- loop 3 で 3 persona が「clamp は bot.py 送信層へ」、loop 4 で 3 persona が「送信部をテスト可能な helper に切り出せ」と要求した帰結がこの設計であり、今さら「/home 出力を 1900 字以下に制御する」案に戻すと loop 2（handler に transport 制約を持ち込むな）と矛盾する。persona 間で相反する要求のデッドロックであり、多数派（architect/migration が容認し細部修正のみ要求）に従う。スコープ増は transport.py 約 40 行 + テスト 4 件で bounded。

## design review 最終確認 dispatch (2026-07-06, design_loops=5/5 到達後)

blocking 4 件（high 4、critical 0）。max_design_loops 到達につき以下を**裁量で残置**し design_review passed とする。

- architect「transport の内容保持契約が lstrip 挙動と厳密には不一致」: `lstrip("\n")` は境界の連続改行を複数落とし得る。実装時に T11/T13 で実挙動どおりに固定する（契約文言は「境界の改行（連続含む）」と読み替え）。実害なし。
- architect「bot.py 変更範囲の記述の曖昧さ」: 実装対象 3 点の列挙で implementer には十分伝わる。実装 diff が真実。
- contrarian「transport 抽出は横断変更」: loop 5 で棄却済みの再提起。persona 間デッドロック（loop 2 で「handler に持ち込むな」⇔ 本指摘「bot.py に波及させるな」）のため多数派設計を維持。
- migration「既存コマンド互換の統合テスト不足」: T10（短文 1 send 不変）で transport 層の互換は固定。bot.py 統合レベルは discord.py 依存で自動化不能（既存方針）、人間完了条件の実機確認で担保。
