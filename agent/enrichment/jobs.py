"""
agent/enrichment/jobs.py
Scrapes job posting velocity to detect hiring signals.
A spike in engineering roles = capacity gap = ICP signal.
"""
import json
import os
import requests
from datetime import datetime, timezone
from typing import Optional


# Engineering role keywords that signal capacity gaps
ENGINEERING_KEYWORDS = [
    "software engineer", "backend engineer", "frontend engineer",
    "full stack", "platform engineer", "devops", "sre", "data engineer",
    "machine learning engineer", "ml engineer", "engineering manager",
    "vp engineering", "cto", "tech lead", "senior engineer",
]


def get_hiring_signal(company_name: str, website: str = None) -> dict:
    """
    Detect hiring velocity for a company.
    Returns a hiring_signal_brief dict.
    """
    # Try Greenhouse (common ATS for funded startups)
    signal = _try_greenhouse(company_name)
    if not signal:
        # Fall back to mock signal for demo purposes
        signal = _mock_signal(company_name)

    return signal


def _try_greenhouse(company_name: str) -> Optional[dict]:
    """
    Attempt to fetch open roles from Greenhouse ATS.
    Many funded startups use Greenhouse and expose a public API.
    """
    slug = company_name.lower().replace(" ", "-").replace(".", "")

    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
        resp = requests.get(url, timeout=5)

        if resp.status_code != 200:
            return None

        data = resp.json()
        jobs = data.get("jobs", [])

        eng_roles = [
            j for j in jobs
            if any(kw in j.get("title", "").lower() for kw in ENGINEERING_KEYWORDS)
        ]

        return _build_signal(
            company_name=company_name,
            total_open_roles=len(jobs),
            eng_open_roles=len(eng_roles),
            roles=eng_roles[:5],  # top 5
            source="greenhouse"
        )

    except Exception as e:
        print(f"[Jobs] Greenhouse lookup failed for {company_name}: {e}")
        return None


def _build_signal(company_name, total_open_roles,
                  eng_open_roles, roles, source) -> dict:

    # Classify signal strength
    if eng_open_roles >= 5:
        signal_strength = "strong"
        signal_label   = "RAPID_HIRING"
    elif eng_open_roles >= 2:
        signal_strength = "medium"
        signal_label   = "ACTIVE_HIRING"
    elif eng_open_roles == 1:
        signal_strength = "weak"
        signal_label   = "LIGHT_HIRING"
    else:
        signal_strength = "none"
        signal_label   = "NO_SIGNAL"

    return {
        "company_name":       company_name,
        "total_open_roles":   total_open_roles,
        "eng_open_roles":     eng_open_roles,
        "signal_strength":    signal_strength,
        "signal_label":       signal_label,
        "top_roles":          [r.get("title") for r in roles],
        "brief":              _generate_brief(company_name, eng_open_roles, signal_label),
        "source":             source,
        "retrieved_at":       datetime.now(timezone.utc).isoformat(),
    }


def _generate_brief(company_name: str, eng_count: int, label: str) -> str:
    if label == "RAPID_HIRING":
        return (
            f"{company_name} has {eng_count} open engineering roles — "
            f"a strong capacity signal. They are scaling faster than "
            f"internal hiring can support."
        )
    elif label == "ACTIVE_HIRING":
        return (
            f"{company_name} has {eng_count} open engineering roles. "
            f"Active hiring suggests growing engineering needs."
        )
    elif label == "LIGHT_HIRING":
        return (
            f"{company_name} has 1 open engineering role. "
            f"Early-stage capacity gap."
        )
    else:
        return (
            f"No active engineering roles found for {company_name}. "
            f"Signal may come from other sources."
        )


def _mock_signal(company_name: str) -> dict:
    """
    Synthetic hiring signal for demo/testing.
    Simulates a company with 4 open eng roles.
    """
    mock_roles = [
        "Senior Backend Engineer",
        "Frontend Engineer",
        "DevOps Engineer",
        "Engineering Manager",
    ]
    return _build_signal(
        company_name=company_name,
        total_open_roles=7,
        eng_open_roles=4,
        roles=[{"title": r} for r in mock_roles],
        source="mock"
    )


if __name__ == "__main__":
    result = get_hiring_signal("Turing Signal")
    print(json.dumps(result, indent=2))