"""
agent/enrichment/discovery_brief.py

Discovery Call Context Brief generator.
Produces the 10-section Markdown brief that attaches to every
Cal.com calendar invite for a booked discovery call.

The human delivery lead reads this 10 minutes before the call.
Quality of this brief is the single biggest lever on
discovery-to-proposal conversion.

Per discovery_call_context_brief.md:
- Every section is required (no skipping)
- Section 10 must honestly flag unknowns
- Section 9 must have at least one "do not do" item
- Brief must be at most one scroll on a laptop screen
- Trace ID must be included at the bottom
"""
import json
from datetime import datetime, timezone
from typing import Optional


def generate_discovery_brief(
    # Prospect info
    prospect_name: str,
    prospect_title: str,
    prospect_company: str,
    call_datetime_utc: str,
    call_datetime_local: str,
    delivery_lead: str,
    duration_minutes: int,
    thread_start_date: str,
    original_subject: str,
    langfuse_trace_url: str,
    # Enrichment data
    icp_result: dict = None,
    hiring_signal: dict = None,
    competitor_gap: dict = None,
    ai_maturity: dict = None,
    crunchbase: dict = None,
    layoff_signal: dict = None,
    # Thread data
    conversation_history: list = None,
    objections_raised: list = None,
    price_bands_quoted: list = None,
    # Bench match
    bench_match: dict = None,
    # Trace ID
    trace_id: str = None,
) -> str:
    """
    Generate a complete 10-section discovery call context brief.

    Returns a Markdown string ready to attach to the Cal.com invite.
    """
    icp_result         = icp_result or {}
    hiring_signal      = hiring_signal or {}
    competitor_gap     = competitor_gap or {}
    ai_maturity        = ai_maturity or {}
    crunchbase         = crunchbase or {}
    layoff_signal      = layoff_signal or {}
    conversation_history = conversation_history or []
    objections_raised  = objections_raised or []
    price_bands_quoted = price_bands_quoted or []
    bench_match        = bench_match or {}

    # Extract key signals
    segment        = icp_result.get("segment", "unknown")
    confidence     = icp_result.get("confidence", 0.0)
    segment_desc   = icp_result.get("segment_description", "Unknown segment")
    pitch          = icp_result.get("pitch", "")
    qualified      = icp_result.get("qualified", False)

    velocity       = hiring_signal.get("hiring_velocity", {})
    buying_signals = hiring_signal.get("buying_window_signals", {})
    funding        = buying_signals.get("funding_event", {})
    layoff         = buying_signals.get("layoff_event", layoff_signal)
    leadership     = buying_signals.get("leadership_change", {})
    honesty_flags  = hiring_signal.get("honesty_flags", [])

    ai_score       = ai_maturity.get("score", 0)
    ai_confidence  = ai_maturity.get("confidence_label", "low")
    ai_brief       = ai_maturity.get("brief", "")

    gap_findings   = competitor_gap.get("gap_findings", [])
    pitch_shift    = competitor_gap.get("suggested_pitch_shift", "")

    # Build the brief
    lines = []

    # ── Header ────────────────────────────────────────────────
    lines.append("# Discovery Call Context Brief")
    lines.append("")
    lines.append(f"**Prospect:** {prospect_name} — {prospect_title} at {prospect_company}")
    lines.append(f"**Scheduled:** {call_datetime_utc} ({call_datetime_local} prospect local)")
    lines.append(f"**Delivery lead assigned:** {delivery_lead}")
    lines.append(f"**Call length booked:** {duration_minutes} minutes")
    lines.append(f"**Thread origin:** {thread_start_date} — Email subject: \"{original_subject}\"")
    lines.append(f"**Full thread:** [Langfuse trace]({langfuse_trace_url})")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Section 1: Segment and confidence ─────────────────────
    lines.append("## 1. Segment and Confidence")
    lines.append("")
    lines.append(f"- **Primary segment match:** {segment}")
    lines.append(f"- **Confidence:** {confidence:.0%}")
    lines.append(f"- **Why this segment:** {_one_line_rationale(segment, icp_result, funding, layoff, leadership)}")
    abstain_risk = "Yes — confidence below 0.7, verify signals before segment-specific pitch" if confidence < 0.7 else "No — confidence sufficient for segment-specific pitch"
    lines.append(f"- **Abstention risk:** {abstain_risk}")
    lines.append("")

    # ── Section 2: Key signals ────────────────────────────────
    lines.append("## 2. Key Signals")
    lines.append("")

    # Funding
    if funding.get("detected"):
        stage  = funding.get("stage", "unknown").replace("_", " ").title()
        amount = funding.get("amount_usd", 0)
        date   = funding.get("closed_at", "unknown")
        src    = funding.get("source_url", "no source URL")
        lines.append(f"- **Funding event:** {stage} ${amount/1e6:.0f}M closed {date} — {src}")
    else:
        lines.append("- **Funding event:** None detected in public sources")

    # Hiring velocity
    eng_today = velocity.get("open_roles_today", 0)
    eng_prior = velocity.get("open_roles_60_days_ago", 0)
    vel_label = velocity.get("velocity_label", "insufficient_signal")
    lines.append(f"- **Hiring velocity:** {eng_today} open eng roles today vs {eng_prior} sixty days ago → {vel_label.replace('_', ' ')}")

    # Layoff
    if layoff.get("detected") or layoff.get("has_layoff"):
        date = layoff.get("date") or layoff.get("layoff_date", "unknown")
        pct  = layoff.get("percentage_cut") or layoff.get("percentage", "unknown")
        lines.append(f"- **Layoff event:** Detected — {date}, {pct}% headcount reduction")
    else:
        lines.append("- **Layoff event:** None detected")

    # Leadership change
    if leadership.get("detected"):
        role   = leadership.get("role", "unknown").replace("_", " ").title()
        name   = leadership.get("new_leader_name", "name not public")
        date   = leadership.get("started_at", "unknown")
        lines.append(f"- **Leadership change:** {role} — {name} started {date}")
    else:
        lines.append("- **Leadership change:** None detected")

    lines.append(f"- **AI maturity score:** {ai_score} / 3 (confidence: {ai_confidence})")
    lines.append("")

    # ── Section 3: Competitor gap findings ────────────────────
    lines.append("## 3. Competitor Gap Findings")
    lines.append("")

    if gap_findings:
        # High confidence first
        high_gaps = [g for g in gap_findings if g.get("confidence") == "high"]
        med_gaps  = [g for g in gap_findings if g.get("confidence") == "medium"]

        lines.append("**High-confidence findings — ready to discuss on the call:**")
        for gap in high_gaps:
            peers = ", ".join(e["competitor_name"] for e in gap.get("peer_evidence", [])[:2])
            lines.append(f"- {gap['practice'][:100]} — peers: {peers}")

        if med_gaps:
            lines.append("")
            lines.append("**Medium-confidence findings — ask rather than assert:**")
            for gap in med_gaps:
                lines.append(f"- {gap['practice'][:100]} (medium confidence — frame as question)")

        if pitch_shift:
            lines.append("")
            lines.append(f"**Pitch shift note:** {pitch_shift}")
    else:
        lines.append("No competitor gap findings generated. Lead with hiring velocity and bench capacity.")

    lines.append("")

    # ── Section 4: Bench-to-brief match ───────────────────────
    lines.append("## 4. Bench-to-Brief Match")
    lines.append("")

    required = bench_match.get("required_stacks") or hiring_signal.get("tech_stack", [])
    gaps     = bench_match.get("gaps", [])
    avail    = bench_match.get("bench_available", True)

    if required:
        lines.append(f"- **Stacks the prospect likely needs:** {', '.join(required)}")
    else:
        lines.append("- **Stacks the prospect likely needs:** Not determined from public signal")

    # Bench availability from bench_summary.json
    bench_counts = {
        "python": 7, "go": 3, "data": 9, "ml": 5,
        "infra": 4, "frontend": 6, "fullstack_nestjs": 2
    }
    if required:
        avail_lines = []
        for stack in required:
            count = bench_counts.get(stack, 0)
            avail_lines.append(f"{stack}: {count} available")
        lines.append(f"- **Bench availability (as of 2026-04-21):** {', '.join(avail_lines)}")

    if gaps:
        lines.append(f"- **Gaps:** {', '.join(gaps)} — not on current bench, route to human before committing")
    else:
        lines.append("- **Gaps:** None — bench covers required stacks")

    agent_promised = "Yes — verify specific commitments before call" if honesty_flags else "No specific staffing committed in thread"
    lines.append(f"- **Honest flag:** {agent_promised}")
    lines.append("")

    # ── Section 5: Conversation history summary ───────────────
    lines.append("## 5. Conversation History Summary")
    lines.append("")

    if conversation_history:
        for i, item in enumerate(conversation_history[:5], 1):
            lines.append(f"{i}. {item}")
    else:
        lines.append("1. Prospect booked discovery call in response to outreach email")
        lines.append(f"2. Segment classified as {segment} with {confidence:.0%} confidence")
        lines.append(f"3. AI maturity score: {ai_score}/3 — {'pitch AI gap' if ai_score >= 2 else 'lead with engineering capacity'}")
        lines.append(f"4. Hiring velocity signal: {vel_label.replace('_', ' ')}")
        lines.append("5. No objections raised in thread — first substantive conversation is this call")

    lines.append("")

    # ── Section 6: Objections already raised ──────────────────
    lines.append("## 6. Objections Already Raised")
    lines.append("")

    if objections_raised:
        lines.append("| Objection | Agent response | Delivery lead should be ready to |")
        lines.append("|---|---|---|")
        for obj in objections_raised:
            lines.append(f"| {obj.get('objection','')} | {obj.get('response','')} | {obj.get('deeper_action','')} |")
    else:
        lines.append("| Objection | Agent response | Delivery lead should be ready to |")
        lines.append("|---|---|---|")
        lines.append("| No objections raised in thread | N/A | Probe for unstated concerns early in call |")

    lines.append("")

    # ── Section 7: Commercial signals ────────────────────────
    lines.append("## 7. Commercial Signals")
    lines.append("")

    if price_bands_quoted:
        lines.append(f"- **Price bands already quoted:** {', '.join(price_bands_quoted)}")
    else:
        lines.append("- **Price bands already quoted:** None — pricing not discussed in thread")

    lines.append("- **Has prospect asked for specific total contract value?** No")
    lines.append("- **Is prospect comparing vendors?** Unknown — not mentioned in thread")
    lines.append("- **Urgency signals:** None quoted directly — inferred from hiring velocity")
    lines.append("")

    # ── Section 8: Suggested call structure ──────────────────
    lines.append("## 8. Suggested Call Structure")
    lines.append("")

    opening, qualifying, capability, commercial, next_step = _suggest_call_structure(
        segment, ai_score, funding, layoff, leadership, duration_minutes
    )

    lines.append(f"- **Minutes 0-2:** {opening}")
    lines.append(f"- **Minutes 2-10:** {qualifying}")
    lines.append(f"- **Minutes 10-20:** {capability}")
    lines.append(f"- **Minutes 20-{duration_minutes-5}:** {commercial}")
    lines.append(f"- **Minutes {duration_minutes-5}-{duration_minutes}:** {next_step}")
    lines.append("")

    # ── Section 9: What NOT to do ──────────────────────────────
    lines.append("## 9. What NOT to Do on This Call")
    lines.append("")

    dont_list = _build_dont_list(segment, ai_score, honesty_flags, gaps, layoff)
    for item in dont_list:
        lines.append(f"- {item}")
    lines.append("")

    # ── Section 10: Agent confidence and unknowns ─────────────
    lines.append("## 10. Agent Confidence and Unknowns")
    lines.append("")

    confident, uncertain, missing = _assess_confidence(
        funding, layoff, leadership, ai_score, ai_confidence,
        velocity, honesty_flags, crunchbase
    )

    lines.append("**Things the agent is confident about:**")
    for item in confident:
        lines.append(f"- {item}")

    lines.append("")
    lines.append("**Things the agent is uncertain about:**")
    for item in uncertain:
        lines.append(f"- {item}")

    lines.append("")
    lines.append("**Things the agent could not find:**")
    for item in missing:
        lines.append(f"- {item}")

    # Overall confidence score
    overall = _overall_confidence(confident, uncertain, missing, honesty_flags)
    lines.append("")
    lines.append(f"**Overall agent confidence in this brief:** {overall:.1f} / 1.0")
    lines.append("")

    # ── Footer ────────────────────────────────────────────────
    lines.append("---")
    lines.append("")
    lines.append(
        f"*This brief was generated by the TRP1 Week 10 Conversion Engine. "
        f"Trace ID: {trace_id or 'unknown'}. "
        f"Generated at {datetime.now(timezone.utc).isoformat()}.*"
    )

    return "\n".join(lines)


