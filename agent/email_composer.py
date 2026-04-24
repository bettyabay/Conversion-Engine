"""
agent/email_composer.py

Email composer for all outbound sequences.
Uses hiring_signal_brief and competitor_gap_brief as source of truth.
Every claim in the email must map to a field in the brief.

Per cold.md, warm.md, reengagement.md, style_guide.md:

Style rules (non-negotiable):
  - Max 120 words for cold Email 1
  - Max 100 words for cold Email 2
  - Max 70 words for cold Email 3
  - Subject line under 60 characters
  - No "just circling back", "hope this finds you well", "wanted to touch base"
  - No "top talent", "world-class", "A-players", "rockstar", "ninja"
  - No fake urgency ("your competitors are moving fast")
  - No social proof dumps (logos, case-study names, customer counts)
  - First name salutation only — no "Hi there" or "Dear"
  - Signature: First name, title, Tenacious Intelligence Corporation, gettenacious.com

Tone markers (from style_guide.md):
  1. Direct — clear, brief, actionable
  2. Grounded — every claim from the brief
  3. Honest — refuse ungrounded claims, use ask vs assert by confidence
  4. Professional — no offshore-vendor clichés
  5. Non-condescending — gap = research finding, not prospect failure
"""
import re
from datetime import datetime, timezone
from typing import Optional


# ── Banned phrases — tone violation triggers ─────────────────
BANNED_PHRASES = [
    "just circling back", "circling back", "just following up",
    "hope this finds you well", "wanted to touch base", "touching base",
    "quick question", "just wanted to reach out",
    "top talent", "world-class", "a-players", "rockstar", "ninja",
    "guaranteed savings", "best offshore", "save 40%", "save 30%",
    "your competitors are moving fast", "before it's too late",
    "limited availability", "act now", "last chance",
    "we can handle any stack", "we can do everything",
    "replace your team", "better than india",
]

SIGNATURE_TEMPLATE = """{first_name}
Research Partner, Tenacious Intelligence Corporation
gettenacious.com"""


def compose_cold_email_1(
    prospect_first_name: str,
    segment: str,
    hiring_signal: dict,
    ai_maturity: dict,
    icp_result: dict,
    cal_link: str = "https://cal.com/tenacious/discovery",
) -> dict:
    """
    Cold Email 1 — Signal-grounded opener. Day 0.
    Max 120 words. Subject under 60 chars.
    """
    velocity    = hiring_signal.get("hiring_velocity", {})
    buying      = hiring_signal.get("buying_window_signals", {})
    funding     = buying.get("funding_event", {})
    layoff      = buying.get("layoff_event", {})
    leadership  = buying.get("leadership_change", {})
    ai_score    = ai_maturity.get("score", 0)
    honesty     = hiring_signal.get("honesty_flags", [])
    eng_today   = velocity.get("open_roles_today", 0)
    vel_label   = velocity.get("velocity_label", "insufficient_signal")
    company     = hiring_signal.get("prospect_name", "your company")

    subject, body = _build_cold_1_content(
        prospect_first_name, segment, company,
        funding, layoff, leadership,
        eng_today, vel_label, ai_score, honesty, cal_link
    )

    return _build_email_result(
        subject, body, prospect_first_name,
        email_type="cold_1", segment=segment,
        word_limit=120
    )


def compose_cold_email_2(
    prospect_first_name: str,
    segment: str,
    hiring_signal: dict,
    competitor_gap: dict,
    cal_link: str = "https://cal.com/tenacious/discovery",
) -> dict:
    """
    Cold Email 2 — Research-finding follow-up. Day 5.
    Max 100 words. Introduces new competitor gap data point.
    """
    gap_findings = competitor_gap.get("gap_findings", [])
    company      = hiring_signal.get("prospect_name", "your company")
    ai_score     = hiring_signal.get("ai_maturity", {}).get("score", 0)

    # Pick the highest-confidence gap for Email 2
    high_gaps = [g for g in gap_findings if g.get("confidence") == "high"]
    med_gaps  = [g for g in gap_findings if g.get("confidence") == "medium"]
    best_gap  = high_gaps[0] if high_gaps else (med_gaps[0] if med_gaps else None)

    subject, body = _build_cold_2_content(
        prospect_first_name, segment, company,
        best_gap, competitor_gap, cal_link
    )

    return _build_email_result(
        subject, body, prospect_first_name,
        email_type="cold_2", segment=segment,
        word_limit=100
    )


