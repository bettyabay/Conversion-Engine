"""
eval/tau2_harness.py
Runs tau2-bench retail domain and writes:
  - eval/score_log.json
  - eval/trace_log.jsonl
"""
import sys, os, json, time, statistics
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── OpenRouter setup ────────────────────────────────────────
os.environ["OPENAI_API_KEY"]  = os.getenv("OPENROUTER_API_KEY", "")
os.environ["OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"

# ── Point Python at tau2-bench src ──────────────────────────
TAU2_SRC = Path(__file__).parent.parent / "tau2-bench" / "src"
sys.path.insert(0, str(TAU2_SRC))

from tau2.runner.batch import run_domain
from tau2.data_model.simulation import TextRunConfig

# ── Paths ────────────────────────────────────────────────────
EVAL_DIR  = Path(__file__).parent
SCORE_LOG = EVAL_DIR / "score_log.json"
TRACE_LOG = EVAL_DIR / "trace_log.jsonl"

# ── Model ────────────────────────────────────────────────────
MODEL = os.getenv("TAU2_MODEL", "deepseek/deepseek-v3")

# ── Helpers ──────────────────────────────────────────────────
def compute_ci_95(scores):
    n = len(scores)
    if n < 2:
        return (0.0, 1.0)
    mean   = statistics.mean(scores)
    stdev  = statistics.stdev(scores)
    margin = 1.96 * (stdev / (n ** 0.5))
    return (
        round(max(0.0, mean - margin), 4),
        round(min(1.0, mean + margin), 4)
    )

def append_trace(run_id, task_id, turn, role, content, cost_usd=0.0):
    entry = {
        "trace_id":  f"{run_id}_{task_id}_{turn}",
        "run_id":    run_id,
        "task_id":   str(task_id),
        "turn":      turn,
        "role":      role,
        "content":   str(content)[:500],
        "cost_usd":  round(cost_usd, 6),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(TRACE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def load_score_log():
    if SCORE_LOG.exists() and SCORE_LOG.stat().st_size > 2:
        with open(SCORE_LOG) as f:
            data = json.load(f)
            return data if isinstance(data, list) else [data]
    return []

def save_score_log(entries):
    with open(SCORE_LOG, "w") as f:
        json.dump(entries, f, indent=2)

# ── Main ─────────────────────────────────────────────────────
def run_baseline(num_tasks=30, run_label="baseline_dev"):
    run_id = f"{run_label}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    start  = time.time()

    print(f"\n{'='*55}")
    print(f"  τ²-Bench Baseline Run")
    print(f"  Run ID  : {run_id}")
    print(f"  Model   : {MODEL}")
    print(f"  Tasks   : {num_tasks}")
    print(f"  Est.cost: ~${0.014 * num_tasks:.2f}")
    print(f"{'='*55}\n")

    # ── Build config — everything in one object ──────────────
    config = TextRunConfig(
        domain          = "retail",
        num_tasks       = num_tasks,
        llm_agent       = MODEL,
        num_trials      = 1,
        max_concurrency = 3,
        seed            = 300,
        log_level       = "ERROR",
    )

    print(f"Running retail domain with {MODEL}...")
    results = run_domain(config)

    # ── Parse results ────────────────────────────────────────
    scores     = []
    total_cost = 0.0

    # Get simulations from results object
    simulations = []
    if hasattr(results, "simulations"):
        simulations = results.simulations
    elif isinstance(results, dict):
        simulations = results.get("simulations", [])
    elif isinstance(results, list):
        simulations = results

    print(f"\nSimulations completed: {len(simulations)}")
    print(f"{'─'*55}")

    for i, sim in enumerate(simulations):
        # Extract reward
        reward = None
        if hasattr(sim, "reward"):
            reward = sim.reward
        elif isinstance(sim, dict):
            reward = sim.get("reward", sim.get("score"))

        passed  = 1 if (reward is not None and float(reward) >= 1.0) else 0
        scores.append(passed)

        # Extract task_id
        task_id = (
            getattr(sim, "task_id", None) or
            (sim.get("task_id") if isinstance(sim, dict) else None) or
            f"task_{i:03d}"
        )

        # Extract messages for trace log
        messages = (
            getattr(sim, "messages", None) or
            (sim.get("messages", sim.get("turns", [])) if isinstance(sim, dict) else [])
        )

        cost_per_turn = 0.014 / max(len(messages), 1)
        for turn_idx, msg in enumerate(messages):
            role = (
                getattr(msg, "role", None) or
                (msg.get("role", "unknown") if isinstance(msg, dict) else "unknown")
            )
            content = (
                getattr(msg, "content", None) or
                (msg.get("content", "") if isinstance(msg, dict) else str(msg))
            )
            append_trace(run_id, task_id, turn_idx, role, content, cost_per_turn)

        total_cost += 0.014
        status = "PASS ✓" if passed else "FAIL ✗"
        print(f"  Task {i+1:02d} | {str(task_id):<15} | reward={reward} | {status}")

    # ── Statistics ───────────────────────────────────────────
    wall_time = time.time() - start
    pass_at_1 = round(statistics.mean(scores), 4) if scores else 0.0
    ci_lower, ci_upper = compute_ci_95(scores)

    print(f"\n{'='*55}")
    print(f"  RESULTS")
    print(f"  Tasks   : {len(scores)}")
    print(f"  PASS    : {sum(scores)}")
    print(f"  FAIL    : {len(scores) - sum(scores)}")
    print(f"  pass@1  : {pass_at_1}")
    print(f"  95% CI  : [{ci_lower}, {ci_upper}]")
    print(f"  Cost    : ${total_cost:.4f}")
    print(f"  Time    : {wall_time:.1f}s")
    print(f"{'='*55}\n")

    # ── Write score_log.json ─────────────────────────────────
    entry = {
        "run_id":         run_id,
        "model":          MODEL,
        "domain":         "retail",
        "slice":          "dev",
        "num_tasks":      len(scores),
        "pass_at_1":      pass_at_1,
        "ci_95_lower":    ci_lower,
        "ci_95_upper":    ci_upper,
        "passes":         sum(scores),
        "failures":       len(scores) - sum(scores),
        "total_cost_usd": round(total_cost, 4),
        "cost_per_task":  round(total_cost / max(len(scores), 1), 4),
        "wall_time_s":    round(wall_time, 1),
        "timestamp":      datetime.now(timezone.utc).isoformat(),
        "raw_scores":     scores,
    }

    existing = load_score_log()
    existing.append(entry)
    save_score_log(existing)

    # Count trace lines
    trace_lines = sum(1 for _ in open(TRACE_LOG, encoding="utf-8")) if TRACE_LOG.exists() else 0

    print(f"score_log.json  → {len(existing)} entries written")
    print(f"trace_log.jsonl → {trace_lines} turns logged")
    print(f"Run ID          : {run_id}")

    return entry


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=int, default=30)
    parser.add_argument("--label", type=str, default="baseline_dev")
    args = parser.parse_args()
    run_baseline(num_tasks=args.tasks, run_label=args.label)