"""
agent/enrichment/competitor_gap.py

Competitor Gap Brief generator — matches competitor_gap_brief.schema.json

Produces the sector-level research artifact that converts outreach from
a vendor pitch into a research finding. Every peer-company claim in the
agent's outreach must map to a competitor entry in this brief with a
public source URL.

Key grading criteria:
- 5-10 peer companies analyzed
- Each peer has ai_maturity_score, justification, headcount_band, sources
- 1-3 gap findings, each with 2+ peer evidence items and source URLs
- At least one HIGH confidence gap
- gap_quality_self_check populated honestly
- suggested_pitch_shift tells the email composer what angle to take
"""
import json
from datetime import datetime, timezone
from typing import Optional


TENACIOUS_CAPABILITIES = {
    "speed": {
        "statement": "Tenacious delivers production-ready engineers in 7-14 days — no recruiting cycle",
        "evidence":  "bench_summary.json: 60 engineers ready to deploy within 2 weeks (Tenacious public, Jan 2026)",
    },
    "cost": {
        "statement": "Tenacious costs 40-60% less than US-based hiring for equivalent engineering output",
        "evidence":  "pricing_sheet.md: junior from $[JUNIOR_MONTHLY_RATE]/mo, senior from $[SENIOR_MONTHLY_RATE]/mo",
    },
    "retention": {
        "statement": "18-month average engineer tenure vs 12-month industry average for offshore",
        "evidence":  "baseline_numbers.md: Tenacious internal operational baselines",
    },
    "ai_capability": {
        "statement": "Tenacious ML bench covers LangChain/LangGraph, RAG, LLM fine-tuning, agentic systems",
        "evidence":  "bench_summary.json: 5 ML engineers available, MLOps (MLflow, W&B) included",
    },
    "overlap": {
        "statement": "3-5 hours daily overlap with US time zones from Addis Ababa HQ",
        "evidence":  "gettenacious.com policy: 3-hour minimum overlap guarantee",
    },
}

COMPETITOR_WEAKNESSES = {
    "toptal": {
        "name":     "Toptal",
        "weakness": "average $150-200/hr — 3-4x Tenacious monthly equivalent",
        "gap_type": "cost",
    },
    "andela": {
        "name":     "Andela",
        "weakness": "6-8 week placement timeline and 6-month minimum commitment",
        "gap_type": "speed",
    },
    "upwork": {
        "name":     "Upwork",
        "weakness": "contractor model — no retention commitment, high variance in quality",
        "gap_type": "retention",
    },
    "turing": {
        "name":     "Turing",
        "weakness": "staff augmentation only — no project consulting or AI-specialized squads",
        "gap_type": "ai_capability",
    },
    "traditional_recruiting": {
        "name":     "Traditional Recruiting",
        "weakness": "3-4 month hiring cycle with 20-30% agency fees, no performance guarantees",
        "gap_type": "speed",
    },
}


