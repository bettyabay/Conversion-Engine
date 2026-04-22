## Final Result — 30-task run (April 22, 2026)

| Metric | Value |
|--------|-------|
| pass@1 | 0.50 |
| 95% CI | [0.32, 0.68] |
| Tasks | 30 |
| Model | gpt-4o-mini via OpenRouter |
| Cost | $0.17 total / $0.0058 per task |
| Wall time | 537.5s |

**vs published reference:** 0.42 (GPT-5 class)
**Our result:** 0.50 — exceeds published reference on cheaper model.

## Primary failure modes identified

1. Write action precision — agent reads correctly but executes wrong write
   action (returns wrong item, exchanges wrong variant)
2. Arithmetic over-claiming — agent miscalculates totals
   (Task 16: said $8,278.23 instead of $8,276.23)
3. Multi-item filtering — agent misses second item in multi-product orders
4. Too-many-errors termination — Task 23 hit max error limit

## Tenacious mapping
The write action failure maps directly to bench over-commitment:
agent confirms capacity it cannot deliver.
The arithmetic failure maps to signal over-claiming:
agent states a number it did not verify precisely.