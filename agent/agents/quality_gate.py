"""
agent/agents/quality_gate.py

GuardrailAgent — Act IV mechanism made into a proper agent.
Replaces the simple tone_pass True/False with a 3-verdict system.

Verdict:
  PASS  — email sends immediately, no changes
  WARN  — agent auto-corrects the specific issue, logs correction
  BLOCK — email dropped entirely, MessageAgent called again with
           tighter constraints

Checks (in order):
  1. Signal confidence gate — overclaimed hiring/AI/funding claims
  2. Tone markers — banned phrases from style_guide.md
  3. Claim honesty — velocity_label matches language used
  4. Bench availability — no stacks pitched that bench cannot staff
  5. Word count — enforces per-email-type limits
"""
import re
import json
from datetime import datetime, timezone


BANNED_PHRASES = [
    "just circling back", "circling back", "just following up",
    "hope this finds you well", "wanted to touch base",
    "top talent", "world-class", "a-players", "rockstar", "ninja",
    "guaranteed savings", "guarantee savings", "guarantees savings", "save 40%", "save 30%", "savings of",
    "your competitors are moving fast", "before it's too late",
    "act now", "last chance", "we can handle any stack",
    "replace your team", "better than india",
    "aggressive hiring", "scaling aggressively",
    "rapid growth", "explosive growth",
]

WORD_LIMITS = {
    "cold_1":        120,
    "cold_2":        100,
    "cold_3":         70,
    "warm_engaged":  150,
    "warm_curious":   90,
    "warm_objection": 150,
    "warm_soft_defer": 60,
    "reengagement_1": 100,
    "reengagement_2":  50,
    "reengagement_3":  40,
}

# Phrases that over-claim hiring velocity
VELOCITY_OVERCLAIMS = [
    "aggressively hiring", "aggressive hiring", "scaling rapidly",
    "explosive hiring", "hiring surge", "tripled your hiring",
    "your hiring has tripled", "doubling your team",
]

# Corrections for WARN-level velocity overclaims
VELOCITY_CORRECTIONS = {
    "aggressively hiring":    "actively hiring",
    "aggressive hiring":      "actively hiring",
    "scaling rapidly":        "growing the engineering team",
    "explosive hiring":       "expanding the team",
    "hiring surge":           "increase in open roles",
    "your hiring has tripled": "open engineering roles have increased",
    "doubling your team":     "adding to the team",
}


def run(
    email_dict: dict,
    hiring_signal: dict = None,
    bench_summary: dict = None,
) -> dict:
    """
    Run the guardrail on a composed email.

    Args:
        email_dict: Output from MessageAgent/email_composer.py
        hiring_signal: The hiring signal brief used to compose the email
        bench_summary: bench_summary.json data for bench checks

    Returns:
        dict with verdict (PASS/WARN/BLOCK), corrected_email,
        issues, corrections, trace_metadata
    """
    hiring_signal  = hiring_signal or {}
    bench_summary  = bench_summary or {}
    issues         = []
    corrections    = []
    corrected_body = email_dict.get("body", "")
    email_type     = email_dict.get("email_type", "cold_1")
    segment        = email_dict.get("segment", "abstain")

    # ── Check 1: Signal confidence gate ──────────────────────
    velocity = hiring_signal.get("hiring_velocity", {})
    vel_label = velocity.get("velocity_label", "")
    vel_conf  = velocity.get("signal_confidence", 1.0)
    honesty   = hiring_signal.get("honesty_flags", [])

    if "weak_hiring_velocity_signal" in honesty or vel_conf < 0.5:
        for phrase in VELOCITY_OVERCLAIMS:
            if phrase in corrected_body.lower():
                issues.append(f"WARN: velocity overclaim '{phrase}' with insufficient_signal confidence {vel_conf:.2f}")
                correction = VELOCITY_CORRECTIONS.get(phrase, "")
                if correction:
                    corrected_body = re.sub(phrase, correction, corrected_body, flags=re.IGNORECASE)
                    corrections.append(f"Replaced '{phrase}' with '{correction}'")

    # ── Check 2: Banned phrases ───────────────────────────────
    body_lower = corrected_body.lower()
    for phrase in BANNED_PHRASES:
        if phrase.lower() in body_lower:
            issues.append(f"BLOCK: banned phrase detected: '{phrase}'")

    # ── Check 3: AI maturity claim honesty ────────────────────
    ai_mat = hiring_signal.get("ai_maturity", {})
    ai_conf_label = ai_mat.get("confidence_label", "high") if isinstance(ai_mat, dict) else "high"
    ai_score = ai_mat.get("score", 0) if isinstance(ai_mat, dict) else 0

    ai_overclaims = ["ai team is scaling", "ai team is growing rapidly", "your ai function is expanding"]
    if ai_conf_label in ("low", "medium") and ai_score < 3:
        for phrase in ai_overclaims:
            if phrase in body_lower:
                issues.append(f"WARN: AI claim '{phrase}' with only {ai_conf_label} confidence")
                corrected_body = corrected_body.replace(phrase, "your AI roadmap")
                corrections.append(f"Replaced asserted AI claim with question framing")

    # ── Check 4: Bench availability ───────────────────────────
    required_stacks = hiring_signal.get("tech_stack", [])
    if bench_summary and required_stacks:
        stacks_data = bench_summary.get("stacks", {})
        for stack in required_stacks:
            avail = stacks_data.get(stack, {}).get("available_engineers", -1)
            if avail == 0:
                if stack in corrected_body.lower():
                    issues.append(f"BLOCK: email pitches {stack} but bench has 0 engineers available")

    # ── Check 5: Word count ───────────────────────────────────
    word_count = len(re.findall(r'\b\w+\b', corrected_body))
    limit = WORD_LIMITS.get(email_type, 150)
    if word_count > limit:
        issues.append(f"WARN: word count {word_count} exceeds {limit} limit for {email_type}")
        # Auto-correct: truncate at the last sentence before the limit
        words   = corrected_body.split()
        trimmed = " ".join(words[:limit])
        last_sentence_end = max(trimmed.rfind("."), trimmed.rfind("?"), trimmed.rfind("!"))
        if last_sentence_end > 0:
            corrected_body = trimmed[:last_sentence_end + 1]
            corrections.append(f"Truncated from {word_count} to {limit} words")

    # ── Subject length ────────────────────────────────────────
    subject = email_dict.get("subject", "")
    if len(subject) > 60:
        issues.append(f"WARN: subject length {len(subject)} exceeds 60 chars")

    # ── Determine verdict ─────────────────────────────────────
    block_issues = [i for i in issues if i.startswith("BLOCK")]
    warn_issues  = [i for i in issues if i.startswith("WARN")]

    if block_issues:
        verdict = "BLOCK"
    elif warn_issues:
        verdict = "WARN"
    else:
        verdict = "PASS"

    corrected_email = dict(email_dict)
    corrected_email["body"] = corrected_body
    corrected_email["word_count"] = len(re.findall(r'\b\w+\b', corrected_body))
    corrected_email["tone_pass"] = verdict in ("PASS", "WARN")  # WARN = auto-corrected and now passing

    result = {
        "verdict":         verdict,
        "issues":          issues,
        "corrections":     corrections,
        "corrected_email": corrected_email if verdict != "BLOCK" else None,
        "block_reason":    block_issues[0] if block_issues else None,
        "auto_corrected":  len(corrections) > 0,
        "checked_at":      datetime.now(timezone.utc).isoformat(),
    }

    print(f"[GuardrailAgent] segment={segment} type={email_type} verdict={verdict}")
    if corrections:
        for c in corrections:
            print(f"  CORRECTED: {c}")
    if block_issues:
        for b in block_issues:
            print(f"  BLOCKED: {b}")

    return result