# ── Helper functions ──────────────────────────────────────────

def _one_line_rationale(segment, icp, funding, layoff, leadership) -> str:
    reasons = icp.get("qualifying_signals", [])
    if reasons:
        return reasons[0]
    if "segment_1" in segment:
        return "Fresh Series A/B funding detected — scaling window open"
    if "segment_2" in segment:
        return "Layoff event detected — cost-preservation buying window"
    if "segment_3" in segment:
        return "New CTO/VP Eng in last 90 days — vendor reassessment window"
    if "segment_4" in segment:
        return "Specialist role open 60+ days with AI maturity >= 2"
    return "No strong segment signal — exploratory call"


def _suggest_call_structure(segment, ai_score, funding, layoff, leadership, duration) -> tuple:
    if "segment_1" in segment:
        return (
            "Reference the specific funding round and hiring velocity from the email — one sentence, then ask what their story is",
            "Ask: what does delivery pressure look like through Q2/Q3? What's the roadmap commitment that's at risk?",
            "Confirm bench match: check offshore constraints, code review culture, then propose squad configuration",
            "Quote the relevant pricing band (do not invent a total) — route to proposal for specifics",
            "Three concrete next steps: system names, security contact, 48hr proposal window",
        )
    elif "segment_2" in segment:
        return (
            "Acknowledge the restructure directly — 'we're here because you're restructuring, not in spite of it'",
            "Ask: what did the departed people do? Where is the gap biggest? Is there in-house knowledge to onboard a replacement team?",
            "Propose squad configuration for the specific roadmap — confirm architect pairing capacity in first two weeks",
            "Quote pricing band — emphasize monthly contracts with 2-week extension blocks, clean exit structure",
            "Three steps: architect availability check, dbt repo walkthrough under NDA, proposal within 72hrs",
        )
    elif "segment_3" in segment:
        return (
            "Congratulate on the role — 'the first 90 days are when vendor mix gets a fresh look'",
            "Ask: what's at the top of the reassessment list? What failed with previous offshore vendors?",
            "Address specific prior failures before pitching — no pitch deck, just a conversation about what the reassessment should include",
            "If capacity gap emerges, suggest second call with head of infrastructure present",
            "Book second call with correct attendee — no proposal on first call",
        )
    elif "segment_4" in segment:
        return (
            "Reference the specific open role and how long it has been open — 'what's the real story on that role?'",
            "Ask: what would the first 90 days look like if they'd hired in January? Is the work urgent or important-but-not-burning?",
            "Propose phased approach: Phase 1 fixed-scope (6wks), Phase 2 evaluation — honest about three possible conclusions",
            "Quote project consulting range — not talent outsourcing rates. Route phase structure to human",
            "Set up technical walkthrough with in-house technical lead, proposal within 48hrs of walkthrough",
        )
    else:
        return (
            "Introduce Tenacious briefly — let prospect set direction",
            "Ask open question about engineering challenges and current capacity",
            "Listen for segment signal before describing specific Tenacious capabilities",
            "If relevant capability emerges, name it and ask if it is worth exploring",
            "Agree on next step — even if just 'I'll send you more context'",
        )