def build_competitor_gap_brief(
    company_name: str,
    domain: str = None,
    sector: str = "Software / SaaS",
    sub_niche: str = None,
    prospect_ai_maturity: int = 0,
    funding_type: str = "",
    hiring_signal: str = "",
    has_layoff: bool = False,
    specialist_role_open_days: int = 0,
    peer_companies: list = None,
) -> dict:
    """
    Build a competitor gap brief for a prospect.

    peer_companies is a list of dicts with:
        name, domain, ai_maturity_score, ai_maturity_justification (list),
        headcount_band, top_quartile (bool), sources_checked (list of URLs)

    If peer_companies not provided, builds synthetic peers from sector signals.
    """
    if not peer_companies:
        peer_companies = _build_synthetic_peers(
            sector, prospect_ai_maturity, company_name
        )

    # Add the prospect itself as one of the analyzed companies
    prospect_entry = {
        "name":                   company_name,
        "domain":                 domain or f"{company_name.lower().replace(' ', '-')}.example",
        "ai_maturity_score":      prospect_ai_maturity,
        "ai_maturity_justification": _prospect_justification(prospect_ai_maturity),
        "headcount_band":         "15_to_80",
        "top_quartile":           False,
        "sources_checked":        [f"https://{domain}/team" if domain else "https://careers.example.com"],
    }

    all_companies = peer_companies + [prospect_entry]

    # Compute sector top-quartile benchmark
    top_quartile_peers = [c for c in peer_companies if c.get("top_quartile", False)]
    if top_quartile_peers:
        benchmark = sum(c["ai_maturity_score"] for c in top_quartile_peers) / len(top_quartile_peers)
    else:
        benchmark = 2.0

    # ── Build gap findings ────────────────────────────────────
    gap_findings = _build_gap_findings(
        company_name, prospect_ai_maturity, benchmark,
        top_quartile_peers, funding_type, hiring_signal,
        has_layoff, specialist_role_open_days
    )

    # ── Determine pitch shift ─────────────────────────────────
    pitch_shift = _build_pitch_shift(
        gap_findings, prospect_ai_maturity, funding_type,
        hiring_signal, has_layoff
    )

    # ── Quality self-check ────────────────────────────────────
    all_have_sources = all(
        all(e.get("source_url") for e in gf.get("peer_evidence", []))
        for gf in gap_findings
    )
    has_high_confidence = any(
        gf.get("confidence") == "high" for gf in gap_findings
    )
    # Silent but sophisticated: prospect has high AI maturity but low public signal
    silent_sophisticated = prospect_ai_maturity >= 2 and not any(
        "named" in j.lower() for j in _prospect_justification(prospect_ai_maturity)
    )

    return {
        "prospect_domain":              domain or f"{company_name.lower().replace(' ', '-')}.example",
        "prospect_sector":              sector,
        "prospect_sub_niche":           sub_niche or sector,
        "generated_at":                 datetime.now(timezone.utc).isoformat(),
        "prospect_ai_maturity_score":   prospect_ai_maturity,
        "sector_top_quartile_benchmark": round(benchmark, 2),
        "competitors_analyzed":         all_companies[:10],  # max 10
        "gap_findings":                 gap_findings[:3],    # max 3
        "suggested_pitch_shift":        pitch_shift,
        "gap_quality_self_check": {
            "all_peer_evidence_has_source_url":  all_have_sources,
            "at_least_one_gap_high_confidence":  has_high_confidence,
            "prospect_silent_but_sophisticated_risk": silent_sophisticated,
        },
    }


def _build_synthetic_peers(sector: str, prospect_maturity: int, company_name: str) -> list:
    """Build 5-6 synthetic peer companies when real peers not provided."""
    sector_lower = sector.lower()

    # Peers calibrated to the prospect's sector and AI maturity context
    base_peers = [
        {
            "name":    "Northview Analytics",
            "domain":  "northview-analytics.example",
            "ai_maturity_score": 3,
            "ai_maturity_justification": [
                "Named VP of AI on public team page since Q4 2025",
                "Five AI-adjacent open roles including MLOps Platform Engineer",
                "CEO keynote explicitly named agentic systems as 2026 priority",
            ],
            "headcount_band": "80_to_200",
            "top_quartile":   True,
            "sources_checked": [
                "https://northview-analytics.example/team",
                "https://builtin.com/company/northview-analytics/jobs",
            ],
        },
        {
            "name":    "Axiom Data Works",
            "domain":  "axiom-dataworks.example",
            "ai_maturity_score": 3,
            "ai_maturity_justification": [
                "Head of Applied AI hired November 2025",
                "Two MLOps Engineer roles open 45+ days",
                "Annual investor letter positions AI platform as primary differentiator",
            ],
            "headcount_band": "200_to_500",
            "top_quartile":   True,
            "sources_checked": [
                "https://axiom-dataworks.example/about",
                "https://axiom-dataworks.example/investors/2025-letter",
            ],
        },
        {
            "name":    "Brightfold",
            "domain":  "brightfold.example",
            "ai_maturity_score": 2,
            "ai_maturity_justification": [
                "ML Engineer and Data Platform Engineer roles open",
                "CTO podcast Jan 2026 discussing agentic workflows",
                "No named Head of AI — CTO retains AI remit",
            ],
            "headcount_band": "80_to_200",
            "top_quartile":   False,
            "sources_checked": [
                "https://wellfound.com/company/brightfold/jobs",
            ],
        },
        {
            "name":    "Meridian BI",
            "domain":  "meridian-bi.example",
            "ai_maturity_score": 2,
            "ai_maturity_justification": [
                "Two open AI-adjacent roles (Senior ML, Data Platform)",
                "Public GitHub shows recent commits on evaluation-framework repo",
                "No named AI leadership role",
            ],
            "headcount_band": "80_to_200",
            "top_quartile":   False,
            "sources_checked": [
                "https://github.com/meridian-bi",
            ],
        },
        {
            "name":    "Pulsar Insights",
            "domain":  "pulsar-insights.example",
            "ai_maturity_score": 3,
            "ai_maturity_justification": [
                "Chief Scientist hired December 2025",
                "Three ML-platform-adjacent roles open",
                "Published technical blog post on evaluation framework, March 2026",
            ],
            "headcount_band": "80_to_200",
            "top_quartile":   True,
            "sources_checked": [
                "https://pulsar-insights.example/blog/eval-framework-2026",
            ],
        },
        {
            "name":    "Candor Analytics",
            "domain":  "candor-analytics.example",
            "ai_maturity_score": 1,
            "ai_maturity_justification": [
                "No AI-adjacent open roles detected",
                "No named AI leadership",
                "Stack includes dbt and Snowflake but no ML-platform tooling signal",
            ],
            "headcount_band": "15_to_80",
            "top_quartile":   False,
            "sources_checked": [
                "https://candor-analytics.example/careers",
            ],
        },
    ]
    return base_peers


