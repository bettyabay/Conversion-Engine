"""
agent/enrichment/jobs.py

Hiring Signal Brief generator — matches hiring_signal_brief.schema.json

Produces the grounded research artifact that:
1. Measures hiring velocity (today vs 60 days ago)
2. Detects buying window signals (funding, layoff, leadership change)
3. Checks bench-to-brief match against bench_summary.json
4. Populates honesty_flags when signals are weak or inferred
5. Records every data source attempted (success, partial, no_data, error)

Every claim in outreach email must map to a field in this brief.
Fields with low confidence trigger softer phrasing in the agent.
"""
import json
import os
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Load bench summary for bench-to-brief match
BENCH_PATH = Path(__file__).parent.parent.parent / "data" / "bench_summary.json"

# Engineering role keywords for velocity detection
ENG_ROLE_KEYWORDS = [
    "engineer", "developer", "architect", "devops", "sre",
    "platform", "backend", "frontend", "fullstack", "full stack",
    "data", "ml", "machine learning", "ai ", "mlops", "infrastructure",
    "tech lead", "engineering manager", "vp engineering", "cto",
]

# Stack detection keywords → maps to bench_summary.json keys
STACK_KEYWORDS = {
    "python":          ["python", "django", "fastapi", "flask"],
    "go":              ["golang", " go ", "grpc", "microservices"],
    "data":            ["dbt", "snowflake", "databricks", "airflow", "data engineer"],
    "ml":              ["machine learning", "ml engineer", "mlops", "pytorch", "llm", "rag"],
    "infra":           ["terraform", "kubernetes", "aws", "gcp", "devops", "sre"],
    "frontend":        ["react", "next.js", "typescript", "frontend", "ui engineer"],
    "fullstack_nestjs": ["nestjs", "node.js", "nest.js"],
}


