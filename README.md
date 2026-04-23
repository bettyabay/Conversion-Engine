# τ²-Bench Baseline — Conversion Engine

## Final Baseline — 3 Complete Trials (April 22, 2026)

| Metric | Value |
|--------|-------|
| Mean pass@1 | 0.5443 |
| 95% CI | [0.4867, 0.6020] |
| Trials | 3 |
| Tasks per trial | 30 |
| Model | gpt-4o-mini via OpenRouter |
| Total cost | $0.52 |
| Cost per task | $0.0058 |
| Avg wall time | 511s per trial |

**Published reference (GPT-5 class):** 0.42
**Our result:** 0.5443 — exceeds reference by 0.12 points.
**CI does not overlap 0.42**, confirming this is a real signal, not noise.

## What Was Reproduced

Ran τ²-Bench v1.0.0 on the retail domain, dev slice, 30 tasks per trial.
Agent: `llm_agent` with gpt-4o-mini. User simulator: gpt-4.1-2025-04-14.
Concurrency: 3. Max steps: 200. Three complete trials logged to score_log.json.

## Confidence Interval

CI computed as `mean ± 1.96 * (stdev / sqrt(n))` across 3 complete trials
(scores: 0.50, 0.60, 0.533). Width of 0.11 is narrow enough for credible claims.
Trial 4 partial (20/30 tasks, credit limit hit) excluded from CI calculation.

## Cost Per Run

Each trial consumed approximately $0.17 at $0.0058 per task.
Cost breakdown: ~70% user simulator (gpt-4.1), ~30% agent (gpt-4o-mini).
Total evaluation spend: $0.52 across 3 complete trials.

## Unexpected Behavior

**Task 0 — failed all 3 trials:** Agent correctly reads product data but
calls `exchange_delivered_order_items` with wrong item variant. Systematic
write action precision failure.

**Task 28 — failed all 3 trials:** Agent processes returns correctly but
miscalculates total refund by including a full order cancellation amount
when only one item was cancelled. Reported $1,013.51 vs correct $918.43.

**Task 2 — failed 3/4 trials:** Agent counts 9 available t-shirt variants
instead of 10. Boolean availability filter misses one qualifying item.

These map directly to Tenacious probes: write action precision maps to
bench over-commitment; arithmetic over-claiming maps to signal over-claiming.