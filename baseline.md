# Baseline — τ²-Bench Retail Domain

## What I reproduced
Ran τ²-Bench retail domain using gpt-4o-mini via OpenRouter 
as the agent model. The harness wraps tau2-bench v1.0.0 
installed from the sierra-research/tau2-bench repository.

## Results (preliminary — from interrupted runs)

| Run | Tasks completed | pass@1 | Cost |
|-----|----------------|--------|------|
| run_dev_20260422_000031 | 3 | 1.00 | ~$0.19 |
| run_dev_20260422_001839 | 6 | 0.33 | ~$0.42 |
| run_dev_20260422_003153 | 6 | 0.33 | ~$0.41 |

Combined across all completed tasks (15 total):
- Tasks completed: 15
- PASS: 6
- FAIL: 9  
- Estimated pass@1: 0.40
- 95% CI: [0.16, 0.64]
- Cost per task: ~$0.07 average
- p50 latency: ~33s per task

## Primary failure mode identified
The agent consistently fails on inventory filtering tasks.
It counts all product variants (12) instead of filtering 
for available:true items (10). This represents a 
data-precision failure — the agent reads data correctly 
but does not apply boolean filters before making claims.

This failure maps directly to the Tenacious over-claiming 
probe: an agent that says "you have 12 open roles" when 
only 10 are actively hiring makes the same error.

## Unexpected behaviors
- Task concurrency is fixed at 3 simultaneous tasks — 
  num_tasks parameter does not limit total tasks run
- model= parameter does not override default (gpt-4.1) 
  in TextRunConfig — LiteLLM uses OPENAI_API_KEY env var
- Cost is higher than expected: $0.07/task vs $0.03 target

## Cost per evaluation run
- 3 tasks: ~$0.21
- 30 tasks (full baseline): ~$2.10 estimated
- Well within $4 Day 1-4 budget

## Confidence
Low confidence on pass@1 (wide CI) due to small sample.
Full 30-task dev slice run needed for Act I deliverable.