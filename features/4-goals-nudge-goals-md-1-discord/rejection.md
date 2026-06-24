# Rejection log for #4

design_loops=1 終了時点で、Codex 3 persona 9 findings はすべて plan.md に反映済み（採用）。棄却した findings は無い。

## 反映サマリ

| persona | severity | title | 反映先 |
|---|---|---|---|
| architect | high | `goals.md` のパスが既存 workspace と衝突している | 設計方針 §1（HERMES_HOME ベース解決）+ §5（cwd 固定） |
| architect | high | `ALLOWED_TOOLS=""` で Read 可能という前提が未検証 | 設計方針 §2（run-claude.sh line 118-122 仕様を引用、`Bash` / `Read` は disallowed に無いと明示） |
| architect | high | `SUPPRESS_RESULT_IF="[NOOP]"` が既存通知経路に適合する保証がない | 設計方針 §2（exact match 仕様を明示、`[NOOP]` 単独応答に厳密化） |
| architect | medium | systemd の JST 要件が `OnCalendar` に表現されていない | 設計方針 §4（`timedatectl` 確認を docs と T06 に追加） |
| architect | medium | 既存関数編集の before/after がない | 設計方針 §5（`bin/run-claude.sh` の before/after を追加） |
| architect | medium | Issue body の frontmatter / 最終 nudge 日と最終設計の差分整理が弱い | In/Out-of-Scope 表 + 設計方針 §1（旧形式の `frontmatter` / `最終 nudge 日:` を無視する解釈ルール）+ Non-Goals 明示 + T07_boundary |
| contrarian | high | LLM に deterministic な parser/date formatter を任せており過剰設計 | 設計方針 §2（**`claude -p` 採用は CLAUDE.md 不変ルール=Max OAuth 課金経路の都合で確定済み**だが、deterministic 部分の日付揺れだけは Bash `date +%Y-%m-%d` 注入で抑える）。スクリプト化案は不変ルールに反するので不採用、理由を Non-Goals 周辺で示唆 |
| contrarian | high | `ALLOWED_TOOLS=""` で Read できるという前提が未検証 | architect#2 と同じ反映 |
| contrarian | high | `[NOOP]` 抑制が exact match 依存で Discord 誤投稿を防げない | architect#3 と同じ反映。さらに prompt 側で「先頭・末尾の空白も改行も付けず `[NOOP]` だけを返す」を厳格に書く方針 |
| contrarian | medium | 毎週日曜 20:00 JST に対して timer の timezone が曖昧 | architect#4 と同じ反映 |
| contrarian | medium | 件数上限なしは YAGNI ではなく Discord 可用性リスク | In-Scope に「先頭 10 件、超過は ほか N 件」明示 + T08_boundary |
| contrarian | medium | parse 失敗時の扱いが In-Scope とテストに落ちていない | 設計方針 §1 解釈ルールに `⚠ parse 失敗` 行の出し方を明記 + T09_boundary |
| contrarian | low | 既存関数編集なしの明示がない | architect#5 と同じ反映（実装対象 §に「`systemd/claude-agent@.{service,timer}` テンプレは変更しない」明記） |
| migration | high | 既存 `run-claude.sh` / `job.env` 契約の互換性確認が欠落 | 設計方針 §2 で `ALLOWED_TOOLS=""` / `SUPPRESS_RESULT_IF` / `NOTIFY_RESULT` の解釈を run-claude.sh のソース行で裏取り、§5 で唯一の既存編集を明示 |
| migration | high | `ALLOWED_TOOLS=""` で Read が使えるかが未検証 | architect#2 と同じ反映 |
| migration | high | systemd drop-in の `OnCalendar` 追加が既存 timer を上書き/重複する可能性 | 設計方針 §4（既存テンプレに `OnCalendar` 無いことを裏取り済みと明示） |
| migration | medium | 既存関数編集の before/after スニペットがない | architect#5 と同じ反映 |
| migration | medium | 旧 Issue body の frontmatter / 最終 nudge 日入力形式からの移行扱いが曖昧 | architect#6 と同じ反映 + Non-Goals に「旧形式の自動変換はしない」明示 |
| migration | medium | 日付とタイムゾーンの互換性が曖昧 | 設計方針 §2（Bash 経由 `date +%Y-%m-%d` を毎回取得して prompt 文面に注入）+ §4（gen8 が Asia/Tokyo 前提を明示） |

