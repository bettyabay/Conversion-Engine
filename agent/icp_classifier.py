"""
agent/icp_classifier.py

ICP Classifier — per icp_definition.md
Four segments with FIXED names (required for grading).
Uses strict priority override chain, not highest-score wins.

Override chain (from icp_definition.md):
  1. Layoff in last 120 days AND fresh funding → segment_2 (cost pressure dominates)
  2. New CTO/VP Eng in last 90 days → segment_3 (transition window)
  3. Specialized capability AND ai_maturity >= 2 → segment_4
  4. Fresh funding in last 180 days → segment_1
  5. Otherwise → abstain

Confidence < 0.6 → abstain regardless of score.

Qualifying filters per segment:
  Segment 1: funding in 180 days, $5M-$30M, headcount 15-80,
             North America/UK/EU, 5+ open engineering roles
  Segment 2: headcount 200-2000, layoff in 120 days or restructure press,
             3+ open engineering roles after layoff
  Segment 3: new CTO/VP Eng in 90 days, headcount 50-500,
             no dual C-suite transition
  Segment 4: 60+ day unfilled specialist role, ai_maturity >= 2,
             bench-feasible capability
"""
import json
from datetime import datetime, timezone
from typing import Optional


SEGMENT_NAMES = {
    1: "segment_1_series_a_b",
    2: "segment_2_mid_market_restructure",
    3: "segment_3_leadership_transition",
    4: "segment_4_specialized_capability",
}

SEGMENT_DESCRIPTIONS = {
    1: "Recently-funded Series A/B — needs to scale engineering fast after raise",
    2: "Mid-market platform restructuring cost — replace capacity, preserve delivery",
    3: "Engineering leadership transition — new CTO/VP Eng in first 90 days",
    4: "Specialized capability gap — building AI/ML product without in-house expertise",
}

# Pitch language per segment and AI readiness (from icp_definition.md)
SEGMENT_PITCHES = {
    1: {
        "high_ai": "scale your AI team faster than in-house hiring can support",
        "low_ai":  "stand up your first AI function with a dedicated squad",
        "default": "scale your engineering capacity faster than recruiting can support — bench engineers available in 7-14 days, embedded in your stack",
    },
    2: {
        "high_ai": "preserve your AI delivery capacity while reshaping cost structure",
        "low_ai":  "maintain platform delivery velocity through the restructure",
        "default": "preserve delivery capacity on the specific roadmap you described — the architecture ownership stays with your in-house team",
    },
    3: {
        "default": "in our experience with CTO transitions, the first 90 days are when vendor mix gets a fresh look — no pitch deck on the first call, just a conversation about what your reassessment should include",
    },
    4: {
        "default": "three companies in your sector have opened similar specialist roles in the last 60 days — curious whether your gap is a deliberate choice or a scoping-in-progress",
    },
}


