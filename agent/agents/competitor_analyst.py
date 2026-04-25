"""
agent/agents/competitor_analyst.py

InsightAgent — LLM-powered competitor gap analysis.
Replaces the rule-based competitor_gap.py for the live pilot.

Uses the backbone LLM to:
1. Pull real sector peers from Crunchbase ODM
2. Generate narrative in Tenacious voice (grounded by style_guide.md)
3. Produce competitor_gap_brief with real company names and evidence
4. Generate pitch_shift note calibrated to the specific prospect

Backbone LLM:
  Dev:  openrouter/deepseek/deepseek-chat (cheap, fast)
  Eval: claude-sonnet-4-6 (high quality for graded runs)

All LLM calls are traced to Langfuse via create_trace() in main.py.
"""
import os
import json
import requests
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
DEV_MODEL  = "deepseek/deepseek-chat"
EVAL_MODEL = "anthropic/claude-sonnet-4-5"


def run(
    company_name: str,
    hiring_signal_brief: dict,
    sector: str = "Software / SaaS",
    use_eval_model: bool = False,
) -> dict:
    """
    Generate a competitor gap brief using the LLM backbone.

    Args:
        company_name: Prospect company name
        hiring_signal_brief: Output from ResearchAgent
        sector: Crunchbase sector classification
        use_eval_model: If True, uses claude-sonnet-4-6 instead of deepseek

    Returns:
        competitor_gap_brief dict matching competitor_gap_brief.schema.json
    """
    # Get real peers from Crunchbase ODM
    peers = _get_real_peers(sector, company_name)
    ai_score = hiring_signal_brief.get("ai_maturity", {}).get("score", 0)
    funding  = hiring_signal_brief.get("buying_window_signals", {}).get("funding_event", {})
    layoff   = hiring_signal_brief.get("buying_window_signals", {}).get("layoff_event", {})
    segment  = hiring_signal_brief.get("primary_segment_match", "abstain")

    # Build the LLM prompt
    prompt = _build_prompt(company_name, sector, ai_score, funding, layoff, segment, peers)
    model  = EVAL_MODEL if use_eval_model else DEV_MODEL

    print(f"[InsightAgent] Calling {model} for {company_name} ({sector})")

    try:
        response = _call_llm(prompt, model)
        brief    = _parse_response(response, company_name, sector, ai_score, peers)
        print(f"[InsightAgent] Generated {len(brief.get('gap_findings',[]))} gap findings")
        return brief
    except Exception as e:
        print(f"[InsightAgent] LLM call failed: {e} — falling back to rule-based")
        from agent.enrichment.competitor_gap import build_competitor_gap_brief
        return build_competitor_gap_brief(
            company_name=company_name,
            sector=sector,
            prospect_ai_maturity=ai_score,
        )


def _get_real_peers(sector: str, exclude_company: str, n: int = 6) -> list:
    """Pull real peer companies from Crunchbase ODM."""
    try:
        from agent.enrichment.crunchbase import get_rows, _build_brief as _build_brief_from_row
        rows  = get_rows()
        peers = []
        sector_lower   = sector.lower()
        exclude_lower  = exclude_company.lower()

        for row in rows[:500]:
            name     = (row.get("name","") or row.get("company_name","") or "").strip()
            industry = (row.get("category_list","") or row.get("industry","") or "").lower()

            if not name or name.lower() == exclude_lower:
                continue

            # Loose sector match
            sector_words = [w for w in sector_lower.split("/") if len(w.strip()) > 3]
            if not any(w.strip() in industry for w in sector_words):
                continue

            brief = _build_brief_from_row(row, name)
            peers.append({
                "name":   name,
                "domain": brief.get("website","").replace("https://www.","").replace("https://",""),
                "sector": brief.get("industry",""),
                "funding_type": brief.get("last_funding_type",""),
                "employee_count": brief.get("employee_count",""),
                "source": brief.get("website",""),
            })

            if len(peers) >= n:
                break

        if peers:
            print(f"[InsightAgent] Found {len(peers)} real peers from ODM for sector '{sector}'")
            return peers

    except Exception as e:
        print(f"[InsightAgent] ODM peer lookup failed: {e}")

    # Fallback: return empty list (LLM will use general knowledge)
    return []


