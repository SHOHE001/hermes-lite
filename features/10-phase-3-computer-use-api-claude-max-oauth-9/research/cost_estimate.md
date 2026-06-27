# Approach C: Computer Use コスト試算（実機なし）

**概算オーダー、誤差 10x 想定、確度: 低、実機なし**。本試算は #9 着手判断の桁感確認用。

## 取得元 URL（probe.sh pricing で curl）

- https://www.anthropic.com/pricing
- https://docs.claude.com/en/docs/about-claude/models/overview

## 仮定（全部明示）

| 変数 | 値 |
|---|---|
| model | claude-sonnet-4-5 |
| input 単価 | $3.00 / MTok（pricing ページから取得、変動あり） |
| output 単価 | $15.00 / MTok（同上） |
| cache_creation 単価 | $3.75 / MTok（×1.25） |
| cache_read 単価 | $0.30 / MTok（×0.10） |
| 1 step あたり screenshot input tokens | 1500 ± 5x（1280×800 PNG、公式式不明時は仮置き） |
| 1 step あたり assistant 応答 tokens | 200 ± 3x |
| 1 セッション step 数 | {25, 50, 100} の 3 ケース |
| cache hit 率 | {0%, 50%, 90%} の 3 ケース |
| sessions/月 | {30, 300} の 2 ケース |

## 計算式

```
session_cost = step * ((image_tokens * (1 - cache_hit) + image_tokens * cache_hit * (cache_read / input))
                       * input_price
                       + assistant_tokens * output_price) / 1_000_000
monthly_cost = session_cost * sessions_per_month
```

## 感度分析（概算 USD、桁感のみ）

### sessions/月 = 30

| step | cache_hit | 概算 USD/月 |
|---:|---:|---:|
| 25 | 0% | $4 |
| 25 | 50% | $2 |
| 25 | 90% | $1 |
| 50 | 0% | $8 |
| 50 | 50% | $4 |
| 50 | 90% | $1 |
| 100 | 0% | $15 |
| 100 | 50% | $8 |
| 100 | 90% | $2 |

### sessions/月 = 300

| step | cache_hit | 概算 USD/月 |
|---:|---:|---:|
| 25 | 0% | $40 |
| 25 | 50% | $20 |
| 25 | 90% | $5 |
| 50 | 0% | $80 |
| 50 | 50% | $40 |
| 50 | 90% | $10 |
| 100 | 0% | $150 |
| 100 | 50% | $80 |
| 100 | 90% | $20 |

## 含意（#9 着手判断）

- light 利用（30 セッション/月、低 step）なら **数 USD/月レンジ**。Max subscription quota 内に十分収まる可能性高い。
- heavy 利用（300 セッション/月、100 step）なら **3 桁 USD/月レンジ**。API key 経路に切替必要。
- 実数の前提（image token 数、cache hit 率）は実機計測で大幅に変わる可能性あり。**10x の精度** であることに留意。

## 制約

- 実機 API key 経路は本 Issue Out-of-Scope。本試算は pricing ページから取得した単価 × 仮定 step/session 数の桁感のみ。
- Anthropic 側 pricing 変更（特に Computer Use 専用枠の新設や image token 算出式変更）で 10x オーダーで変動し得る。
- **本試算を SLA / 予算根拠に使ってはいけない**。