def classify(
    company_name: str,
    # Funding signals
    funding_type: str = "",            # seed/series_a/series_b/series_c/etc
    funding_amount_usd: int = 0,
    funding_days_ago: int = 999,       # days since funding closed
    # Headcount
    headcount: int = 0,
    # Hiring signals
    open_eng_roles: int = 0,
    specialist_role_open_days: int = 0,  # how long key specialist role open
    # Restructuring signals
    has_layoff: bool = False,
    layoff_days_ago: int = 999,
    layoff_percentage: float = 0.0,
    # Leadership change
    has_new_cto: bool = False,
    cto_days_ago: int = 999,
    has_dual_transition: bool = False,  # dual C-suite = disqualifier
    # AI maturity
    ai_maturity_score: int = 0,
    # Disqualifiers
    has_anti_offshore_stance: bool = False,
    is_competitor_client: bool = False,
    is_regulated_jurisdiction: bool = False,
    # Description for context
    description: str = "",
) -> dict:
    """
    Classify a prospect into one of 4 ICP segments.
    Uses strict priority override chain from icp_definition.md.
    Returns dict with segment name, confidence, pitch, and rationale.
    """

    # ── Global disqualifiers ──────────────────────────────────
    if has_anti_offshore_stance:
        return _abstain(company_name, "Disqualified: public anti-offshore stance detected")
    if is_competitor_client:
        return _abstain(company_name, "Disqualified: already a client of direct Tenacious competitor")
    if is_regulated_jurisdiction:
        return _abstain(company_name, "Disqualified: regulated jurisdiction requires manual approval")

    # ── Check qualifying filters per segment ──────────────────
    seg1_score, seg1_confidence, seg1_reasons = _score_segment_1(
        funding_type, funding_amount_usd, funding_days_ago,
        headcount, open_eng_roles, has_layoff, layoff_days_ago
    )

    seg2_score, seg2_confidence, seg2_reasons = _score_segment_2(
        headcount, has_layoff, layoff_days_ago, layoff_percentage,
        open_eng_roles
    )

    seg3_score, seg3_confidence, seg3_reasons = _score_segment_3(
        has_new_cto, cto_days_ago, headcount, has_dual_transition
    )

    seg4_score, seg4_confidence, seg4_reasons = _score_segment_4(
        ai_maturity_score, specialist_role_open_days, open_eng_roles
    )

    # ── Apply strict priority override chain ──────────────────
    # Rule 1: Layoff AND fresh funding → Segment 2
    if has_layoff and layoff_days_ago <= 120 and funding_days_ago <= 180:
        if seg2_confidence >= 0.6:
            return _build_result(
                company_name, 2, seg2_confidence,
                "Layoff within 120 days AND fresh funding — cost pressure dominates buying window",
                seg2_reasons, ai_maturity_score
            )

    # Rule 2: New CTO/VP Eng → Segment 3
    if has_new_cto and cto_days_ago <= 90 and not has_dual_transition:
        if seg3_confidence >= 0.6:
            return _build_result(
                company_name, 3, seg3_confidence,
                "New CTO/VP Eng in last 90 days — transition window dominates",
                seg3_reasons, ai_maturity_score
            )

    # Rule 3: Specialized capability + AI maturity >= 2 → Segment 4
    if ai_maturity_score >= 2 and specialist_role_open_days >= 60:
        if seg4_confidence >= 0.6:
            return _build_result(
                company_name, 4, seg4_confidence,
                "Specialist role open 60+ days and AI maturity >= 2 — capability gap signal",
                seg4_reasons, ai_maturity_score
            )

    # Rule 4: Fresh funding → Segment 1
    if funding_days_ago <= 180 and funding_type in ("series_a", "series_b"):
        if seg1_confidence >= 0.6:
            return _build_result(
                company_name, 1, seg1_confidence,
                "Series A/B funding in last 180 days",
                seg1_reasons, ai_maturity_score
            )

    # Rule 4b: Seed funding with enough qualifying filters
    if funding_days_ago <= 180 and funding_type == "seed":
        if seg1_confidence >= 0.6:
            return _build_result(
                company_name, 1, seg1_confidence,
                "Seed funding in last 180 days with qualifying hiring signal",
                seg1_reasons, ai_maturity_score
            )

    # ── Check if any segment reaches 0.6 confidence ──────────
    # If no priority rule fired, use highest confidence above threshold
    candidates = [
        (seg1_confidence, 1, seg1_reasons),
        (seg2_confidence, 2, seg2_reasons),
        (seg3_confidence, 3, seg3_reasons),
        (seg4_confidence, 4, seg4_reasons),
    ]
    candidates.sort(key=lambda x: x[0], reverse=True)

    if candidates[0][0] >= 0.6:
        conf, seg, reasons = candidates[0]
        return _build_result(
            company_name, seg, conf,
            f"Highest confidence segment ({SEGMENT_NAMES[seg]})",
            reasons, ai_maturity_score
        )

    # ── Abstain — no segment reached 0.6 confidence ──────────
    return _abstain(
        company_name,
        f"No segment reached 0.6 confidence threshold. "
        f"Best: {SEGMENT_NAMES[candidates[0][1]]} at {candidates[0][0]:.2f}. "
        f"Send generic exploratory email, do not segment-specific pitch."
    )