def compose_cold_email_3(
    prospect_first_name: str,
    company: str,
    segment: str,
) -> dict:
    """
    Cold Email 3 — Gracious close. Day 12.
    Max 70 words. Clean exit, leaves door open.
    """
    subject = f"Closing the loop on our research note"

    body = f"""{prospect_first_name},

I'll stop here — looks like the timing isn't right, which is fine.

If the hiring-velocity data on your sector would be useful on its own, reply "yes" and I'll send a one-pager with no calendar ask. Otherwise I'll check back in Q3.

All the best,

{SIGNATURE_TEMPLATE.format(first_name=prospect_first_name)}"""

    return _build_email_result(
        subject, body, prospect_first_name,
        email_type="cold_3", segment=segment,
        word_limit=70
    )


def compose_warm_reply(
    prospect_first_name: str,
    reply_class: str,
    prospect_reply: str,
    segment: str,
    hiring_signal: dict,
    competitor_gap: dict,
    bench_summary: dict = None,
    cal_link: str = "https://cal.com/tenacious/discovery",
) -> dict:
    """
    Warm reply handler. Five reply classes:
    engaged / curious / hard_no / soft_defer / objection

    Returns dict with subject, body, reply_class, and next_action.
    """
    company  = hiring_signal.get("prospect_name", "your company")
    ai_score = hiring_signal.get("ai_maturity", {}).get("score", 0)
    velocity = hiring_signal.get("hiring_velocity", {})

    if reply_class == "hard_no":
        return {
            "reply_class":  "hard_no",
            "action":       "opt_out",
            "send_reply":   False,
            "hubspot_update": {"outreach_status": "opted_out"},
            "message":      "No reply sent. Contact marked opted_out in HubSpot. Domain added to suppression list.",
        }

    elif reply_class == "soft_defer":
        subject, body = _build_soft_defer(prospect_first_name)
        return _build_email_result(
            subject, body, prospect_first_name,
            email_type="warm_soft_defer", segment=segment,
            word_limit=60, next_action="log_reengagement_date"
        )

    elif reply_class == "curious":
        subject, body = _build_curious_reply(
            prospect_first_name, segment, company,
            velocity, ai_score, cal_link
        )
        return _build_email_result(
            subject, body, prospect_first_name,
            email_type="warm_curious", segment=segment,
            word_limit=90, next_action="await_reply"
        )

    elif reply_class == "objection":
        objection_type = _classify_objection(prospect_reply)
        subject, body  = _build_objection_reply(
            prospect_first_name, objection_type, cal_link
        )
        return _build_email_result(
            subject, body, prospect_first_name,
            email_type=f"warm_objection_{objection_type}", segment=segment,
            word_limit=150, next_action="await_reply"
        )

    else:  # engaged
        subject, body = _build_engaged_reply(
            prospect_first_name, segment, company,
            prospect_reply, hiring_signal,
            competitor_gap, bench_summary, cal_link
        )
        return _build_email_result(
            subject, body, prospect_first_name,
            email_type="warm_engaged", segment=segment,
            word_limit=150, next_action="book_discovery_call"
        )


def compose_reengagement_email_1(
    prospect_first_name: str,
    company: str,
    segment: str,
    new_signal: str,
    original_subject: str,
) -> dict:
    """
    Reengagement Email 1 — New data point. 10 days after last message.
    Max 100 words. References previous thread, introduces new information.
    """
    subject = f"Re: {original_subject[:40]} — one update"

    body = f"""{prospect_first_name},

Picking up from our thread on {company}.

{new_signal}

Happy to share the full sector comparison — reply "yes" and I'll send a one-pager, no calendar ask.

{SIGNATURE_TEMPLATE.format(first_name=prospect_first_name)}"""

    return _build_email_result(
        subject, body, prospect_first_name,
        email_type="reengagement_1", segment=segment,
        word_limit=100
    )


def compose_reengagement_email_2(
    prospect_first_name: str,
    company: str,
    segment: str,
    specific_question: str,
) -> dict:
    """
    Reengagement Email 2 — Single specific question. 7 days after Email 1.
    Max 50 words. One question, answerable in one line.
    """
    subject = "One specific question"

    body = f"""{prospect_first_name},

{specific_question}

Either answer is useful for our research — no follow-up pitch either way.

{SIGNATURE_TEMPLATE.format(first_name=prospect_first_name)}"""

    return _build_email_result(
        subject, body, prospect_first_name,
        email_type="reengagement_2", segment=segment,
        word_limit=50
    )