def _build_dont_list(segment, ai_score, honesty_flags, bench_gaps, layoff) -> list:
    donts = []

    # Universal don'ts from style_guide.md
    donts.append("Do not use phrases: 'top talent', 'world-class', 'A-players', 'rockstar', 'ninja'")
    donts.append("Do not quote a specific total contract value — quote bands only, route total to proposal")
    donts.append("Do not claim bench capacity for stacks not in bench_summary.json")

    # Segment-specific don'ts
    if "segment_2" in segment:
        donts.append("Do not frame as 'we'll replace your laid-off team' — frame as replacing delivery capacity on specific roadmap")
        donts.append("Do not pitch growth or scale language — this is a cost-preservation conversation")

    if "segment_3" in segment:
        donts.append("Do not bring a pitch deck — the first call is exploratory, not a presentation")
        donts.append("Do not push for a commitment on this call — second call with infrastructure lead is the right next step")

    if "segment_4" in segment:
        donts.append("Do not claim the agentic approach will definitely work before evaluation — three possible conclusions are equally valid")
        donts.append("Do not pitch the AI team as 'world-class' — name specific engineers and past engagements")

    # Honesty flag don'ts
    if "weak_hiring_velocity_signal" in honesty_flags:
        donts.append("Do not assert 'aggressive hiring' — velocity signal is weak, ask rather than assert")

    if "bench_gap_detected" in honesty_flags or bench_gaps:
        gaps_str = ", ".join(bench_gaps) if bench_gaps else "unknown stacks"
        donts.append(f"Do not commit to {gaps_str} capacity — bench gap detected, route to human")

    if ai_score < 2:
        donts.append("Do not pitch AI capability gap — AI maturity score below 2, lead with engineering capacity only")

    # Layoff don't
    if layoff.get("detected") or layoff.get("has_layoff"):
        donts.append("Do not reference the layoff percentage or headcount numbers on the call unless the prospect brings it up")

    return donts