## 棄却なし（loop 1）

design_loops=1 ですべて採用反映済み。

---

## 2 周目 (design_loops=2)

8 件 / 3 persona。多くは 1 周目の cwd 変更案を共通 runner グローバル変更として高 severity で再指摘されたもの。**設計判断を方針転換**して以下を採用:

| persona | severity | title | 反映 / 棄却 |
|---|---|---|---|
| architect | high | 単一 job の都合で共有 runner の cwd を変更している | **反映**: `bin/run-claude.sh` 変更を取り下げ。`prompt.md` で goals.md の絶対パスをハードコード（gen8 環境固定）。In-Scope 表、設計方針 §1, §5 を全面書き換え |
| architect | high | timer drop-in が In-Scope と言いつつ成果物にない | **反映**: In-Scope を「timer 登録**手順を docs に書く**」と弱める。drop-in 本体は repo 管理せず user 環境配置（mail-watch と同じスタイル）。実装対象に drop-in ファイルを含めない |
| architect | high | 構造化処理を prompt に押し込んでおりジョブ境界が曖昧 | **棄却（不変ルール優先）**: hermes-lite は CLAUDE.md「課金経路」で `claude -p` subprocess 経由を不変ルールとして固定済み。deterministic script に寄せる案は不変ルールに反する。**ただし軽減策は採用**: `ALLOWED_TOOLS` を `Read Bash(date:*)` に絞ってツール拡散をランナー側で遮断、prompt 側で「`[NOOP]` 5 文字のみ」を厳格に明示、`run-claude.sh` の exact match 依存リスクは prompt の output discipline で抑える |
| architect | medium | parse 不能の定義が `状態なしは active` と衝突 | **反映**: §1 解釈ルールを 6 ステップで機械的に再定義。「状態 key 欠落 = active」「状態値が許容外 = parse 失敗」と明示分離 |
| architect | medium | 旧形式無視と markdown セクション分割の相互作用が未定義 | **反映**: 解釈ルール 1 で「先頭の `---` ブロックを **セクション分割前に除去**」と順序を明示。`最終 nudge 日:` は key 抽出時に無視 |
| architect | medium | `ALLOWED_TOOLS=""` が広すぎる | **反映**: `ALLOWED_TOOLS="Read Bash(date:*)"` に明示。pattern が CLI で機能しない場合の fallback (Read Bash 全許可) は T01_setup で検証 |
| architect | low | 件数 N が総数か超過数か曖昧 | **反映**: `total_active` / `overflow_count` で変数名を分離 |
| contrarian | high | 既定ツール許可によりプロンプト注入に弱い | **反映**: §1.b インジェクション対策セクション新設、`ALLOWED_TOOLS` 最小化、T10_injection を追加 |
| contrarian | high | LLM 過剰設計で NOOP 抑制が非決定的 | **棄却（不変ルール優先）** + 軽減策（architect#3 と同じ） |
| contrarian | high | runner グローバル cwd 変更が広すぎる | **反映**（architect#1 と同じ方針転換） |
| contrarian | medium | テスト計画が手動目視に偏り境界条件の期待値が検証可能になっていない | **棄却（不変ルール優先）**: project_type=jobs で deterministic parser を採らない方針のため、自動 fixture test も不採用。ただし手動チェックリストの境界ケースを 4 件追加（T04_today, T04_8d, T05_invalid, T10_injection）して網羅性を強化 |
| contrarian | medium | parse 不能セクションの定義が曖昧 | **反映**（architect#4 と同じ） |
| contrarian | low | In-Scope の timer と成果物が一致していない | **反映**（architect#2 と同じ） |
| migration | high | 全ジョブ共通 cwd 変更の互換性検証が不足 | **反映**（architect#1 と同じ方針転換） |
| migration | high | 旧 frontmatter 形式の goals.md がサイレントに NOOP になる | **棄却**: hermes-lite では本 Issue まで `goals.md` 機能は **未着手**なので、旧 frontmatter-only goals.md は実環境に存在し得ない。Issue body に出てくる「frontmatter で書く」は提案段階の表現で、決定済み論点で「markdown 見出し方式」に確定済み。新規導入ファイルなのでサイレント NOOP のリスクはない。docs に「既存ファイルがある場合は上書きせず内容確認」を明記する点だけは採用 |
| migration | medium | `状態` 値の互換性が `active|achieved|paused` 限定 | **部分採用**: trim + lowercase 正規化は採用、許容値も `active|achieved|paused` のまま固定（`達成済み`, `done`, `pause` 等は parse 失敗扱い）。「無理に拡張せず、明示的に許容値を狭く保ち、外れは parse 失敗で気づかせる」方針が誤検知を防ぐ。T02_boundary を大小文字混在に拡張、T09_boundary の (c) に `状態: 達成済み` を追加 |
| migration | medium | 日付計算の境界条件が仕様化されていない | **反映**: §3 で D の場合分けを明文化（`D=0 → ⚡ + あと 0 日`, `0<D≤7 → ⚡`, `D>7 → badge なし`, `D<0 → ⚠️ + 期限超過`, 無効日付 → 期限不明）。T04_today, T04_8d, T05_invalid を追加 |
| migration | medium | 既存 goals.md 退避手順が運用移行手順になっていない | **反映**: `docs/jobs-goals-nudge.md` に「既存ファイルがある場合は上書きせず内容確認、新雛形は別ファイル名で配置してから手動マージ」を含めると実装対象に明記 |
| migration | low | NOOP exact match のテストが JSON result だけ | **反映**: T01 / T03_boundary の期待値を「raw `.result` 値が完全に 5 文字 `[NOOP]`、前後改行・空白・コードフェンス無し」に強化 + prompt 側にも明示 |