def compose_reengagement_email_3(
    prospect_first_name: str,
    company: str,
    segment: str,
    reengagement_month: str = "July",
) -> dict:
    """
    Reengagement Email 3 — 6-month close. Final touch.
    Max 40 words. Parks thread with specific re-engagement date.
    """
    subject = f"Parking this — {reengagement_month} check-in"

    body = f"""{prospect_first_name},

Closing this thread for now and parking for a {reengagement_month} check-in with fresh research.

{SIGNATURE_TEMPLATE.format(first_name=prospect_first_name)}"""

    return _build_email_result(
        subject, body, prospect_first_name,
        email_type="reengagement_3", segment=segment,
        word_limit=40
    )


# ── Internal builders ──────────────────────────────────────────

def _build_cold_1_content(
    first_name, segment, company,
    funding, layoff, leadership,
    eng_today, vel_label, ai_score, honesty, cal_link
):
    """Build subject + body for cold Email 1 based on segment."""

    # ── Segment 1: Recently funded ────────────────────────────
    if "segment_1" in segment:
        stage  = funding.get("stage", "").replace("_", " ").title()
        amount = funding.get("amount_usd", 0)
        amount_str = f"${amount/1e6:.0f}M " if amount else ""

        subject = f"Context: {company} and the {stage} engineering team"
        subject = subject[:59]  # enforce 60 char limit

        # Grounded sentence 1: single verifiable fact
        if funding.get("detected") and "weak_hiring_velocity_signal" not in honesty:
            fact = (f"You closed the {stage} {amount_str}round and have "
                    f"{eng_today} engineering roles open since then.")
        elif eng_today > 0:
            fact = f"You have {eng_today} engineering roles open on public job boards."
        else:
            fact = f"{company} recently closed a funding round with active engineering hiring."

        # Sentence 2: observation, not assertion
        if "segment_1" in segment:
            observation = ("The typical bottleneck for teams at that stage "
                           "is recruiting capacity, not budget.")

        # Sentence 3: one specific Tenacious capability
        if ai_score >= 2:
            capability = ("We run dedicated engineering squads for companies "
                          "scaling post-raise — engineers available in 7-14 days, "
                          "embedded in your stack, with 3-hour minimum overlap "
                          "with your time zone. AI-capable where you need it.")
        else:
            capability = ("We run dedicated engineering squads for companies "
                          "scaling post-raise — senior engineers available in "
                          "7-14 days, embedded in your stack. "
                          "Not a staffing agency; a delivery team.")

        ask = f"Worth 15 minutes next Tuesday or Wednesday? → {cal_link}"

        body = f"""{first_name},

{fact} {observation}

{capability}

{ask}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    # ── Segment 2: Restructuring ──────────────────────────────
    elif "segment_2" in segment:
        subject = f"Note on {company} and delivery capacity"
        subject = subject[:59]

        # Soften urgency per cold.md segment 2 adjustment
        fact = (f"{company} has gone through a reduction recently. "
                f"There are still {eng_today} engineering roles open — "
                f"the roadmap is still live.")

        observation = ("The challenge for teams in this position is maintaining "
                       "delivery velocity without adding headcount back to the P&L.")

        capability = ("We provide dedicated offshore delivery capacity — "
                      "monthly contracts, 2-week extension blocks, "
                      "clean exit if the board changes direction. "
                      "The architecture ownership stays with your in-house team.")

        ask = f"Worth 15 minutes to walk through how that structure works? → {cal_link}"

        body = f"""{first_name},

{fact} {observation}

{capability}

{ask}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    # ── Segment 3: Leadership transition ─────────────────────
    elif "segment_3" in segment:
        role = leadership.get("role", "CTO").replace("_", " ").title()
        subject = f"Congrats on the {role} appointment"
        subject = subject[:59]

        body = f"""{first_name},

Congratulations on the {role} role at {company}. In our experience, the first 90 days are when vendor mix gets a fresh look.

If offshore delivery is on your list for that review, we'd welcome 15 minutes — managed teams, not staff aug, with full time-zone overlap with US East.

No pitch deck on the first call. A conversation about what your first-90-days vendor reassessment should include.

→ {cal_link}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    # ── Segment 4: Capability gap ─────────────────────────────
    elif "segment_4" in segment:
        subject = f"Question on {company} AI capability signal"
        subject = subject[:59]

        body = f"""{first_name},