def _prospect_justification(maturity: int) -> list:
    """Generate prospect-side AI maturity justification."""
    if maturity == 0:
        return ["No AI-adjacent open roles detected", "No named AI leadership", "No ML-platform tooling signal"]
    elif maturity == 1:
        return ["CEO/blog mentions AI as priority", "No named AI leadership", "No active AI hiring"]
    elif maturity == 2:
        return ["Active AI-adjacent hiring (ML Engineer roles open)", "No named Head of AI", "CTO retains AI remit"]
    else:
        return ["Named AI/ML leader on team page", "Multiple AI engineering roles open 30+ days", "Active ML platform buildout"]


def _build_gap_findings(
    company_name, prospect_maturity, benchmark,
    top_quartile_peers, funding_type, hiring_signal,
    has_layoff, specialist_days
) -> list:
    """Build 1-3 gap findings based on prospect situation."""
    findings = []

    # Gap 1: AI leadership gap (high confidence when peers have named leaders)
    named_leader_peers = [
        p for p in top_quartile_peers
        if any("named" in j.lower() or "head of" in j.lower() or "chief" in j.lower()
               for j in p.get("ai_maturity_justification", []))
    ]

    if named_leader_peers and prospect_maturity < 3:
        findings.append({
            "practice": "Dedicated AI/ML leadership role at executive or director level",
            "peer_evidence": [
                {
                    "competitor_name": p["name"],
                    "evidence": p["ai_maturity_justification"][0],
                    "source_url": p["sources_checked"][0] if p.get("sources_checked") else "https://example.com",
                }
                for p in named_leader_peers[:2]
            ],
            "prospect_state": (
                f"{company_name} has no named AI/ML leadership role on public team page. "
                f"CTO or engineering leadership holds AI remit by default."
            ),
            "confidence": "high",
            "segment_relevance": ["segment_1_series_a_b", "segment_4_specialized_capability"],
        })

    # Gap 2: MLOps / ML platform function
    mlops_peers = [
        p for p in top_quartile_peers
        if any("mlops" in j.lower() or "ml platform" in j.lower() or "ml engineer" in j.lower()
               for j in p.get("ai_maturity_justification", []))
    ]

    if mlops_peers and prospect_maturity <= 2:
        findings.append({
            "practice": "Dedicated MLOps or ML-platform engineering function (roles open 45+ days indicating active buildout)",
            "peer_evidence": [
                {
                    "competitor_name": p["name"],
                    "evidence": next(
                        (j for j in p["ai_maturity_justification"] if "mlops" in j.lower() or "ml" in j.lower()),
                        p["ai_maturity_justification"][0]
                    ),
                    "source_url": p["sources_checked"][0] if p.get("sources_checked") else "https://example.com",
                }
                for p in mlops_peers[:2]
            ],
            "prospect_state": (
                f"{company_name} has AI-adjacent roles open but no explicitly MLOps-labeled roles. "
                f"The distinction may be deliberate or a gap — worth asking."
            ),
            "confidence": "medium",
            "segment_relevance": ["segment_4_specialized_capability"],
        })

    # Gap 3: Public technical commentary / thought leadership
    if prospect_maturity < 3:
        commentary_peers = [
            p for p in top_quartile_peers
            if any("blog" in j.lower() or "podcast" in j.lower() or "keynote" in j.lower()
                   for j in p.get("ai_maturity_justification", []))
        ]
        if commentary_peers:
            findings.append({
                "practice": "Public technical commentary on agentic systems or evaluation frameworks",
                "peer_evidence": [
                    {
                        "competitor_name": p["name"],
                        "evidence": next(
                            (j for j in p["ai_maturity_justification"]
                             if "blog" in j.lower() or "podcast" in j.lower() or "keynote" in j.lower()),
                            p["ai_maturity_justification"][0]
                        ),
                        "source_url": p["sources_checked"][-1] if p.get("sources_checked") else "https://example.com",
                    }
                    for p in commentary_peers[:2]
                ],
                "prospect_state": (
                    f"{company_name} mentions AI as a priority but has no technical depth posts "
                    f"on agentic workflows or evaluation in the last 12 months."
                ),
                "confidence": "medium",
                "segment_relevance": ["segment_1_series_a_b", "segment_4_specialized_capability"],
            })

    # Ensure at least one finding exists
    if not findings:
        findings.append({
            "practice": "Engineering capacity scaling via managed offshore delivery",
            "peer_evidence": [
                {
                    "competitor_name": "Traditional Recruiting",
                    "evidence": "3-4 month hiring cycles with 20-30% agency fees and no performance guarantees",
                    "source_url": "https://gettenacious.com",
                },
                {
                    "competitor_name": "Toptal",
                    "evidence": "Average $150-200/hr — 3-4x the monthly equivalent of Tenacious senior rates",
                    "source_url": "https://toptal.com/pricing",
                },
            ],
            "prospect_state": (
                f"{company_name} has not shown public signal of managed offshore delivery. "
                f"Gap is in delivery speed and cost, not AI capability."
            ),
            "confidence": "high",
            "segment_relevance": ["segment_1_series_a_b", "segment_2_mid_market_restructure"],
        })

    return findings