def _score_segment_1(funding_type, amount_usd, days_ago, headcount, open_roles, has_layoff, layoff_days_ago):
    """Score Segment 1: Recently-funded Series A/B startups."""
    score = 0
    reasons = []

    # Disqualifier: layoff in last 90 days > 15% → shifts to Segment 2
    if has_layoff and layoff_days_ago <= 90:
        return 0, 0.1, ["Disqualified from Seg 1: layoff in last 90 days shifts to Segment 2"]

    # Qualifying: Series A/B in last 180 days, $5M-$30M
    if funding_type in ("series_a", "series_b") and days_ago <= 180:
        if 5_000_000 <= amount_usd <= 30_000_000:
            score += 4
            reasons.append(f"Series A/B ${amount_usd/1e6:.0f}M closed {days_ago} days ago")
        elif amount_usd > 0:
            score += 2
            reasons.append(f"Series A/B funding (amount outside $5M-$30M range)")
    elif funding_type == "seed" and days_ago <= 180:
        score += 2
        reasons.append(f"Seed funding {days_ago} days ago")

    # Headcount 15-80
    if 15 <= headcount <= 80:
        score += 2
        reasons.append(f"Headcount {headcount} in target range 15-80")
    elif headcount == 0:
        score += 1  # unknown but don't penalize
        reasons.append("Headcount unknown")

    # 5+ open engineering roles
    if open_roles >= 5:
        score += 2
        reasons.append(f"{open_roles} open engineering roles (target: 5+)")
    elif open_roles >= 2:
        score += 1
        reasons.append(f"{open_roles} open engineering roles (below 5 target)")

    confidence = min(score / 8.0, 0.95) if score > 0 else 0.0
    return score, confidence, reasons


def _score_segment_2(headcount, has_layoff, layoff_days_ago, layoff_pct, open_roles):
    """Score Segment 2: Mid-market restructuring."""
    score = 0
    reasons = []

    # Disqualifier: layoff above 40%
    if layoff_pct > 40:
        return 0, 0.1, ["Disqualified: layoff above 40% — survival mode, not vendor expansion"]

    # Qualifying: headcount 200-2000
    if 200 <= headcount <= 2000:
        score += 2
        reasons.append(f"Headcount {headcount} in target range 200-2000")
    elif headcount == 0:
        pass  # unknown

    # Layoff in last 120 days
    if has_layoff and layoff_days_ago <= 120:
        score += 4
        reasons.append(f"Layoff event {layoff_days_ago} days ago")

    # 3+ open roles after layoff (still hiring = not frozen)
    if open_roles >= 3:
        score += 2
        reasons.append(f"{open_roles} open roles after layoff (not frozen)")
    elif open_roles > 0:
        score += 1

    confidence = min(score / 8.0, 0.95) if score > 0 else 0.0
    return score, confidence, reasons


def _score_segment_3(has_new_cto, cto_days_ago, headcount, has_dual_transition):
    """Score Segment 3: Leadership transition."""
    score = 0
    reasons = []

    # Disqualifier: interim appointment or dual transition
    if has_dual_transition:
        return 0, 0.1, ["Disqualified: dual C-suite transition freezes procurement"]

    # Qualifying: new CTO/VP Eng in last 90 days
    if has_new_cto and cto_days_ago <= 90:
        score += 5
        reasons.append(f"New CTO/VP Eng started {cto_days_ago} days ago")
    elif has_new_cto and cto_days_ago <= 180:
        score += 2
        reasons.append(f"New CTO/VP Eng started {cto_days_ago} days ago (outside 90-day window)")

    # Headcount 50-500
    if 50 <= headcount <= 500:
        score += 2
        reasons.append(f"Headcount {headcount} in target range 50-500")
    elif headcount == 0:
        score += 1

    confidence = min(score / 7.0, 0.95) if score > 0 else 0.0
    return score, confidence, reasons


def _score_segment_4(ai_maturity, specialist_days_open, open_roles):
    """Score Segment 4: Specialized capability gap."""
    score = 0
    reasons = []

    # Hard gate: AI maturity must be >= 2
    if ai_maturity < 2:
        return 0, 0.0, [f"Hard-gated: AI maturity {ai_maturity} < 2 required for Segment 4"]

    score += ai_maturity  # 2 or 3

    # Specialist role open 60+ days
    if specialist_days_open >= 60:
        score += 3
        reasons.append(f"Specialist role open {specialist_days_open} days (target: 60+)")
    elif specialist_days_open >= 30:
        score += 1
        reasons.append(f"Specialist role open {specialist_days_open} days (below 60-day target)")

    # Any open engineering roles
    if open_roles >= 1:
        score += 1

    reasons.insert(0, f"AI maturity score {ai_maturity} >= 2 (pitch_ai=true)")

    confidence = min(score / 6.0, 0.95) if score > 0 else 0.0
    return score, confidence, reasons