## 設計判断（棄却理由のまとめ）

「LLM 過剰設計、deterministic script に寄せろ」系の指摘は **CLAUDE.md 不変ルールに反するため棄却**。代わりにツール最小許可・インジェクション対策・出力 discipline で攻撃面を絞り、`SUPPRESS_RESULT_IF` の exact match 依存リスクを許容範囲に抑える。

---

## 3 周目 (design_loops=3, light max 到達 → 裁量で passed)

8 件 / 3 persona。`max_design_loops.light = 3` に到達したため、`ask_user_on_blocking: false` 設定下で **裁量で passed** とする。安全に関わる指摘 4 件を反映、4 件は方針判断として裁量残置。

### 反映（裁量 passed 前に修正）

| persona | severity | title | 反映 |
|---|---|---|---|
| migration | low | `[NOOP]` の文字数が「5 文字」と誤記 | 「6 文字（角括弧含む）」に訂正 |
| architect | medium | parse 失敗が active=0 のとき NOOP に潰される | §2 ステップ 5 に「`parse_failed_count == 0` も NOOP の条件に加える」と明文化。`parse_failed_count > 0 && total_active == 0` の挙動を §3 で「parse 失敗行だけの警告本文を Discord に投稿」と定義。T11_parse_only を追加 |
| contrarian | high | T10_injection のテスト期待値が「文字列含まない」と「備考そのまま」で矛盾 | T10_injection を「指示として実行されない」観点に書き換え（最終応答が `EXFIL_MARKER` 単独にならない、Bash tool で `date` 以外が呼ばれない、を期待値に） |
| contrarian + migration | high | `Bash(date:*)` 失敗時のフォールバック `Read Bash` がインジェクション対策を崩す | §2 から `Read Bash` への退避を削除。pattern が受理されない場合は別 pattern を試して、それでもダメなら **本 Issue を fail として中断**、runner 側 TODAY 注入は follow-up Issue 化、と明示 |
| migration | medium | 既存 `goals.md` の上書き防止が実装手順で曖昧 | 実装対象を `goals.md.example` 追加に変更。`goals.md` 本体は repo に含めず、ユーザーが手動でコピー編集する運用を In-Scope と「実装対象」に明記 |

### 裁量で残置（rejected, design_loops 上限）