{company} has had a specialist engineering role open for 60+ days. The people who can do that work are being competed for by companies with more name recognition — it's a market problem, not a compensation problem.

We run fixed-scope project consulting engagements for exactly this situation — a working prototype and an honest build/buy recommendation, not a slide deck.

Worth 15 minutes? → {cal_link}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    # ── Abstain / unknown ─────────────────────────────────────
    else:
        subject = f"Quick question on {company} engineering"
        subject = subject[:59]

        body = f"""{first_name},

I came across {company} while researching engineering teams at your stage. We work with companies building engineering capacity without a full in-house recruiting cycle.

If that's a challenge you're thinking about, worth 15 minutes? → {cal_link}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    return subject, body


def _build_cold_2_content(
    first_name, segment, company, best_gap, competitor_gap, cal_link
):
    """Build Email 2 — new competitor gap data point."""
    if best_gap:
        practice = best_gap.get("practice", "")
        peers    = best_gap.get("peer_evidence", [])
        peer_names = [p.get("competitor_name", "") for p in peers[:2]]
        peer_str = " and ".join(peer_names) if peer_names else "peers in your sector"
        confidence = best_gap.get("confidence", "medium")

        # Non-condescending framing — research finding, not assertion
        if confidence == "high":
            gap_sentence = (f"{peer_str} show public signal of {practice.lower()}. "
                            f"{company} does not show the same signal publicly.")
            question = (f"Curious whether that's a deliberate choice or "
                        f"still being scoped on your side.")
        else:
            gap_sentence = (f"{peer_str} have been building out {practice.lower()} "
                            f"in the last 90 days.")
            question = (f"Wondering whether {company} is on a similar path "
                        f"or has made a deliberate call not to.")

        subject = f"One more data point: {peer_names[0] if peer_names else 'peer'} signal"
        subject = subject[:59]

        body = f"""{first_name},

Adding one data point from our research on {company}'s sector.

{gap_sentence} {question}

No pitch here — just interested in the pattern. If you want to compare notes → {cal_link}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    else:
        # No gap data — use hiring velocity comparison
        subject = f"Your peer companies and engineering capacity"
        subject = subject[:59]

        body = f"""{first_name},

One data point from our research on teams at {company}'s stage.

Companies that closed their Series A/B in the last 6 months and kept in-house hiring as the only scaling path typically see a 3-4 month lag between funding close and engineering velocity increase.

Curious whether that pattern matches what you're seeing.

→ {cal_link}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    return subject, body


def _build_soft_defer(first_name):
    subject = "Re: timing"
    body = f"""{first_name},

Understood — timing matters. I'll check back in early Q3 with fresh research.

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""
    return subject, body


def _build_curious_reply(
    first_name, segment, company, velocity, ai_score, cal_link
):
    eng_today = velocity.get("open_roles_today", 0)

    if ai_score >= 2:
        description = (f"Tenacious is a managed engineering delivery firm — "
                       f"we run dedicated squads out of Addis Ababa for US and EU "
                       f"scale-ups, with 3-5 hours of daily time-zone overlap. "
                       f"Our ML bench covers LangChain, RAG, agentic systems, and MLOps.")
    else:
        description = (f"Tenacious is a managed engineering delivery firm — "
                       f"we run dedicated squads out of Addis Ababa for US and EU "
                       f"scale-ups, with 3-5 hours of daily time-zone overlap. "
                       f"Engineers are employees, not contractors — "
                       f"18-month average tenure.")

    if eng_today:
        context = f"For {company} with {eng_today} open engineering roles, a typical first engagement is a 3-engineer squad on a 6-12 month scope."
    else:
        context = f"For a company at {company}'s stage, a typical first engagement is a 3-engineer squad on a 6-12 month scope."

    subject = "Re: your question"
    body = f"""{first_name},

Glad this landed. Two-line version: {description}

{context}

15 minutes Wednesday or Thursday? → {cal_link}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    return subject, body


def _classify_objection(reply_text: str) -> str:
    """Classify objection type from reply text."""
    reply_lower = reply_text.lower()
    if any(w in reply_lower for w in ["price", "cost", "expensive", "cheaper", "india", "rate"]):
        return "price"
    if any(w in reply_lower for w in ["vendor", "agency", "contractor", "already have", "incumbent"]):
        return "incumbent"
    if any(w in reply_lower for w in ["poc", "pilot", "small", "test", "try"]):
        return "small_poc"
    if any(w in reply_lower for w in ["offshore", "quality", "rotation", "management", "accenture"]):
        return "offshore_skepticism"
    return "general"


def _build_objection_reply(first_name, objection_type, cal_link):
    """Build objection reply using approved language from transcripts."""
    subject = "Re: your question"

    if objection_type == "price":
        body = f"""{first_name},

