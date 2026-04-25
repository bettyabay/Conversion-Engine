"""
agent/agents/outreach_composer.py

MessageAgent — produces the full 3-email cold sequence.
Wraps email_composer.py and passes drafts to GuardrailAgent.

This agent:
  1. Determines which email in the sequence to send (1, 2, or 3)
  2. Calls the correct composer function
  3. Passes the draft to GuardrailAgent for verdict
  4. Returns approved email or None if BLOCK_FINAL

Flow:
  MessageAgent → GuardrailAgent → PASS/WARN → email_handler.send_email()
                                → BLOCK → MessageAgent regenerates
"""
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

CAL_URL = os.getenv("CAL_URL", "https://cal.com/bethelhem-abay/discovery-call")


def run(
    prospect_name: str,
    company: str,
    email: str,
    segment: str,
    email_number: int,           # 1, 2, or 3
    hiring_signal: dict,
    competitor_gap: dict,
    ai_maturity: dict,
    icp_result: dict,
    sequence_type: str = "cold", # "cold" or "reengagement"
    reengagement_signal: str = "",
    specific_question: str = "",
    reengagement_month: str = "July",
) -> dict:
    """
    Produce an approved email for this prospect.

    Returns:
        dict with subject, body, tone_pass, word_count, guardrail_verdict
        or None if GuardrailAgent issues a BLOCK_FINAL verdict
    """
    from agent.email_composer import (
        compose_cold_email_1,
        compose_cold_email_2,
        compose_cold_email_3,
        compose_reengagement_email_1,
        compose_reengagement_email_2,
        compose_reengagement_email_3,
    )
    from agent.agents.quality_gate import run_with_retry

    # ── Compose the draft ────────────────────────────────────
    if sequence_type == "reengagement":
        if email_number == 1:
            draft = compose_reengagement_email_1(
                prospect_first_name=prospect_name,
                company=company,
                segment=segment,
                new_signal=reengagement_signal or f"{company} sector signal has shifted — worth a fresh look.",
                original_subject=f"{company} engineering capacity",
            )
        elif email_number == 2:
            draft = compose_reengagement_email_2(
                prospect_first_name=prospect_name,
                company=company,
                segment=segment,
                specific_question=specific_question or f"Is the engineering capacity gap something you're actively scoping at {company}?",
            )
        else:
            draft = compose_reengagement_email_3(
                prospect_first_name=prospect_name,
                company=company,
                segment=segment,
                reengagement_month=reengagement_month,
            )
    else:
        # Cold sequence
        if email_number == 1:
            draft = compose_cold_email_1(
                prospect_first_name=prospect_name,
                segment=segment,
                hiring_signal=hiring_signal,
                ai_maturity=ai_maturity,
                icp_result=icp_result,
                cal_link=CAL_URL,
            )
        elif email_number == 2:
            draft = compose_cold_email_2(
                prospect_first_name=prospect_name,
                segment=segment,
                hiring_signal=hiring_signal,
                competitor_gap=competitor_gap,
                cal_link=CAL_URL,
            )
        else:
            draft = compose_cold_email_3(
                prospect_first_name=prospect_name,
                company=company,
                segment=segment,
            )

    # ── Run through GuardrailAgent ──────────────────────────
    bench_summary = _load_bench_summary()
    guardrail_result = run_with_retry(
        email_dict=draft,
        hiring_signal=hiring_signal,
        bench_summary=bench_summary,
        max_retries=2,
    )

    verdict = guardrail_result.get("verdict", "PASS")

    print(f"[MessageAgent] {prospect_name} email_{email_number} → GuardrailAgent: {verdict}")

    if verdict == "BLOCK_FINAL":
        print(f"[MessageAgent] BLOCK_FINAL — email dropped for {email}")
        return None

    # Return the approved (possibly auto-corrected) email
    approved = guardrail_result.get("corrected_email") or draft
    approved["guardrail_verdict"]   = verdict
    approved["guardrail_corrections"] = guardrail_result.get("corrections", [])
    approved["attempts"]            = guardrail_result.get("attempts", 1)

    return approved


def _load_bench_summary() -> dict:
    """Load bench_summary.json for guardrail bench checks."""
    import json
    from pathlib import Path

    paths = [
        Path("seed/bench_summary.json"),
        Path("data/bench_summary.json"),
        Path("bench_summary.json"),
    ]
    for p in paths:
        if p.exists():
            return json.loads(p.read_text())

    # Hardcoded fallback from seed materials
    return {
        "stacks": {
            "python":  {"available_engineers": 7},
            "go":      {"available_engineers": 3},
            "data":    {"available_engineers": 9},
            "ml":      {"available_engineers": 5},
            "infra":   {"available_engineers": 4},
            "frontend": {"available_engineers": 6},
            "fullstack_nestjs": {"available_engineers": 2},
        }
    }


if __name__ == "__main__":
    # Test with Orrin Labs
    sample_hiring = {
        "prospect_name": "Orrin Labs",
        "hiring_velocity": {
            "open_roles_today": 11,
            "open_roles_60_days_ago": 4,
            "velocity_label": "doubled",
            "signal_confidence": 0.85,
        },
        "buying_window_signals": {
            "funding_event": {
                "detected": True,
                "stage": "series_b",
                "amount_usd": 14_000_000,
                "closed_at": "2026-02-12",
            },
            "layoff_event": {"detected": False},
            "leadership_change": {"detected": False},
        },
        "tech_stack": ["python", "data"],
        "honesty_flags": [],
        "ai_maturity": {"score": 2},
    }
    sample_icp = {
        "segment": "segment_1_series_a_b",
        "confidence": 0.82,
        "qualified": True,
        "pitch": "scale your engineering team faster than recruiting can support",
    }
    sample_ai = {"score": 2, "confidence_label": "high"}
    sample_gap = {
        "gap_findings": [{
            "practice": "Dedicated AI/ML leadership",
            "peer_evidence": [
                {"competitor_name": "Northview", "evidence": "VP of AI on team page", "source_url": "https://northview.example/team"},
                {"competitor_name": "Axiom", "evidence": "Head of AI hired Nov 2025", "source_url": "https://axiom.example/team"},
            ],
            "confidence": "high",
        }],
        "suggested_pitch_shift": "Lead with AI leadership gap",
    }

    result = run(
        prospect_name="Jordan",
        company="Orrin Labs",
        email="cto@orrin-labs.example",
        segment="segment_1_series_a_b",
        email_number=1,
        hiring_signal=sample_hiring,
        competitor_gap=sample_gap,
        ai_maturity=sample_ai,
        icp_result=sample_icp,
    )

    if result:
        print(f"\nSubject: {result['subject']}")
        print(f"Words: {result['word_count']}")
        print(f"Guardrail: {result['guardrail_verdict']}")
        print(f"Corrections: {result.get('guardrail_corrections', [])}")
    else:
        print("Email blocked by GuardrailAgent")