| persona | severity | title | 残置理由 |
|---|---|---|---|
| architect | high | 未確証の `Bash(date:*)` を設計中核にしている | pattern の CLI 受理確認は実行でしかできない。失敗時は fail と扱う方針に変更したので、事前確証要求は実装試走で代替する。設計上の安全性は「fail で止まる」ことで担保 |
| architect | high | NOOP exact match を LLM 出力契約に依存している | hermes-lite 不変ルール（`claude -p` subprocess 経路）に基づく設計判断。runner 編集なしを維持する以上、出力 discipline を prompt 側で厳格化する以外に手段がない。`SUPPRESS_RESULT_IF` 不一致時のリスクは「`[NOOP]` でなかった場合 Discord に投稿される」だけで、安全上の致命傷ではない |
| architect / contrarian / migration | medium-high | 絶対パスのハードコード | `bin/run-claude.sh` は prompt をテンプレ展開せず `cat` してそのまま渡す仕様。`job.env` の `GOALS_MD_PATH` を prompt に埋め込むには runner 改修が必要で「runner 編集なし」方針と衝突する。docs に「gen8 以外では prompt 書き換え必要」を明示することで運用負債を可視化、follow-up Issue で runner 側の prompt 環境変数置換機構を別途検討 |
| architect / contrarian | medium-high | parser/formatter を LLM に集約する責務 | CLAUDE.md 不変ルールにより棄却済み |
| migration | high | 旧 frontmatter 内データ保持が silent NOOP に | hermes-lite では本 Issue まで `goals.md` 機能未着手のため、旧形式の実データは **存在し得ない**。Issue body の「frontmatter で書く」は提案表現であり、本 plan で新形式に確定。docs に「旧形式の goals.md があれば手動で新形式に書き換える」運用を記載することで対応する（移行スクリプトは作らない） |
| architect | low | `jobs/mail-watch/job.env` との対応表 | implementer が `docs/jobs-mail-watch.md` と `jobs/mail-watch/job.env` を直接参照すれば足りる。plan 本文に貼り出す価値が低い |
| contrarian | medium | 既存編集なしの場合の依存挙動 fallback 方針 | §5 の「依存している既存挙動の引用」で 3 点を明示済み。それぞれの fallback は「runner 側を編集しない」方針の通り、合致しなければ本 Issue を fail と扱う |

### 残置の commit message 反映

裁量で残した high 指摘 (3 件) は STEP 8 の commit message 本文に「Codex design blocking 3 件残置（NOOP exact match LLM 依存、絶対パスハードコード、旧 frontmatter silent NOOP）」と記す。

---

## Codex final review (codex_loops 5 周 = max 到達 → 裁量で passed)

5 周回して blocking が 9 → 7 → 6 → 8 → 8 と推移、収束しなかったため `max_codex_loops=5` を根拠に **裁量で final_review passed**。`ask_user_on_blocking: false` なので AskUserQuestion は出さない。

### 各周で対応した主な修正

| round | blocking | 主な反映 |
|---|---|---|
| 1 | 4 (architect/contrarian/migration が空 diff を指摘) | WIP commit を作って実装内容を diff に乗せた |
| 2 | 6 (scope 外変更、test-summary 破損誤検知、jq -r 改行、cp 順序) | scope 外 (CLAUDE.md, ROADMAP.md, .batch/.loop) を WIP commit から外す reset+restage、cp -n、jq -j、test-spec の退避タイムスタンプ、plan.md に `.gitignore` の `/goals.md` 例外を明示 |
| 3 | 8 (MAX_TURNS=5 残置、Bash pattern 緩める案残置、scope 外誤検知) | plan.md の `MAX_TURNS=5` を `20` に整合、`Bash(date:*)` 失敗時の `Read Bash` 緩和案を plan / test-spec / docs から削除し fail 中断方針に統一 |
| 4 | 8 (`[NOOP]` 5 文字誤記、codex-input Test summary 空) | plan.md の `5 文字` → `6 文字` 訂正、test-summary.json に `summary` トップレベルキー追加で codex-input.md の Test summary 欄を populate |
| 5 | 8 (収束せず、不変ルール由来 + diff truncation 由来の誤検知) | これ以上のループは効果見込み薄、`max_codex_loops` 到達で裁量 passed |

### 裁量で残置した high 指摘（commit message 本文 + follow-up Issue 検討対象）