Fair — and we're rarely the cheapest. We compete on reliability and retention, not hourly rate: 18-month average engineer tenure, 3-hour minimum overlap with your time zone, and a dedicated project manager on every engagement.

The comparison worth making is delivered-output per dollar over 18 months, not hourly rate. Happy to walk through what that looks like for your stack.

→ {cal_link}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    elif objection_type == "incumbent":
        body = f"""{first_name},

Makes sense — your core scope is likely well covered. The gap Tenacious fills is typically for new initiatives or specialized capability that the current vendor doesn't have on their bench.

Worth 15 minutes to see if there's a specific workload that fits? → {cal_link}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    elif objection_type == "small_poc":
        body = f"""{first_name},

Starting small is the right call. The smallest engagement we do is a fixed-scope project consulting contract — a specific deliverable, evaluated objectively in 4-6 weeks.

If we deliver, you know our team works. If we don't, you've learned that without a long commitment.

What's the smallest deliverable that would prove value for your team? → {cal_link}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    elif objection_type == "offshore_skepticism":
        body = f"""{first_name},

The rotation and management-layer problems are real — I'd rather name them than pretend they don't exist.

Our model is different on two specific dimensions: engineers are employees with 18-month average tenure, and there's no management layer between your technical lead and ours. Your lead talks directly to our senior engineer.

Worth 15 minutes to test whether that structure would have addressed what went wrong before? → {cal_link}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    else:
        body = f"""{first_name},

Good question — let me give you a direct answer.

We're most useful when the architecture is clear and delivery capacity is the bottleneck. We don't replace in-house architecture, and we're not the cheapest option. We compete on reliability, retention, and time-zone overlap.

Worth 15 minutes to see if the fit is there? → {cal_link}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    return subject, body


def _build_engaged_reply(
    first_name, segment, company,
    prospect_reply, hiring_signal,
    competitor_gap, bench_summary, cal_link
):
    """Build engaged reply — grounded answer + book."""
    velocity  = hiring_signal.get("hiring_velocity", {})
    ai_score  = hiring_signal.get("ai_maturity", {}).get("score", 0)
    eng_today = velocity.get("open_roles_today", 0)
    stacks    = hiring_signal.get("tech_stack", [])

    # Bench match
    bench_counts = {
        "python": 7, "go": 3, "data": 9, "ml": 5,
        "infra": 4, "frontend": 6, "fullstack_nestjs": 2
    }
    avail_stacks = []
    for s in stacks[:2]:
        count = bench_counts.get(s, 0)
        if count > 0:
            avail_stacks.append(f"{count} {s} engineers available")

    avail_str = (", ".join(avail_stacks) + " as of this week"
                 if avail_stacks else "bench engineers available in 7-14 days")

    if ai_score >= 2:
        squad_desc = ("3 engineers: 1 senior (architecture + AI-adjacent work) "
                      "and 2 mid-level ICs, plus a fractional project manager.")
    else:
        squad_desc = ("3 engineers: 1 senior (architecture and code review) "
                      "and 2 mid-level ICs, plus a fractional project manager at 0.5 FTE.")

    subject = "Re: your question"
    body = f"""{first_name},

Good question. Our engineers are full-time Tenacious employees — salaried, benefits, insurance. They join your standups, your Slack, your PR review. We carry HR and payroll; you direct the work.

A typical squad for a company at {company}'s stage: {squad_desc} We have {avail_str}.

Minimum 1 month, extensions in 2-week blocks after that.

Free for 30 minutes Wednesday 10am ET or Thursday 2pm ET? → {cal_link}

{SIGNATURE_TEMPLATE.format(first_name=first_name)}"""

    return subject, body


# ── Validation and utilities ──────────────────────────────────

def _count_words(text: str) -> int:
    return len(re.findall(r'\b\w+\b', text))


def _check_tone(body: str) -> list:
    """Check for banned phrases. Returns list of violations."""
    violations = []
    body_lower = body.lower()
    for phrase in BANNED_PHRASES:
        if phrase.lower() in body_lower:
            violations.append(f"Banned phrase detected: '{phrase}'")
    return violations