def _build_prompt(
    company_name, sector, ai_score, funding, layoff, segment, peers
) -> str:
    """Build the LLM prompt for competitor gap analysis."""
    funding_str = ""
    if funding.get("detected"):
        stage  = funding.get("stage","").replace("_"," ").title()
        amount = funding.get("amount_usd", 0)
        funding_str = f"Recently closed {stage} of ${amount/1e6:.0f}M."

    layoff_str = ""
    if layoff.get("detected"):
        layoff_str = f"Had a layoff of {layoff.get('percentage_cut','?')}% recently."

    peers_str = ""
    if peers:
        peer_lines = [f"- {p['name']} ({p.get('funding_type','unknown')} stage, {p.get('employee_count','?')} employees)" for p in peers[:4]]
        peers_str  = "Known sector peers from Crunchbase:\n" + "\n".join(peer_lines)
    else:
        peers_str = "Sector peers: not available from database — use general knowledge of this sector."

    return f"""You are a research analyst at Tenacious Consulting, an African offshore engineering firm.
Your job: produce a competitor gap brief for {company_name}.

CONTEXT:
- Company: {company_name}
- Sector: {sector}
- AI maturity score: {ai_score}/3 (0=no AI, 3=active AI function with named leadership)
- ICP segment: {segment}
- {funding_str}
- {layoff_str}
{peers_str}

TASK:
Produce a competitor_gap_brief JSON with exactly this structure:
{{
  "prospect_sector": "{sector}",
  "prospect_ai_maturity_score": {ai_score},
  "sector_top_quartile_benchmark": <float 0-3>,
  "competitors_analyzed": [
    {{
      "name": "<real company name>",
      "domain": "<domain.com>",
      "ai_maturity_score": <0-3>,
      "ai_maturity_justification": ["<one line per signal>"],
      "headcount_band": "<15_to_80|80_to_200|200_to_500|500_to_2000>",
      "top_quartile": <true|false>,
      "sources_checked": ["<public URL>"]
    }}
  ],
  "gap_findings": [
    {{
      "practice": "<specific practice — verifiable fact, not opinion>",
      "peer_evidence": [
        {{"competitor_name": "<name>", "evidence": "<one line>", "source_url": "<public URL>"}}
      ],
      "prospect_state": "<what {company_name} shows or does not show publicly>",
      "confidence": "<high|medium|low>",
      "segment_relevance": ["<segment_1_series_a_b|segment_2_mid_market_restructure|segment_3_leadership_transition|segment_4_specialized_capability>"]
    }}
  ],
  "suggested_pitch_shift": "<one paragraph for the email composer>",
  "gap_quality_self_check": {{
    "all_peer_evidence_has_source_url": <true|false>,
    "at_least_one_gap_high_confidence": <true|false>,
    "prospect_silent_but_sophisticated_risk": <true|false>
  }}
}}

RULES:
1. Analyze 5-7 peer companies. At least 2 must be top_quartile (score 3).
2. Produce 2-3 gap findings. At least 1 must be high confidence.
3. Every peer_evidence item must have a real public source_url.
4. prospect_state must describe what is or is not visible publicly — never assert what is private.
5. suggested_pitch_shift must be in Tenacious voice: Direct, Grounded, Honest, Professional, Non-condescending.
6. Return ONLY the JSON. No preamble, no markdown fences.
"""


def _call_llm(prompt: str, model: str) -> str:
    """Call OpenRouter LLM API."""
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type":  "application/json",
            "HTTP-Referer":  "https://github.com/bettyabay/Conversion-Engine",
        },
        json={
            "model":      model,
            "max_tokens": 2000,
            "messages":   [{"role": "user", "content": prompt}],
            "temperature": 0.3,  # low temperature for factual output
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _parse_response(
    response: str, company_name: str,
    sector: str, ai_score: int, peers: list
) -> dict:
    """Parse LLM JSON response into a validated brief."""
    # Strip markdown fences if present
    clean = response.strip()
    if clean.startswith("```"):
        lines = clean.split("\n")
        clean = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

    try:
        brief = json.loads(clean)
    except json.JSONDecodeError:
        # Try to extract JSON from mixed response
        start = clean.find("{")
        end   = clean.rfind("}") + 1
        if start >= 0 and end > start:
            brief = json.loads(clean[start:end])
        else:
            raise ValueError("LLM response was not valid JSON")

    # Add required top-level fields
    brief["prospect_domain"]            = f"{company_name.lower().replace(' ','-')}.example"
    brief["generated_at"]              = datetime.now(timezone.utc).isoformat()
    brief["prospect_ai_maturity_score"] = ai_score

    # Ensure gap_quality_self_check is populated
    findings = brief.get("gap_findings", [])
    brief["gap_quality_self_check"] = {
        "all_peer_evidence_has_source_url": all(
            all(e.get("source_url") for e in f.get("peer_evidence",[]))
            for f in findings
        ),
        "at_least_one_gap_high_confidence": any(
            f.get("confidence") == "high" for f in findings
        ),
        "prospect_silent_but_sophisticated_risk": False,
    }

    return brief


if __name__ == "__main__":
    # Test with Orrin Labs
    sample_brief = {
        "primary_segment_match": "segment_1_series_a_b",
        "ai_maturity": {"score": 2},
        "buying_window_signals": {
            "funding_event": {"detected": True, "stage": "series_b", "amount_usd": 14000000},
            "layoff_event":  {"detected": False},
        }
    }
    print("Testing InsightAgent (requires OPENROUTER_API_KEY)...")
    if not OPENROUTER_API_KEY:
        print("OPENROUTER_API_KEY not set — skipping live test")
    else:
        result = run("Orrin Labs", sample_brief, "Business Intelligence / Analytics")
        print(json.dumps(result, indent=2)[:500])