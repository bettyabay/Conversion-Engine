"""
agent/enrichment/ai_maturity.py

AI Maturity Scorer — 0 to 3 scale per hiring_signal_brief.schema.json

Scoring rubric (from ICP definition):
  0 = No AI signal at all
  1 = Strategic communications only (CEO blog, keynote mentions AI)
  2 = Active AI hiring OR modern ML stack — building toward AI
  3 = Active AI function with NAMED leadership AND open AI-adjacent roles

Signal weights (from schema):
  HIGH:   ai_adjacent_open_roles, named_ai_ml_leadership
  MEDIUM: github_org_activity, executive_commentary
  LOW:    modern_data_ml_stack, strategic_communications

Confidence affects phrasing:
  high   (>=0.7) → assert the finding
  medium (0.4-0.7) → ask rather than assert
  low    (<0.4)  → "we don't see public signal of X"
"""
import json
from datetime import datetime, timezone
from typing import Optional


# ── Signal definitions ────────────────────────────────────────
# Each signal has keywords that indicate its presence,
# a weight (high/medium/low), and its contribution to the score.

AI_ROLE_KEYWORDS = [
    "ml engineer", "machine learning engineer", "mlops", "ml platform",
    "ai engineer", "ai platform", "data scientist", "llm engineer",
    "applied scientist", "research scientist", "head of ai", "head of ml",
    "vp of ai", "vp of data", "chief ai", "chief data", "chief scientist",
    "applied ml", "ai/ml", "ml infrastructure", "model engineer",
    "generative ai", "llm", "rag", "langchain", "pytorch", "hugging face",
]

LEADERSHIP_KEYWORDS = [
    "head of ai", "head of ml", "vp ai", "vp ml", "vp data",
    "chief ai officer", "chief data officer", "chief scientist",
    "director of ai", "director of ml", "director of data science",
    "named ai", "named ml", "ai leadership", "ml leadership",
]

ML_STACK_KEYWORDS = [
    "databricks", "mlflow", "weights and biases", "wandb", "ray",
    "kubeflow", "airflow ml", "sagemaker", "vertex ai", "azure ml",
    "pytorch", "tensorflow", "hugging face", "vllm", "triton",
    "feature store", "vector database", "pinecone", "weaviate", "qdrant",
]

EXEC_COMMENTARY_KEYWORDS = [
    "ai-powered", "ai-first", "ai-native", "powered by ai",
    "generative ai", "large language model", "llm-driven",
    "agentic", "autonomous", "ai strategy", "ai roadmap",
    "ai as a priority", "ai transformation", "ai capabilities",
    "machine learning", "deep learning", "neural network",
]

STRATEGIC_KEYWORDS = [
    "artificial intelligence", "ai initiative", "ai exploration",
    "exploring ai", "considering ai", "ai in our roadmap",
    "ai in 2026", "ai this year", "ai opportunity",
]


