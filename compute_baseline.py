import json, statistics
from pathlib import Path

with open("eval/score_log.json") as f:
    runs = json.load(f)

# Use only the 3 complete 30-task runs
complete = [r for r in runs if r["num_tasks"] == 30]
scores = [r["pass_at_1"] for r in complete]

mean = statistics.mean(scores)
stdev = statistics.stdev(scores)
margin = 1.96 * (stdev / (len(scores) ** 0.5))
ci_lower = round(max(0.0, mean - margin), 4)
ci_upper = round(min(1.0, mean + margin), 4)

print(f"Complete trials: {len(complete)}")
print(f"Individual scores: {scores}")
print(f"Mean pass@1: {round(mean, 4)}")
print(f"95% CI: [{ci_lower}, {ci_upper}]")
print(f"Total cost: ${sum(r['total_cost_usd'] for r in complete):.4f}")