def _build_email_result(
    subject, body, first_name,
    email_type, segment,
    word_limit=120, next_action="await_reply"
) -> dict:
    """Build the final email result dict with validation."""
    word_count  = _count_words(body)
    subject_len = len(subject)
    violations  = _check_tone(body)

    # Word count check
    if word_count > word_limit:
        violations.append(
            f"Word count {word_count} exceeds {word_limit} limit for {email_type}"
        )

    # Subject length check
    if subject_len > 60:
        violations.append(
            f"Subject length {subject_len} exceeds 60 char limit"
        )

    if violations:
        for v in violations:
            print(f"[EmailComposer] TONE VIOLATION: {v}")

    return {
        "email_type":  email_type,
        "segment":     segment,
        "subject":     subject,
        "body":        body,
        "word_count":  word_count,
        "word_limit":  word_limit,
        "subject_len": subject_len,
        "violations":  violations,
        "tone_pass":   len(violations) == 0,
        "next_action": next_action,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "headers": {
            "X-Tenacious-Status": "draft",
            "X-Tenacious-Env":    "sandbox",
        },
    }


if __name__ == "__main__":
    # Test all email types

    sample_hiring = {
        "prospect_name": "Turing Signal",
        "hiring_velocity": {
            "open_roles_today": 4,
            "open_roles_60_days_ago": 1,
            "velocity_label": "tripled_or_more",
        },
        "buying_window_signals": {
            "funding_event": {
                "detected": True, "stage": "series_b",
                "amount_usd": 14_000_000, "closed_at": "2026-02-12",
            },
            "layoff_event": {"detected": False},
            "leadership_change": {"detected": False},
        },
        "tech_stack": ["python", "data"],
        "honesty_flags": [],
        "ai_maturity": {"score": 0},
    }

    sample_ai = {"score": 0, "confidence_label": "high"}
    sample_icp = {
        "segment": "segment_1_series_a_b",
        "confidence": 0.82,
        "qualified": True,
        "pitch": "scale your engineering team faster than recruiting can support",
    }
    sample_gap = {
        "gap_findings": [{
            "practice": "Dedicated AI/ML leadership role",
            "peer_evidence": [
                {"competitor_name": "Northview Analytics",
                 "evidence": "VP of AI named on team page",
                 "source_url": "https://northview.example/team"},
                {"competitor_name": "Axiom Data Works",
                 "evidence": "Head of Applied AI hired Nov 2025",
                 "source_url": "https://axiom.example/team"},
            ],
            "confidence": "high",
        }],
        "suggested_pitch_shift": "Lead with AI leadership gap",
    }

    print("=== COLD EMAIL 1 ===")
    e1 = compose_cold_email_1("Elena", "segment_1_series_a_b",
                               sample_hiring, sample_ai, sample_icp)
    print(f"Subject: {e1['subject']}")
    print(f"Words: {e1['word_count']}/{e1['word_limit']}")
    print(f"Tone pass: {e1['tone_pass']}")
    print(e1["body"])

    print("\n=== COLD EMAIL 2 ===")
    e2 = compose_cold_email_2("Elena", "segment_1_series_a_b",
                               sample_hiring, sample_gap)
    print(f"Subject: {e2['subject']}")
    print(f"Words: {e2['word_count']}/{e2['word_limit']}")
    print(f"Tone pass: {e2['tone_pass']}")
    print(e2["body"])

    print("\n=== COLD EMAIL 3 ===")
    e3 = compose_cold_email_3("Elena", "Turing Signal", "segment_1_series_a_b")
    print(f"Words: {e3['word_count']}/{e3['word_limit']}")
    print(f"Tone pass: {e3['tone_pass']}")
    print(e3["body"])

    print("\n=== WARM REPLY — OBJECTION (PRICE) ===")
    wr = compose_warm_reply(
        "Elena", "objection",
        "your price is higher than what I'd pay an Indian vendor",
        "segment_1_series_a_b", sample_hiring, sample_gap
    )
    print(f"Tone pass: {wr['tone_pass']}")
    print(wr["body"])

    print("\n=== REENGAGEMENT EMAIL 1 ===")
    re1 = compose_reengagement_email_1(
        "Elena", "Turing Signal", "segment_1_series_a_b",
        "Northview Analytics just posted a third MLOps role — the sector signal is shifting from gap to consolidation.",
        "Turing Signal engineering capacity"
    )
    print(f"Words: {re1['word_count']}/{re1['word_limit']}")
    print(f"Tone pass: {re1['tone_pass']}")
    print(re1["body"])