def score_ai_maturity(
    company_name: str,
    description: str = "",
    job_titles: list = None,
    website_text: str = "",
    github_has_ml_repos: bool = False,
    has_named_ai_leader: bool = False,
) -> dict:
    """
    Score a company's AI maturity on a 0-3 scale.

    Parameters:
        company_name: Company being scored
        description: Company description (from Crunchbase or website)
        job_titles: List of open job title strings
        website_text: Text from company website / blog
        github_has_ml_repos: Whether public GitHub org has ML/AI repos
        has_named_ai_leader: Whether a named AI/ML leader is publicly listed

    Returns:
        dict matching hiring_signal_brief.schema.json ai_maturity block
    """
    job_titles = job_titles or []
    all_text = f"{description} {website_text}".lower()
    all_jobs = " ".join(job_titles).lower()

    justifications = []

    # ── Signal 1: ai_adjacent_open_roles (HIGH weight) ────────
    ai_roles_found = [t for t in job_titles
                      if any(kw in t.lower() for kw in AI_ROLE_KEYWORDS)]
    ai_role_pct = len(ai_roles_found) / max(len(job_titles), 1)

    if ai_roles_found:
        role_confidence = "high" if len(ai_roles_found) >= 2 else "medium"
        justifications.append({
            "signal": "ai_adjacent_open_roles",
            "status": f"{len(ai_roles_found)} AI-adjacent open role(s) detected: {', '.join(ai_roles_found[:3])}.",
            "weight": "high",
            "confidence": role_confidence,
        })
    else:
        justifications.append({
            "signal": "ai_adjacent_open_roles",
            "status": "No AI-adjacent open roles detected in provided job titles.",
            "weight": "high",
            "confidence": "high",
        })

    # ── Signal 2: named_ai_ml_leadership (HIGH weight) ────────
    leadership_in_desc = any(kw in all_text for kw in LEADERSHIP_KEYWORDS)
    leadership_in_jobs = any(kw in all_jobs for kw in LEADERSHIP_KEYWORDS)
    has_leadership = has_named_ai_leader or leadership_in_desc or leadership_in_jobs

    if has_leadership:
        justifications.append({
            "signal": "named_ai_ml_leadership",
            "status": "Named AI/ML leadership role detected (Head of AI, VP Data, or equivalent).",
            "weight": "high",
            "confidence": "high" if has_named_ai_leader else "medium",
        })
    else:
        justifications.append({
            "signal": "named_ai_ml_leadership",
            "status": "No named AI/ML leadership role found on public team page or job postings.",
            "weight": "high",
            "confidence": "high",
        })

    # ── Signal 3: github_org_activity (MEDIUM weight) ──────────
    if github_has_ml_repos:
        justifications.append({
            "signal": "github_org_activity",
            "status": "Public GitHub org contains ML/AI repositories.",
            "weight": "medium",
            "confidence": "medium",
        })
    else:
        justifications.append({
            "signal": "github_org_activity",
            "status": "No public ML/AI repos in GitHub org. Absence is not proof — AI work may be in private repos.",
            "weight": "medium",
            "confidence": "low",
        })

    # ── Signal 4: executive_commentary (MEDIUM weight) ─────────
    exec_signals = [kw for kw in EXEC_COMMENTARY_KEYWORDS if kw in all_text]
    if exec_signals:
        justifications.append({
            "signal": "executive_commentary",
            "status": f"Executive/marketing copy references AI: {', '.join(exec_signals[:3])}.",
            "weight": "medium",
            "confidence": "medium" if len(exec_signals) >= 2 else "low",
        })
    else:
        justifications.append({
            "signal": "executive_commentary",
            "status": "No AI-specific executive commentary detected in description or website text.",
            "weight": "medium",
            "confidence": "medium",
        })

    # ── Signal 5: modern_data_ml_stack (LOW weight) ────────────
    stack_signals = [kw for kw in ML_STACK_KEYWORDS if kw in all_text]
    if stack_signals:
        justifications.append({
            "signal": "modern_data_ml_stack",
            "status": f"Modern ML/data stack signals: {', '.join(stack_signals[:3])}.",
            "weight": "low",
            "confidence": "high",
        })
    else:
        justifications.append({
            "signal": "modern_data_ml_stack",
            "status": "No ML-platform tooling signal detected. Modern data stack (dbt/Snowflake) without ML layer.",
            "weight": "low",
            "confidence": "high",
        })

    # ── Signal 6: strategic_communications (LOW weight) ────────
    strategic_signals = [kw for kw in STRATEGIC_KEYWORDS if kw in all_text]
    if strategic_signals:
        justifications.append({
            "signal": "strategic_communications",
            "status": f"AI mentioned in strategic context: {', '.join(strategic_signals[:2])}.",
            "weight": "low",
            "confidence": "low",
        })
    else:
        justifications.append({
            "signal": "strategic_communications",
            "status": "No AI mentioned in strategic/communications materials.",
            "weight": "low",
            "confidence": "medium",
        })

    # ── Scoring logic ──────────────────────────────────────────
    # Score 3: Named AI leader AND AI-adjacent open roles (both HIGH signals present)
    # Score 2: Either AI-adjacent roles OR modern ML stack (building toward AI)
    # Score 1: Executive commentary only (aware but not building)
    # Score 0: No signal

    has_ai_roles   = bool(ai_roles_found)
    has_ml_stack   = bool(stack_signals)
    has_exec_ai    = bool(exec_signals)
    has_strategic  = bool(strategic_signals)

    if has_leadership and has_ai_roles:
        # Both high-weight signals present — actively building AI function
        score = 3
        raw_confidence = 0.85 if len(ai_roles_found) >= 2 else 0.7
    elif has_ai_roles and (has_ml_stack or has_exec_ai):
        # AI roles open + supporting signal — building toward AI
        score = 2
        raw_confidence = 0.75
    elif has_ai_roles:
        # AI roles only — early AI hiring
        score = 2
        raw_confidence = 0.6
    elif has_ml_stack and has_exec_ai:
        # Modern stack + executive commentary — AI-aware, building infrastructure
        score = 2
        raw_confidence = 0.55
    elif has_exec_ai or has_ml_stack:
        # Commentary or stack only — AI-aware
        score = 1
        raw_confidence = 0.5
    elif has_strategic:
        # Only strategic mentions — mentioned AI but no signal of building
        score = 1
        raw_confidence = 0.35
    else:
        score = 0
        raw_confidence = 0.85  # High confidence in the zero score

    # Confidence label
    if raw_confidence >= 0.7:
        confidence_label = "high"
    elif raw_confidence >= 0.4:
        confidence_label = "medium"
    else:
        confidence_label = "low"

    # Pitch AI only at score >= 2
    pitch_ai = score >= 2

    # ── Phrasing based on confidence ──────────────────────────
    brief = _generate_brief(company_name, score, confidence_label, pitch_ai, ai_roles_found)

    return {
        "company_name":    company_name,
        "score":           score,
        "confidence":      raw_confidence,
        "confidence_label": confidence_label,
        "pitch_ai":        pitch_ai,
        "justifications":  justifications,
        "brief":           brief,
        "scored_at":       datetime.now(timezone.utc).isoformat(),
    }