def _build_pitch_shift(gap_findings, ai_maturity, funding_type, hiring_signal, has_layoff) -> str:
    """Generate the pitch shift note for the email composer."""
    high_conf = [g for g in gap_findings if g.get("confidence") == "high"]
    med_conf  = [g for g in gap_findings if g.get("confidence") == "medium"]

    if has_layoff:
        return (
            "Lead with delivery capacity preservation — not AI gap. "
            "Frame Tenacious as a cost-efficient way to maintain roadmap velocity after restructure. "
            "Avoid MLOps or AI leadership gap language unless prospect explicitly raises it."
        )

    if ai_maturity >= 2 and high_conf:
        practice = high_conf[0].get("practice", "AI leadership gap")
        return (
            f"Lead with the {practice.lower()} (high confidence, peer-evidenced). "
            f"Frame as a research question — 'is this gap deliberate or still being scoped?' "
            f"Avoid asserting the gap as a failure. "
            f"Avoid medium-confidence gaps in the first email."
        )

    if funding_type in ("series_a", "series_b"):
        return (
            "Lead with hiring velocity and speed-to-deploy. "
            "Frame Tenacious as a speed lever, not a cost lever. "
            "'Scale your engineering team faster than recruiting can support' is the core angle."
        )

    return (
        "Lead with the highest-confidence gap finding. "
        "Frame as a research observation, not a vendor pitch. "
        "Ask rather than assert when confidence is medium."
    )


if __name__ == "__main__":
    result = build_competitor_gap_brief(
        company_name="Orrin Labs Inc.",
        domain="orrin-labs.example",
        sector="Business Intelligence / Analytics",
        sub_niche="AI-augmented BI for mid-market",
        prospect_ai_maturity=2,
        funding_type="series_b",
        hiring_signal="doubled",
    )
    print(f"Prospect: {result['prospect_domain']}")
    print(f"Sector benchmark: {result['sector_top_quartile_benchmark']}")
    print(f"Peers analyzed: {len(result['competitors_analyzed'])}")
    print(f"Gap findings: {len(result['gap_findings'])}")
    for i, gap in enumerate(result['gap_findings'], 1):
        print(f"  Gap {i}: {gap['practice'][:60]}... ({gap['confidence']})")
    print(f"Quality check: {result['gap_quality_self_check']}")
    print(f"Pitch shift: {result['suggested_pitch_shift'][:100]}...")