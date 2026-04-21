"""
eval/tau2_harness.py

Wraps tau2-bench retail domain. Every run writes to:
  - eval/score_log.json   (pass@1, CI, cost, latency per run)
  - eval/trace_log.jsonl  (one line per conversation turn)
"""
import sys
import os
import json
import time
import uuid
import statistics
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# ── Tell LiteLLM to use OpenRouter ────────────────────────────────────
os.environ["OPENAI_API_KEY"]  = os.getenv("OPENROUTER_API_KEY", "")
os.environ["OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"

# ── Point Python at tau2-bench src ───────────────────────────────────
TAU2_SRC = Path(__file__).parent.parent / "tau2-bench" / "src"
sys.path.insert(0, str(TAU2_SRC))

from tau2.run import run_domain, get_tasks
from tau2.data_model.simulation import TextRunConfig

# ── Output paths ──────────────────────────────────────────────────────
EVAL_DIR  = Path(__file__).parent
SCORE_LOG = EVAL_DIR / "score_log.json"
TRACE_LOG = EVAL_DIR / "trace_log.jsonl"

# ── Model settings ────────────────────────────────────────────────────
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
DEV_MODEL      = "openai/gpt-4o-mini"


def compute_ci_95(scores: list) -> tuple:
    """95% confidence interval for binary pass/fail scores."""
    n = len(scores)
    if n < 2:
        return (0.0, 1.0)
    mean   = statistics.mean(scores)
    stdev  = statistics.stdev(scores)
    margin = 1.96 * (stdev / (n ** 0.5))
    return (round(max(0.0, mean - margin), 4),
            round(min(1.0, mean + margin), 4))


def append_trace(run_id, task_id, turn, role, content, cost_usd=0.0):
    """Write one conversation turn to trace_log.jsonl."""
    entry = {
        "trace_id":  str(uuid.uuid4()),
        "run_id":    run_id,
        "task_id":   str(task_id),
        "turn":      turn,
        "role":      role,
        "content":   str(content)[:300],
        "cost_usd":  round(cost_usd, 6),
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(TRACE_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def update_score_log(entry: dict):
    """Append one run entry to score_log.json."""
    entries = []
    if SCORE_LOG.exists():
        try:
            entries = json.loads(SCORE_LOG.read_text(encoding="utf-8"))
            if not isinstance(entries, list):
                entries = []
        except Exception:
            entries = []
    entries.append(entry)
    SCORE_LOG.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def run_baseline(num_tasks: int = 3,
                 model: str = DEV_MODEL,
                 slice_name: str = "dev") -> dict:
    """
    Run tau2-bench retail domain on a limited number of tasks.
    Records results to score_log.json and trace_log.jsonl.
    """
    if not OPENROUTER_KEY:
        print("ERROR: OPENROUTER_API_KEY not found in .env")
        return {}

    run_id = f"run_{slice_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print(f"\n{'='*52}")
    print(f"  tau2-Bench Retail Domain")
    print(f"{'='*52}")
    print(f"  Run ID : {run_id}")
    print(f"  Model  : {model}")
    print(f"  Tasks  : {num_tasks}")
    print(f"  Slice  : {slice_name}")
    print(f"{'='*52}\n")

    # ── Load and slice tasks ───────────────────────────────────────────
    # get_tasks returns all 114 retail tasks.
    # We slice to exactly num_tasks to control cost.
    # At ~$0.06 per task, 3 tasks = ~$0.18, 30 tasks = ~$1.80
    all_tasks     = get_tasks("retail")
    limited_tasks = all_tasks[:num_tasks]
    print(f"  Loaded {len(all_tasks)} total tasks")
    print(f"  Running {len(limited_tasks)} tasks\n")

    config = TextRunConfig(
        domain = "retail",
        agent  = "llm_agent",
        model  = model,
    )

    start_time = time.time()

    # Pass task_ids directly — this is how tau2 v1.0 limits tasks
    task_ids = [getattr(t, "task_id", i) for i, t in enumerate(limited_tasks)]
    print(f"  Task IDs to run: {task_ids}")

    try:
        results = run_domain(config, task_ids=task_ids)
    except TypeError:
    # Final fallback — use environment variable
        print("WARNING: Falling back to full domain run")
        results = run_domain(config)

    wall_time = time.time() - start_time

    # ── Parse results ──────────────────────────────────────────────────
    scores    = []
    costs     = []
    latencies = []
    sim_runs  = getattr(results, "simulation_runs", []) or []

    for i, sim_run in enumerate(sim_runs):
        reward  = float(getattr(sim_run, "reward", 0) or 0)
        passed  = reward >= 1.0
        scores.append(1 if passed else 0)

        task_id = getattr(sim_run, "task_id",          f"task_{i+1}")
        cost    = float(getattr(sim_run, "cost",        0.0) or 0.0)
        latency = float(getattr(sim_run, "wall_time_seconds", 0.0) or 0.0)
        costs.append(cost)
        latencies.append(latency)

        turns        = getattr(sim_run, "turns", []) or []
        per_turn_cost = cost / max(len(turns), 1)
        for j, turn in enumerate(turns):
            role    = getattr(turn, "role",    "unknown")
            content = getattr(turn, "content", "")
            append_trace(run_id, task_id, j, role, content, per_turn_cost)

        status = "PASS" if passed else "FAIL"
        print(f"  Task {i+1:2d}/{len(sim_runs)} "
              f"[{task_id}]: {status}  "
              f"(cost ${cost:.4f}, {latency:.1f}s)")

    if not scores:
        print("\nWARNING: No results returned.")
        return {}

    # ── Compute metrics ────────────────────────────────────────────────
    pass_at_1    = round(statistics.mean(scores), 4)
    ci_lo, ci_hi = compute_ci_95(scores)
    total_cost   = round(sum(costs), 6)
    sorted_lat   = sorted(latencies)
    p50 = round(sorted_lat[len(sorted_lat) // 2], 2) if latencies else 0.0
    p95 = round(sorted_lat[int(len(sorted_lat) * 0.95)], 2) if latencies else 0.0

    entry = {
        "run_id":        run_id,
        "model":         model,
        "domain":        "retail",
        "slice":         slice_name,
        "num_tasks":     len(scores),
        "pass_at_1":     pass_at_1,
        "ci_95_lower":   ci_lo,
        "ci_95_upper":   ci_hi,
        "cost_usd":      total_cost,
        "p50_latency_s": p50,
        "p95_latency_s": p95,
        "wall_time_s":   round(wall_time, 2),
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }

    update_score_log(entry)

    print(f"\n{'='*52}")
    print(f"  Results")
    print(f"{'='*52}")
    print(f"  pass@1     : {pass_at_1}  ({sum(scores)}/{len(scores)})")
    print(f"  95% CI     : [{ci_lo}, {ci_hi}]")
    print(f"  Cost       : ${total_cost}")
    print(f"  p50/p95    : {p50}s / {p95}s")
    print(f"  Wall time  : {wall_time:.1f}s")
    print(f"{'='*52}")
    print(f"\n  Score log  : {SCORE_LOG}")
    print(f"  Trace log  : {TRACE_LOG}\n")

    return entry


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="tau2-bench harness for Conversion Engine"
    )
    parser.add_argument(
        "--tasks",
        type    = int,
        default = 3,
        help    = "Number of tasks to run (3=smoke, 30=full baseline)"
    )
    parser.add_argument(
        "--model",
        type    = str,
        default = DEV_MODEL,
        help    = "Model via OpenRouter (default: openai/gpt-4o-mini)"
    )
    parser.add_argument(
        "--slice",
        type    = str,
        default = "dev",
        choices = ["dev", "held_out"],
        help    = "Slice name for score_log"
    )
    args = parser.parse_args()

    run_baseline(
        num_tasks  = args.tasks,
        model      = args.model,
        slice_name = args.slice,
    )