def _generate_brief(
    company_name: str,
    score: int,
    confidence_label: str,
    pitch_ai: bool,
    ai_roles: list,
) -> str:
    """
    Generate phrasing calibrated to confidence level.
    HIGH confidence → assert. MEDIUM → ask. LOW → "we don't see signal of X".
    """
    if score == 0:
        if confidence_label == "high":
            return (
                f"{company_name} shows no public AI signal. "
                f"Do not pitch AI capability gap. Lead with engineering capacity."
            )
        else:
            return (
                f"We don't see public AI signal for {company_name}, "
                f"but absence from public sources is not proof of absence. "
                f"Lead with engineering capacity; let the prospect surface AI interest."
            )

    elif score == 1:
        if confidence_label in ("high", "medium"):
            return (
                f"{company_name} mentions AI in strategic context but shows no "
                f"active AI hiring or named AI leadership. AI-aware but not yet building. "
                f"Do not pitch AI capability gap — ask about their AI roadmap instead."
            )
        else:
            return (
                f"Weak AI signal for {company_name}. "
                f"Worth asking: 'is AI a 2026 priority for your team?' rather than asserting a gap."
            )

    elif score == 2:
        role_str = f" ({', '.join(ai_roles[:2])})" if ai_roles else ""
        if confidence_label == "high":
            return (
                f"{company_name} has active AI hiring{role_str}. "
                f"They understand AI value — can pitch AI capability gap. "
                f"Frame as: 'scaling your AI team faster than in-house hiring can support.'"
            )
        else:
            return (
                f"{company_name} shows some AI hiring signal{role_str}. "
                f"Medium confidence — ask about their AI roadmap before pitching. "
                f"'Is the AI function something you're actively building out?'"
            )

    else:  # score == 3
        if confidence_label == "high":
            return (
                f"{company_name} has a named AI leader and active AI engineering roles. "
                f"Strong AI capability gap candidate. "
                f"Pitch: 'stand up your AI squad faster than in-house hiring can support.'"
            )
        else:
            return (
                f"{company_name} shows strong AI signal with medium confidence. "
                f"Verify named AI leadership before Segment 4 pitch. "
                f"Approach as a research question: 'who owns the AI function at your company?'"
            )


if __name__ == "__main__":
    # Test with Orrin Labs sample from the seed materials
    result = score_ai_maturity(
        company_name="Orrin Labs Inc.",
        description="AI-powered business intelligence platform. CEO blog 2026 names AI as priority.",
        job_titles=[
            "Data Platform Engineer",
            "ML Engineer",
            "Data Platform Engineer",
        ],
        website_text="ai-powered insights dbt snowflake",
        has_named_ai_leader=False,
    )
    print(json.dumps(result, indent=2))