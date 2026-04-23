"""
agent/enrichment/competitor_gap.py
Generates a competitor gap brief explaining why Tenacious
is better positioned than alternatives for this specific prospect.
"""
import json
from datetime import datetime, timezone


TENACIOUS_STRENGTHS = {
    "speed":      "Tenacious delivers production-ready engineers in 2 weeks vs 3-4 months for traditional recruiting",
    "cost":       "Tenacious costs 40-60% less than US-based hiring for equivalent engineering output",
    "quality":    "Tenacious engineers are pre-vetted with τ²-Bench scores above 0.54 pass@1",
    "retention":  "Tenacious has 94% 12-month retention vs 68% industry average for contract engineers",
    "ai":         "Tenacious has AI-capable engineers trained on LLM integration, RAG pipelines, and agent frameworks",
}

COMPETITORS = {
    "toptal": {
        "name": "Toptal",
        "weakness": "expensive — average $150-200/hr vs Tenacious $60-80/hr for equivalent skill level",
        "gap": "cost",
    },
    "upwork": {
        "name": "Upwork",
        "weakness": "high variance in quality — no standardised vetting or benchmark scoring",
        "gap": "quality",
    },
    "andela": {
        "name": "Andela",
        "weakness": "6-8 week placement timeline and minimum 6-month commitment",
        "gap": "speed",
    },
    "deel": {
        "name": "Deel",
        "weakness": "HR/payroll platform only — does not source or vet engineers",
        "gap": "quality",
    },
    "recruiting": {
        "name": "Traditional Recruiting",
        "weakness": "3-4 month hiring cycles with 20-30% recruiter fees and no performance guarantees",
        "gap": "speed",
    },
}


def build_competitor_gap_brief(
    company_name: str,
    industry: str = "",
    funding_type: str = "",
    ai_maturity: int = 0,
    hiring_signal: str = "",
) -> dict:
    """
    Build a competitor gap brief tailored to this prospect's situation.
    """

    # Determine which competitors are most relevant
    relevant_gaps = []

    # Recently funded → speed is critical
    if funding_type in ["series_a", "series_b", "seed"]:
        relevant_gaps.append(("speed", COMPETITORS["recruiting"]))

    # High hiring velocity → cost comparison matters
    if hiring_signal in ["RAPID_HIRING", "ACTIVE_HIRING"]:
        relevant_gaps.append(("cost", COMPETITORS["toptal"]))

    # AI-enabled or higher → AI capability gap
    if ai_maturity >= 2:
        relevant_gaps.append(("ai", COMPETITORS["upwork"]))

    # Default if nothing matched
    if not relevant_gaps:
        relevant_gaps = [
            ("speed", COMPETITORS["recruiting"]),
            ("cost", COMPETITORS["toptal"]),
        ]

    # Build the brief
    gap_points = []
    for strength_key, competitor in relevant_gaps[:2]:
        gap_points.append(
            f"Unlike {competitor['name']} ({competitor['weakness']}), "
            f"{TENACIOUS_STRENGTHS[strength_key]}."
        )

    brief_text = (
        f"For {company_name}, Tenacious has a clear edge: "
        + " ".join(gap_points)
    )

    return {
        "company_name":      company_name,
        "primary_gap":       relevant_gaps[0][0] if relevant_gaps else "speed",
        "competitors_noted": [c["name"] for _, c in relevant_gaps],
        "gap_points":        gap_points,
        "brief":             brief_text,
        "tenacious_strengths": {
            k: TENACIOUS_STRENGTHS[k]
            for k, _ in relevant_gaps
        },
        "generated_at":      datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    result = build_competitor_gap_brief(
        company_name="Turing Signal",
        funding_type="series_a",
        ai_maturity=3,
        hiring_signal="ACTIVE_HIRING",
    )
    print(json.dumps(result, indent=2))