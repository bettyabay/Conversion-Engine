"""
agent/enrichment/ai_maturity.py
Scores a company's AI maturity on a 0-4 scale.
Used to gate Segment 4 (AI capability gap) outreach.
Only pitch AI if maturity >= 2.

Scale:
  0 = No AI presence
  1 = AI mentioned but no products
  2 = AI features in product
  3 = AI-first product
  4 = AI infrastructure / platform company
"""
import json
import re
from datetime import datetime, timezone


# Keywords that indicate AI maturity levels
LEVEL_4_SIGNALS = [
    "llm infrastructure", "vector database", "model training",
    "foundation model", "ai platform", "mlops", "gpu cluster",
    "inference api", "embedding model",
]

LEVEL_3_SIGNALS = [
    "ai-first", "ai-native", "powered by ai", "built on llm",
    "generative ai", "large language model", "gpt", "claude api",
    "openai api", "autonomous agent", "ai agent",
]

LEVEL_2_SIGNALS = [
    "ai feature", "ai assistant", "ai-powered", "machine learning",
    "natural language", "nlp", "recommendation engine",
    "predictive", "intelligent", "smart search", "ai copilot",
]

LEVEL_1_SIGNALS = [
    "artificial intelligence", "ai strategy", "ai roadmap",
    "exploring ai", "ai initiative", "ai transformation",
]


def score_ai_maturity(
    company_name: str,
    description: str = "",
    job_titles: list = None,
    website_text: str = "",
) -> dict:
    """
    Score AI maturity from available signals.
    Returns maturity_brief dict with score 0-4.
    """
    job_titles = job_titles or []
    text = f"{description} {website_text} {' '.join(job_titles)}".lower()

    score = 0
    matched_signals = []

    if any(s in text for s in LEVEL_4_SIGNALS):
        score = 4
        matched_signals = [s for s in LEVEL_4_SIGNALS if s in text]
    elif any(s in text for s in LEVEL_3_SIGNALS):
        score = 3
        matched_signals = [s for s in LEVEL_3_SIGNALS if s in text]
    elif any(s in text for s in LEVEL_2_SIGNALS):
        score = 2
        matched_signals = [s for s in LEVEL_2_SIGNALS if s in text]
    elif any(s in text for s in LEVEL_1_SIGNALS):
        score = 1
        matched_signals = [s for s in LEVEL_1_SIGNALS if s in text]

    # Bonus: engineering job titles with AI keywords
    ai_job_titles = [
        t for t in job_titles
        if any(kw in t.lower() for kw in ["ml", "ai", "machine learning", "data science"])
    ]
    if ai_job_titles and score < 3:
        score = min(score + 1, 3)

    label = {
        0: "NO_AI",
        1: "AI_AWARE",
        2: "AI_ENABLED",
        3: "AI_FIRST",
        4: "AI_PLATFORM",
    }[score]

    pitch_ai = score >= 2

    return {
        "company_name":    company_name,
        "ai_maturity":     score,
        "maturity_label":  label,
        "pitch_ai":        pitch_ai,
        "matched_signals": matched_signals[:3],
        "ai_job_titles":   ai_job_titles[:3],
        "brief":           _generate_brief(company_name, score, label, pitch_ai),
        "scored_at":       datetime.now(timezone.utc).isoformat(),
    }


def _generate_brief(company_name, score, label, pitch_ai) -> str:
    if score == 0:
        return (
            f"{company_name} shows no AI signals. "
            f"Do not pitch AI capability gap. Lead with engineering capacity."
        )
    elif score == 1:
        return (
            f"{company_name} is AI-aware but not yet building AI products. "
            f"Do not pitch AI capability gap yet."
        )
    elif score == 2:
        return (
            f"{company_name} has AI features in their product. "
            f"Can pitch AI capability gap — they understand the value."
        )
    elif score == 3:
        return (
            f"{company_name} is AI-first. Strong candidate for AI capability gap pitch. "
            f"They need engineers who can ship AI features fast."
        )
    else:
        return (
            f"{company_name} is an AI platform company. "
            f"Highest-value prospect for AI-capable engineering teams."
        )


if __name__ == "__main__":
    result = score_ai_maturity(
        company_name="Turing Signal",
        description="AI-powered recruiting platform using LLMs to match engineers",
        job_titles=["ML Engineer", "Senior Backend Engineer"],
    )
    print(json.dumps(result, indent=2))