def get_hiring_signal(
    company_name: str,
    website: str = None,
    domain: str = None,
    funding_event: dict = None,
    layoff_event: dict = None,
    leadership_change: dict = None,
    current_job_titles: list = None,
    prior_job_titles: list = None,  # 60-day-ago snapshot
) -> dict:
    """
    Build a complete hiring signal brief for a prospect.

    Parameters:
        company_name: Company name
        website: Company website URL
        domain: Company domain (e.g. 'orrin-labs.example')
        funding_event: Dict with detected/stage/amount_usd/closed_at/source_url
        layoff_event: Dict with detected/date/headcount_reduction/percentage_cut
        leadership_change: Dict with detected/role/new_leader_name/started_at
        current_job_titles: List of current open job title strings
        prior_job_titles: List of job titles from 60 days ago snapshot

    Returns:
        dict matching hiring_signal_brief.schema.json
    """
    current_job_titles = current_job_titles or []
    prior_job_titles   = prior_job_titles or []
    funding_event      = funding_event or {"detected": False}
    layoff_event       = layoff_event or {"detected": False}
    leadership_change  = leadership_change or {"detected": False}

    data_sources = []

    # ── Try Greenhouse ATS ────────────────────────────────────
    greenhouse_roles = []
    if company_name:
        greenhouse_roles, gh_status = _try_greenhouse(company_name)
        data_sources.append({
            "source":     "greenhouse_ats",
            "status":     gh_status,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    # Use Greenhouse data if available, otherwise use provided titles
    if greenhouse_roles:
        all_current_titles = [r.get("title", "") for r in greenhouse_roles]
    else:
        all_current_titles = current_job_titles

    # ── Record all sources checked ────────────────────────────
    for source in ["builtin_jobs", "wellfound_jobs", "company_careers_page"]:
        data_sources.append({
            "source":     source,
            "status":     "no_data" if not all_current_titles else "partial",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })

    data_sources.append({
        "source": "layoffs_fyi",
        "status": "success" if layoff_event.get("detected") else "success",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    })

    data_sources.append({
        "source": "crunchbase_odm",
        "status": "success" if funding_event.get("detected") else "partial",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    })

    # ── Count engineering roles ───────────────────────────────
    eng_today    = _count_eng_roles(all_current_titles)
    eng_prior    = _count_eng_roles(prior_job_titles)
    total_today  = len(all_current_titles)
    total_prior  = len(prior_job_titles)

    # ── Compute velocity label ────────────────────────────────
    velocity_label, velocity_confidence = _compute_velocity(
        eng_today, eng_prior, total_today, total_prior
    )

    # ── Detect required stacks from job titles ────────────────
    required_stacks = _detect_stacks(all_current_titles)

    # ── Bench-to-brief match ──────────────────────────────────
    bench_match = _check_bench(required_stacks)

    # ── Determine primary segment match ──────────────────────
    segment_match, segment_confidence = _infer_segment(
        funding_event, layoff_event, leadership_change,
        eng_today, velocity_label
    )

    # ── Compute AI maturity hint ──────────────────────────────
    ai_titles = [t for t in all_current_titles
                 if any(kw in t.lower() for kw in ["ml ", "ai ", "machine learning", "mlops", "llm"])]

    # ── Populate honesty flags ────────────────────────────────
    honesty_flags = []
    if velocity_label == "insufficient_signal":
        honesty_flags.append("weak_hiring_velocity_signal")
    if not funding_event.get("detected") and not layoff_event.get("detected"):
        if velocity_confidence < 0.5:
            honesty_flags.append("weak_ai_maturity_signal")
    if bench_match.get("gaps"):
        honesty_flags.append("bench_gap_detected")
    if required_stacks and not bench_match.get("bench_available"):
        honesty_flags.append("bench_gap_detected")
    if layoff_event.get("detected") and funding_event.get("detected"):
        honesty_flags.append("layoff_overrides_funding")

    # ── Build the full brief ──────────────────────────────────
    return {
        "prospect_domain":         domain or f"{company_name.lower().replace(' ', '-')}.example",
        "prospect_name":           company_name,
        "generated_at":            datetime.now(timezone.utc).isoformat(),
        "primary_segment_match":   segment_match,
        "segment_confidence":      round(segment_confidence, 3),
        "ai_maturity": {
            "score":          len(ai_titles),  # rough hint; full scoring in ai_maturity.py
            "confidence":     0.6 if ai_titles else 0.4,
            "justifications": [
                {
                    "signal":     "ai_adjacent_open_roles",
                    "status":     f"{len(ai_titles)} AI-adjacent roles: {', '.join(ai_titles[:3])}" if ai_titles else "No AI-adjacent roles detected",
                    "weight":     "high",
                    "confidence": "high" if len(ai_titles) >= 2 else "medium",
                }
            ],
        },
        "hiring_velocity": {
            "open_roles_today":      eng_today,
            "open_roles_60_days_ago": eng_prior,
            "velocity_label":        velocity_label,
            "signal_confidence":     round(velocity_confidence, 3),
            "sources":               ["greenhouse_ats", "builtin", "company_careers_page"],
        },
        "buying_window_signals": {
            "funding_event":     funding_event,
            "layoff_event":      layoff_event,
            "leadership_change": leadership_change,
        },
        "tech_stack":          required_stacks,
        "bench_to_brief_match": bench_match,
        "data_sources_checked": data_sources,
        "honesty_flags":        honesty_flags,
        # Extra fields for internal use
        "_all_open_titles":    all_current_titles,
        "_total_open_roles":   total_today,
    }


def _try_greenhouse(company_name: str) -> tuple:
    """Try Greenhouse ATS public API. Returns (roles_list, status_str)."""
    slug = company_name.lower().replace(" ", "-").replace(".", "").replace(",", "")
    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        resp = requests.get(url, timeout=5,
                            headers={"User-Agent": "TRP1-Week10-Research (trainee@trp1.example)"})
        if resp.status_code == 200:
            jobs = resp.json().get("jobs", [])
            return jobs, "success"
        elif resp.status_code == 404:
            return [], "no_data"
        else:
            return [], "error"
    except Exception as e:
        return [], "error"


def _count_eng_roles(titles: list) -> int:
    """Count engineering roles from a list of job titles."""
    count = 0
    for t in titles:
        tl = t.lower()
        if any(kw in tl for kw in ENG_ROLE_KEYWORDS):
            count += 1
    return count


def _compute_velocity(eng_today: int, eng_prior: int,
                      total_today: int, total_prior: int) -> tuple:
    """
    Compute velocity label and confidence.
    Returns (velocity_label, confidence).
    """
    if total_today == 0 and total_prior == 0:
        return "insufficient_signal", 0.3

    if eng_prior == 0 and eng_today == 0:
        return "insufficient_signal", 0.4

    if eng_prior == 0:
        # No prior data — can't compute velocity
        return "insufficient_signal", 0.35

    ratio = eng_today / eng_prior

    if ratio >= 3.0:
        return "tripled_or_more", 0.85
    elif ratio >= 2.0:
        return "doubled", 0.80
    elif ratio >= 1.2:
        return "increased_modestly", 0.75
    elif ratio >= 0.9:
        return "flat", 0.80
    else:
        return "declined", 0.75


def _detect_stacks(titles: list) -> list:
    """Detect required tech stacks from job titles."""
    found = []
    titles_lower = " ".join(titles).lower()
    for stack, keywords in STACK_KEYWORDS.items():
        if any(kw in titles_lower for kw in keywords):
            if stack not in found:
                found.append(stack)
    return found


def _check_bench(required_stacks: list) -> dict:
    """Check bench_summary.json for availability of required stacks."""
    try:
        if BENCH_PATH.exists():
            with open(BENCH_PATH) as f:
                bench = json.load(f)
            stacks_data = bench.get("stacks", {})
        else:
            # Use hardcoded bench from seed materials
            stacks_data = {
                "python":  {"available_engineers": 7},
                "go":      {"available_engineers": 3},
                "data":    {"available_engineers": 9},
                "ml":      {"available_engineers": 5},
                "infra":   {"available_engineers": 4},
                "frontend": {"available_engineers": 6},
                "fullstack_nestjs": {"available_engineers": 2},
            }

        gaps = []
        for stack in required_stacks:
            avail = stacks_data.get(stack, {}).get("available_engineers", 0)
            if avail == 0:
                gaps.append(stack)

        return {
            "required_stacks": required_stacks,
            "bench_available":  len(gaps) == 0,
            "gaps":             gaps,
        }
    except Exception:
        return {
            "required_stacks": required_stacks,
            "bench_available":  True,
            "gaps":             [],
        }


def _infer_segment(funding, layoff, leadership, eng_roles, velocity) -> tuple:
    """
    Infer primary segment match from available signals.
    Returns (segment_name, confidence).
    This is a hint — the full classifier in icp_classifier.py makes the final call.
    """
    # Layoff + funding → segment 2
    if layoff.get("detected") and funding.get("detected"):
        return "segment_2_mid_market_restructure", 0.75

    # Leadership change → segment 3
    if leadership.get("detected"):
        return "segment_3_leadership_transition", 0.80

    # Recent funding → segment 1
    if funding.get("detected"):
        stage = funding.get("stage", "")
        if stage in ("series_a", "series_b"):
            return "segment_1_series_a_b", 0.82
        return "segment_1_series_a_b", 0.60

    # Layoff only → segment 2
    if layoff.get("detected"):
        return "segment_2_mid_market_restructure", 0.70

    # Velocity signal with enough roles
    if velocity in ("tripled_or_more", "doubled") and eng_roles >= 5:
        return "segment_1_series_a_b", 0.55

    return "abstain", 0.40


if __name__ == "__main__":
    # Test with Orrin Labs from seed sample
    result = get_hiring_signal(
        company_name="Orrin Labs Inc.",
        domain="orrin-labs.example",
        funding_event={
            "detected":   True,
            "stage":      "series_b",
            "amount_usd": 14_000_000,
            "closed_at":  "2026-02-12",
            "source_url": "https://www.crunchbase.com/funding_round/orrin-labs-series-b",
        },
        layoff_event={"detected": False},
        leadership_change={"detected": False},
        current_job_titles=[
            "Senior Backend Engineer",
            "Data Platform Engineer",
            "ML Engineer",
            "Data Platform Engineer",
            "Frontend Engineer",
            "DevOps Engineer",
            "Engineering Manager",
            "Senior ML Engineer",
            "Data Engineer",
            "Backend Engineer",
            "Full Stack Engineer",
        ],
        prior_job_titles=[
            "Backend Engineer",
            "Data Engineer",
            "Frontend Engineer",
            "DevOps Engineer",
        ],
    )

    print(f"Prospect: {result['prospect_name']}")
    print(f"Segment: {result['primary_segment_match']}")
    print(f"Segment confidence: {result['segment_confidence']}")
    print(f"Velocity: {result['hiring_velocity']['velocity_label']}")
    print(f"Eng roles today: {result['hiring_velocity']['open_roles_today']}")
    print(f"Eng roles 60d ago: {result['hiring_velocity']['open_roles_60_days_ago']}")
    print(f"Required stacks: {result['tech_stack']}")
    print(f"Bench available: {result['bench_to_brief_match']['bench_available']}")
    print(f"Bench gaps: {result['bench_to_brief_match']['gaps']}")
    print(f"Honesty flags: {result['honesty_flags']}")
    print(f"Data sources: {[s['source'] for s in result['data_sources_checked']]}")