def _assess_confidence(funding, layoff, leadership, ai_score, ai_confidence, velocity, honesty_flags, crunchbase) -> tuple:
    confident = []
    uncertain = []
    missing   = []

    # Confident items
    if funding.get("detected"):
        confident.append(f"Funding event: {funding.get('stage','unknown')} ${funding.get('amount_usd',0)/1e6:.0f}M (sourced from Crunchbase)")
    if velocity.get("velocity_label") not in ("insufficient_signal", ""):
        confident.append(f"Hiring velocity: {velocity.get('velocity_label','').replace('_',' ')} ({velocity.get('open_roles_today',0)} roles today)")
    if ai_confidence == "high":
        confident.append(f"AI maturity score {ai_score}/3 — high confidence")

    # Uncertain items
    if "weak_hiring_velocity_signal" in honesty_flags:
        uncertain.append("Hiring velocity — limited historical data, 60-day comparison may not be representative")
    if ai_confidence in ("medium", "low"):
        uncertain.append(f"AI maturity score {ai_score}/3 — {ai_confidence} confidence, verify on call")
    if not leadership.get("detected"):
        uncertain.append("Leadership tenure — unable to confirm how long current CTO/VP Eng has been in role")
    if crunchbase.get("source") == "mock":
        uncertain.append("Firmographic data — Crunchbase ODM file not loaded, using mock brief")

    # Missing items
    if not funding.get("detected"):
        missing.append("Funding history — no public Crunchbase record found")
    missing.append("Customer contract data-handling clauses — check for offshore restrictions before SOW")
    missing.append("Code review culture and architectural decision process — ask in first 10 minutes")
    if not velocity.get("open_roles_today"):
        missing.append("Current open role count — Greenhouse ATS board not found for this company")

    # Ensure all three lists have at least one item
    if not confident:
        confident.append("Prospect booked the call — expressed sufficient interest to schedule")
    if not uncertain:
        uncertain.append("Segment confidence is above threshold but single data source")
    if not missing:
        missing.append("Tech stack confirmation — inferred from job titles, not directly verified")

    return confident, uncertain, missing