1. **architect: 主要仕様が `user_manual_required` のまま `core_impl: passed` になっている**
   - 残置理由: 本ジョブは `bin/run-claude.sh` 経由で Discord に **実投稿** する経路（T02 / T04 / T05 / T07 / T08 / T09 / T10 / T11）が中心。事前ユーザー確認なしに Discord 投稿を行うのは CLAUDE.common.md「送信系操作の事前確認ルール」違反のため、自動試走では検証できない。test-spec.md に手動チェックリストとして整備済み、ユーザーが webhook を本物に差し替えた後で実施する想定。
2. **architect / contrarian: `Bash(date:*)` を安全境界にしているが shell injection 面の契約が曖昧**
   - 残置理由: Step C 試走で `permission_denials=[]` を確認済み（`date -d "<無効値>"` も通る）。Bash の引数評価は claude CLI 側 sandbox に依存し、本 Issue 範囲では追加の入力 sanitize はしない。万一 sandbox がない / 破られる場合は follow-up Issue で job 専用 wrapper / deterministic な date 渡しを検討。
3. **architect / contrarian / migration: 絶対パス `/home/shohei/プロジェクト/hermes-lite/goals.md` の prompt ハードコード**
   - 残置理由（design loop で既に判断済み）: `bin/run-claude.sh` が prompt をテンプレ展開しない仕様のため、job.env から prompt への変数注入には runner 改修が要る。本 Issue は runner 編集なし方針 → docs に既知制約として明記。follow-up Issue で runner 側の `${VAR}` 置換機構を検討するのが筋。
4. **contrarian: 失敗 verdict のレビュー成果物をコミットしている**
   - 残置理由: gloop 設計上、Codex の各周 verdict は `features/<n-slug>/codex-*.yaml` として記録する仕様（後段の loop 集計や次サイクルでの参照のため）。これは本 Issue 固有の問題ではない。
5. **contrarian / migration: feature diff にレビュー / loop メタデータが大量に含まれる / Non-Goals 違反**
   - 残置理由: 上記 4 と同じ。gloop の運用上 features/ 配下にレビュー履歴を残す設計。本 Issue で変更する話ではない。
6. **migration: gen8 固定の絶対パスが別 checkout で誤った goals.md を読む**
   - 残置理由: 上記 3 と同じ。docs 内のすべてのコマンド・パスを `/home/shohei/プロジェクト/hermes-lite` に揃えてある（`HERMES_DIR=…` 変数として冒頭で固定）。別 checkout で動かす場合の prompt 書き換え注意も docs に明記済み。
7. **migration: state.json が diff truncate で完結していないように見える**
   - 残置理由: 実ファイルは valid（`jq -e . features/4-.../state.json` で確認可能）。Codex 側の 60kB diff truncation が原因の誤検知。
8. **migration: 旧 frontmatter 形式 / 既存 goals.md の退避が弱い** (medium)
   - 残置理由: 旧形式 goals.md は hermes-lite では本 Issue まで未着手機能のため実環境に存在しない（design loop で既判断済み）。退避は `cp -p ...bak.$(date +...)` のタイムスタンプ付きに修正済み。
9. **NOOP exact match の既知リスク**
   - 残置理由: design loop で既判断済み。`bin/run-claude.sh` の `RESULT_TEXT == "$SUPPRESS_RESULT_IF"` の bash exact match に依存。runner 編集なし方針のため受容、prompt 側の出力 discipline で緩和。

### Codex final review 5 周のまとめ

- 採用済み修正: 計 8 件（design loop 上限ですでに採用したものを含めず、final loop で新たに反映したもの）
- 裁量残置: 9 件（うち high 6 件、medium 3 件）
- 残置理由は (a) hermes-lite 不変ルール (claude -p subprocess 経路、runner 編集なし)、(b) gloop 運用上の仕様（features/ 配下のレビュー履歴）、(c) Codex の diff truncation 由来の誤検知、(d) 「Discord 実投稿を伴う試走はユーザー手動」の安全方針、の 4 カテゴリ。
- いずれも本 Issue で対応すべき bug ではなく、運用負債として可視化済み。重要な high 2-3 件は follow-up Issue として検討。