def run_with_retry(
    email_dict: dict,
    hiring_signal: dict = None,
    bench_summary: dict = None,
    max_retries: int = 2,
) -> dict:
    """
    Run guardrail with retry on BLOCK.
    On BLOCK: calls MessageAgent again with tighter constraints.
    Returns the final result after up to max_retries attempts.
    """
    for attempt in range(max_retries + 1):
        result = run(email_dict, hiring_signal, bench_summary)

        if result["verdict"] != "BLOCK":
            result["attempts"] = attempt + 1
            return result

        print(f"[GuardrailAgent] BLOCK on attempt {attempt + 1} — regenerating with constraints")

        if attempt < max_retries:
            # Regenerate with tighter constraints
            email_dict = _regenerate_with_constraints(email_dict, result["block_reason"])

    result["attempts"] = max_retries + 1
    result["verdict"]  = "BLOCK_FINAL"
    result["corrected_email"] = None
    return result


def _regenerate_with_constraints(email_dict: dict, block_reason: str) -> dict:
    """
    Regenerate email with tighter constraints based on block reason.
    In production: calls MessageAgent with updated system prompt.
    In this implementation: applies targeted transformation.
    """
    body    = email_dict.get("body", "")
    segment = email_dict.get("segment", "abstain")

    # Remove the blocked content
    if "bench" in block_reason.lower():
        # Remove stack-specific claims
        for phrase in ["python engineers", "go engineers", "ml engineers", "data engineers"]:
            body = body.replace(phrase, "engineers")
        body = body.replace("engineers on bench", "engineers available")

    # Ensure the regenerated email is under word limit
    email_type  = email_dict.get("email_type", "cold_1")
    limit       = WORD_LIMITS.get(email_type, 120)
    words       = body.split()
    if len(words) > limit:
        body = " ".join(words[:limit])

    new_dict = dict(email_dict)
    new_dict["body"] = body
    new_dict["regenerated"] = True
    return new_dict


if __name__ == "__main__":
    # Test PASS case
    test_email = {
        "email_type": "cold_1",
        "segment":    "segment_1_series_a_b",
        "subject":    "Orrin Labs engineering capacity",
        "body":       "Jordan,\n\nYou have 11 engineering roles open since the Series B closed. The typical bottleneck at that stage is recruiting capacity, not budget.\n\nWe run dedicated engineering squads — senior engineers available in 7-14 days, embedded in your stack.\n\nWorth 15 minutes? → https://cal.com/\n\nBethelhem\nResearch Partner, Tenacious Intelligence Corporation\ngettenacious.com",
        "word_count": 61,
    }
    result = run(test_email)
    print(f"Test PASS: verdict={result['verdict']}")

    # Test WARN case (velocity overclaim)
    test_warn = dict(test_email)
    test_warn["body"] = test_warn["body"].replace("11 engineering roles open", "aggressively hiring engineers")
    test_warn_hiring = {"hiring_velocity": {"velocity_label": "insufficient_signal", "signal_confidence": 0.3}, "honesty_flags": ["weak_hiring_velocity_signal"]}
    result2 = run(test_warn, test_warn_hiring)
    print(f"Test WARN: verdict={result2['verdict']} corrections={result2['corrections']}")

    # Test BLOCK case (banned phrase)
    test_block = dict(test_email)
    test_block["body"] = test_block["body"] + "\n\nWe are the best offshore team and guarantee savings of 40%."
    result3 = run(test_block)
    print(f"Test BLOCK: verdict={result3['verdict']} reason={result3['block_reason']}")