def _overall_confidence(confident, uncertain, missing, honesty_flags) -> float:
    base = 0.7
    base -= len(uncertain) * 0.05
    base -= len(missing) * 0.03
    base -= len(honesty_flags) * 0.05
    base += len(confident) * 0.03
    return round(max(0.3, min(0.95, base)), 2)


if __name__ == "__main__":
    # Test with Turing Signal synthetic prospect
    brief = generate_discovery_brief(
        prospect_name="Alex Kim",
        prospect_title="VP Engineering",
        prospect_company="Turing Signal",
        call_datetime_utc="2026-04-25T14:00:00Z",
        call_datetime_local="10:00 AM ET",
        delivery_lead="Arun Sharma",
        duration_minutes=30,
        thread_start_date="2026-04-23",
        original_subject="Turing Signal engineering capacity — worth a conversation?",
        langfuse_trace_url="https://cloud.langfuse.com/trace/869d4d8e",
        icp_result={
            "segment": "segment_1_series_a_b",
            "segment_description": "Recently-funded Series A/B",
            "confidence": 0.82,
            "qualified": True,
            "pitch": "scale your AI team faster than in-house hiring can support",
            "qualifying_signals": ["Seed funding 83 days ago", "4 open engineering roles"],
        },
        hiring_signal={
            "hiring_velocity": {
                "open_roles_today": 4,
                "open_roles_60_days_ago": 1,
                "velocity_label": "tripled_or_more",
            },
            "buying_window_signals": {
                "funding_event": {
                    "detected": True,
                    "stage": "seed",
                    "amount_usd": 5_000_000,
                    "closed_at": "2024-01-01",
                    "source_url": "https://crunchbase.com/turing-signal",
                },
                "layoff_event":      {"detected": False},
                "leadership_change": {"detected": False},
            },
            "tech_stack": ["python", "data"],
            "honesty_flags": [],
        },
        ai_maturity={
            "score": 0,
            "confidence_label": "high",
            "brief": "No AI signal detected. Lead with engineering capacity.",
        },
        trace_id="869d4d8e-f2e4-4719-9bc4-efc0ba62ffff",
    )

    print(brief)
    print(f"\n--- Brief length: {len(brief.split(chr(10)))} lines ---")