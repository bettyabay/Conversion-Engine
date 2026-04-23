"""
agent/icp_classifier.py
Classifies a prospect into one of 4 ICP segments.

Segment 1 — Recently funded (Series A/B in last 90 days)
Segment 2 — Restructuring / layoff signal
Segment 3 — New CTO or VP Engineering (last 90 days)
Segment 4 — AI capability gap (maturity >= 2, hiring AI engineers)
"""
import json
from datetime import datetime, timezone
from typing import Optional


SEGMENT_DESCRIPTIONS = {
    1: "Recently Funded — needs to scale engineering fast after raise",
    2: "Restructuring — cutting costs, open to outsourced engineering",
    3: "New Technical Leader — new CTO/VP Eng evaluating vendors in first 90 days",
    4: "AI Capability Gap — building AI products, needs AI-capable engineers",
}

SEGMENT_PITCHES = {
    1: (
        "Congratulations on your recent raise. "
        "Tenacious helps funded startups scale engineering in 2 weeks — "
        "no recruiting overhead, production-ready teams."
    ),
    2: (
        "We help companies maintain engineering velocity during transitions — "
        "Tenacious provides flexible capacity without long-term headcount commitment."
    ),
    3: (
        "As you evaluate your engineering setup, "
        "Tenacious gives new technical leaders a fast, low-risk way to "
        "expand capacity while you assess the team."
    ),
    4: (
        "Building AI products requires engineers who can ship LLM integrations, "
        "RAG pipelines, and agent frameworks. Tenacious has that bench ready now."
    ),
}


def classify(
    company_name: str,
    funding_type: str = "",
    funding_date: str = "",
    has_layoff_signal: bool = False,
    has_new_cto: bool = False,
    ai_maturity: int = 0,
    hiring_signal: str = "",
    description: str = "",
) -> dict:
    """
    Classify a prospect into an ICP segment.
    Returns classification dict with segment, confidence, and pitch.
    """

    scores = {1: 0, 2: 0, 3: 0, 4: 0}

    # ── Segment 1 — Recently funded ──────────────────────────
    if funding_type in ["series_a", "series_b", "seed", "series_c"]:
        scores[1] += 3
    if funding_type in ["series_a", "series_b"]:
        scores[1] += 2  # bonus for growth-stage funding
    if hiring_signal in ["RAPID_HIRING", "ACTIVE_HIRING"]:
        scores[1] += 1  # hiring after raise

    # ── Segment 2 — Restructuring / layoff ───────────────────
    if has_layoff_signal:
        scores[2] += 5
    if hiring_signal == "NO_SIGNAL":
        scores[2] += 1  # not hiring = possible freeze

    # ── Segment 3 — New CTO / VP Eng ─────────────────────────
    if has_new_cto:
        scores[3] += 5
    if hiring_signal in ["ACTIVE_HIRING", "RAPID_HIRING"]:
        scores[3] += 1  # new leader building team

    # ── Segment 4 — AI capability gap ────────────────────────
    if ai_maturity >= 2:
        scores[4] += 3
    if ai_maturity >= 3:
        scores[4] += 2  # bonus for AI-first
    if hiring_signal in ["ACTIVE_HIRING", "RAPID_HIRING"]:
        scores[4] += 1

    # Pick highest scoring segment
    segment = max(scores, key=lambda k: scores[k])
    top_score = scores[segment]

    # Confidence
    if top_score >= 5:
        confidence = "high"
    elif top_score >= 3:
        confidence = "medium"
    elif top_score >= 1:
        confidence = "low"
    else:
        confidence = "unqualified"
        segment = None

    # Block Segment 4 if AI maturity < 2
    if segment == 4 and ai_maturity < 2:
        # Fall back to next best segment
        scores[4] = 0
        segment = max(scores, key=lambda k: scores[k])
        confidence = "medium"

    return {
        "company_name":        company_name,
        "segment":             segment,
        "segment_description": SEGMENT_DESCRIPTIONS.get(segment, "Unqualified"),
        "confidence":          confidence,
        "scores":              scores,
        "pitch":               SEGMENT_PITCHES.get(segment, ""),
        "ai_maturity":         ai_maturity,
        "hiring_signal":       hiring_signal,
        "qualified":           confidence != "unqualified",
        "classified_at":       datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    # Test with Turing Signal synthetic prospect
    result = classify(
        company_name="Turing Signal",
        funding_type="series_a",
        has_new_cto=True,
        ai_maturity=3,
        hiring_signal="ACTIVE_HIRING",
    )
    print(json.dumps(result, indent=2))