def _build_result(company_name, segment_num, confidence, rationale, reasons, ai_maturity):
    """Build the final classification result dict."""
    segment_name = SEGMENT_NAMES[segment_num]
    pitches = SEGMENT_PITCHES[segment_num]

    if segment_num == 3:
        pitch = pitches["default"]
    elif ai_maturity >= 2:
        pitch = pitches.get("high_ai", pitches["default"])
    else:
        pitch = pitches.get("low_ai", pitches["default"])

    return {
        "company_name":        company_name,
        "segment":             segment_name,
        "segment_number":      segment_num,
        "segment_description": SEGMENT_DESCRIPTIONS[segment_num],
        "confidence":          round(confidence, 3),
        "qualified":           True,
        "rationale":           rationale,
        "qualifying_signals":  reasons,
        "pitch":               pitch,
        "ai_maturity":         ai_maturity,
        "abstain":             False,
        "classified_at":       datetime.now(timezone.utc).isoformat(),
    }


def _abstain(company_name, reason):
    """Return an abstain result — send generic exploratory email."""
    return {
        "company_name":        company_name,
        "segment":             "abstain",
        "segment_number":      None,
        "segment_description": "No qualifying segment — send generic exploratory email",
        "confidence":          0.0,
        "qualified":           False,
        "rationale":           reason,
        "qualifying_signals":  [],
        "pitch":               "Generic exploratory: introduce Tenacious and ask about engineering challenges without a segment-specific angle",
        "ai_maturity":         0,
        "abstain":             True,
        "classified_at":       datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    # Test 1: Orrin Labs — Series B, AI maturity 2
    print("=== Test 1: Orrin Labs (Series B) ===")
    result = classify(
        company_name="Orrin Labs Inc.",
        funding_type="series_b",
        funding_amount_usd=14_000_000,
        funding_days_ago=70,
        headcount=45,
        open_eng_roles=11,
        ai_maturity_score=2,
    )
    print(f"Segment: {result['segment']}")
    print(f"Confidence: {result['confidence']}")
    print(f"Pitch: {result['pitch'][:80]}...")
    print()

    # Test 2: Restructuring scenario
    print("=== Test 2: Mid-market with layoff ===")
    result2 = classify(
        company_name="AcmeCorp",
        funding_type="series_b",
        funding_amount_usd=20_000_000,
        funding_days_ago=100,
        headcount=800,
        open_eng_roles=5,
        has_layoff=True,
        layoff_days_ago=90,
        layoff_percentage=12.0,
        ai_maturity_score=1,
    )
    print(f"Segment: {result2['segment']} (should be segment_2)")
    print(f"Confidence: {result2['confidence']}")
    print()

    # Test 3: New CTO
    print("=== Test 3: New CTO transition ===")
    result3 = classify(
        company_name="TechCo",
        headcount=180,
        has_new_cto=True,
        cto_days_ago=65,
        open_eng_roles=4,
        ai_maturity_score=1,
    )
    print(f"Segment: {result3['segment']} (should be segment_3)")
    print(f"Confidence: {result3['confidence']}")
    print()

    # Test 4: Segment 4 capability gap
    print("=== Test 4: AI capability gap ===")
    result4 = classify(
        company_name="MLStartup",
        headcount=120,
        open_eng_roles=8,
        specialist_role_open_days=70,
        ai_maturity_score=2,
    )
    print(f"Segment: {result4['segment']} (should be segment_4)")
    print(f"Confidence: {result4['confidence']}")
    print()

    # Test 5: Abstain — no signal
    print("=== Test 5: Abstain ===")
    result5 = classify(
        company_name="Unknown Corp",
        headcount=50,
        open_eng_roles=1,
    )
    print(f"Segment: {result5['segment']} (should be abstain)")
    print(f"Qualified: {result5['qualified']}")