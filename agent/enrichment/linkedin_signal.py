"""
agent/enrichment/linkedin_signal.py

LinkedIn public signal detector using SerpAPI.
SerpAPI: 100 free searches/month at serpapi.com

Detects:
  1. New CTO / VP Engineering appointments (feeds Segment 3)
  2. Open engineering roles via LinkedIn Jobs search (feeds hiring velocity)

Setup:
  Add to .env:
    SERP_API_KEY=your_serpapi_key

Policy compliance:
  - Public pages only via SerpAPI Google search
  - User agent handled by SerpAPI
  - Rate limit: 2 second delay between calls
  - Cap: max 200 companies per challenge week
"""
import re
import time
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

_last_request_time: dict = {}
RATE_LIMIT_SECONDS = 2

CTO_KEYWORDS = [
    "chief technology officer",
    "cto",
    "vp engineering",
    "vp of engineering",
    "vice president engineering",
    "head of engineering",
    "head of technology",
    "chief data officer",
    "vp of ai",
    "head of ai",
    "head of ml",
]

ENG_JOB_KEYWORDS = [
    "software engineer",
    "backend engineer",
    "frontend engineer",
    "full stack engineer",
    "data engineer",
    "ml engineer",
    "devops engineer",
    "platform engineer",
    "infrastructure engineer",
    "machine learning",
    "data scientist",
    "ai engineer",
    "engineering manager",
    "tech lead",
    "senior engineer",
]


def get_linkedin_signal(company_name: str, days_window: int = 90) -> dict:
    """
    Get LinkedIn signals for a company using SerpAPI.

    Returns dict with:
      leadership_change: detected, role, name, started_at
      open_roles_linkedin: count of engineering roles found
      role_titles: list of role titles
      signal_confidence: high/medium/low
      source: linkedin_serpapi
    """
    print(f"[LinkedIn] Searching signals for: {company_name}")

    result = {
        "company_name":        company_name,
        "leadership_change":   {"detected": False, "role": "", "name": "", "started_at": ""},
        "open_roles_linkedin": 0,
        "role_titles":         [],
        "signal_confidence":   "low",
        "source":              "linkedin_serpapi",
        "retrieved_at":        datetime.now(timezone.utc).isoformat(),
    }

    # Check SerpAPI key
    serp_key = os.getenv("SERP_API_KEY", "")
    if not serp_key:
        print("[LinkedIn] SERP_API_KEY not set — skipping LinkedIn enrichment")
        return result

    # Search for leadership change
    leadership = _search_leadership_change(company_name, serp_key)
    if leadership["detected"]:
        result["leadership_change"] = leadership
        result["signal_confidence"] = "medium"
        print(f"[LinkedIn] Leadership change: {leadership['role']} — {leadership['name']}")

    # Search for open engineering roles
    roles, titles = _search_linkedin_jobs(company_name, serp_key)
    if roles > 0:
        result["open_roles_linkedin"] = roles
        result["role_titles"]         = titles
        if result["signal_confidence"] == "low":
            result["signal_confidence"] = "medium"
        print(f"[LinkedIn] Found {roles} engineering roles: {titles[:3]}")

    if result["leadership_change"]["detected"] and result["open_roles_linkedin"] > 0:
        result["signal_confidence"] = "high"

    return result


def _search_leadership_change(company_name: str, serp_key: str) -> dict:
    """Search for new CTO/VP Eng appointment using SerpAPI."""
    _rate_limit("serpapi.com")

    year  = datetime.now().year
    kw    = " OR ".join([f'"{k}"' for k in CTO_KEYWORDS[:4]])
    query = f'site:linkedin.com "{company_name}" ("new" OR "joined") ({kw})'

    items = _serp_search(query, serp_key, num=5)

    for item in items:
        title    = item.get("title", "").lower()
        snippet  = item.get("snippet", "").lower()
        combined = title + " " + snippet

        for keyword in CTO_KEYWORDS:
            if keyword in combined:
                name      = _extract_name_from_title(item.get("title", ""))
                role      = _normalize_role(keyword)
                is_recent = str(year) in combined or str(year - 1) in combined

                if is_recent or "new" in combined or "joined" in combined:
                    return {
                        "detected":   True,
                        "role":       role,
                        "name":       name,
                        "started_at": f"{year}-01-01",
                        "source_url": item.get("link", ""),
                        "snippet":    snippet[:200],
                    }

    return {"detected": False, "role": "", "name": "", "started_at": ""}


def _search_linkedin_jobs(company_name: str, serp_key: str) -> tuple:
    """Search for open engineering roles on LinkedIn Jobs using SerpAPI."""
    _rate_limit("serpapi.com")

    query = f'site:linkedin.com/jobs "{company_name}" engineer'
    items = _serp_search(query, serp_key, num=10)

    titles = []
    for item in items:
        title        = item.get("title", "")
        snippet      = item.get("snippet", "").lower()
        title_lower  = title.lower()

        for keyword in ENG_JOB_KEYWORDS:
            if keyword in title_lower or keyword in snippet:
                clean = re.sub(r'\s*[-|]\s*(LinkedIn|Jobs).*$', '', title, flags=re.IGNORECASE).strip()
                if clean and clean not in titles:
                    titles.append(clean)
                break

    return len(titles), titles[:10]


def _serp_search(query: str, api_key: str, num: int = 5) -> list:
    """
    Execute a search via SerpAPI Google Search endpoint.
    Returns list of result dicts with title, link, snippet.
    """
    try:
        import requests
        resp = requests.get(
            "https://serpapi.com/search",
            params={
                "engine":  "google",
                "q":       query,
                "num":     num,
                "api_key": api_key,
                "gl":      "us",
                "hl":      "en",
            },
            timeout=15,
        )

        if resp.status_code == 200:
            data    = resp.json()
            results = data.get("organic_results", [])
            print(f"[LinkedIn] SerpAPI returned {len(results)} results for: {query[:60]}")
            return results
        else:
            error_msg = resp.json().get("error", resp.text[:100])
            print(f"[LinkedIn] SerpAPI returned {resp.status_code}: {error_msg}")
            return []

    except Exception as e:
        print(f"[LinkedIn] SerpAPI search failed: {e}")
        return []


def _rate_limit(domain: str):
    """Enforce minimum delay between requests to same domain."""
    now  = time.time()
    last = _last_request_time.get(domain, 0)
    wait = RATE_LIMIT_SECONDS - (now - last)
    if wait > 0:
        time.sleep(wait)
    _last_request_time[domain] = time.time()


def _extract_name_from_title(title: str) -> str:
    """Extract person name from LinkedIn result title."""
    match = re.match(r'^([A-Z][a-z]+ [A-Z][a-z]+)\s*[-|]', title)
    if match:
        return match.group(1)
    match2 = re.match(r'^([A-Z][a-z]+ [A-Z][a-z]+)\s*\|', title)
    if match2:
        return match2.group(1)
    return "name not confirmed"


def _normalize_role(keyword: str) -> str:
    """Normalize role keyword to schema enum."""
    kw = keyword.lower()
    if "cto" in kw or "chief technology" in kw:
        return "cto"
    if "vp eng" in kw or "vice president eng" in kw:
        return "vp_engineering"
    if "head of eng" in kw:
        return "vp_engineering"
    if "head of ai" in kw or "vp of ai" in kw:
        return "head_of_ai"
    if "chief data" in kw:
        return "chief_data_officer"
    return "other"


def enrich_with_linkedin(hiring_signal: dict, company_name: str) -> dict:
    """
    Enrich an existing hiring_signal_brief with LinkedIn signals.
    Call this from enrichment_pipeline.py after get_hiring_signal().
    Falls back gracefully if SerpAPI is unavailable.
    """
    linkedin = get_linkedin_signal(company_name)

    # Merge leadership change
    if linkedin["leadership_change"]["detected"]:
        existing_lc = hiring_signal.get("buying_window_signals", {}).get("leadership_change", {})
        if not existing_lc.get("detected"):
            if "buying_window_signals" not in hiring_signal:
                hiring_signal["buying_window_signals"] = {}
            hiring_signal["buying_window_signals"]["leadership_change"] = {
                "detected":        True,
                "role":            linkedin["leadership_change"]["role"],
                "new_leader_name": linkedin["leadership_change"]["name"],
                "started_at":      linkedin["leadership_change"]["started_at"],
                "source_url":      linkedin["leadership_change"].get("source_url", ""),
            }
            print(f"[LinkedIn] Added leadership_change to hiring signal")

    # Merge open roles
    existing_velocity = hiring_signal.get("hiring_velocity", {})
    existing_count    = existing_velocity.get("open_roles_today", 0)
    linkedin_count    = linkedin["open_roles_linkedin"]

    if linkedin_count > 0:
        combined = existing_count + linkedin_count
        if "hiring_velocity" not in hiring_signal:
            hiring_signal["hiring_velocity"] = {}
        hiring_signal["hiring_velocity"]["open_roles_today"] = combined
        hiring_signal["hiring_velocity"]["sources"] = list(set(
            hiring_signal["hiring_velocity"].get("sources", []) + ["linkedin_public"]
        ))

        # Recalculate velocity label
        prior = existing_velocity.get("open_roles_60_days_ago", 0)
        if prior > 0 and combined > 0:
            ratio = combined / prior
            if ratio >= 3.0:
                hiring_signal["hiring_velocity"]["velocity_label"] = "tripled_or_more"
            elif ratio >= 2.0:
                hiring_signal["hiring_velocity"]["velocity_label"] = "doubled"
            elif ratio >= 1.2:
                hiring_signal["hiring_velocity"]["velocity_label"] = "increased_modestly"

        existing_titles = hiring_signal.get("_all_open_titles", [])
        hiring_signal["_all_open_titles"] = existing_titles + linkedin["role_titles"]
        print(f"[LinkedIn] Added {linkedin_count} roles. Total now: {combined}")

    # Record in data_sources_checked
    sources = hiring_signal.get("data_sources_checked", [])
    sources.append({
        "source":     "linkedin_serpapi",
        "status":     "success" if linkedin_count > 0 or linkedin["leadership_change"]["detected"] else "no_data",
        "fetched_at": linkedin["retrieved_at"],
    })
    hiring_signal["data_sources_checked"] = sources

    return hiring_signal


if __name__ == "__main__":
    serp_key = os.getenv("SERP_API_KEY", "")
    if not serp_key:
        print("SERP_API_KEY not set in .env")
        print("Add: SERP_API_KEY=your_serpapi_key")
    else:
        print("=== LinkedIn Signal Test: Stripe ===")
        r = get_linkedin_signal("Stripe")
        print(f"Leadership change: {r['leadership_change']['detected']}")
        print(f"Open roles found:  {r['open_roles_linkedin']}")
        print(f"Role titles:       {r['role_titles'][:3]}")
        print(f"Confidence:        {r['signal_confidence']}")
        print()

        print("=== LinkedIn Signal Test: Figma ===")
        r2 = get_linkedin_signal("Figma")
        print(f"Leadership change: {r2['leadership_change']['detected']}")
        print(f"Open roles found:  {r2['open_roles_linkedin']}")
        print(f"Confidence:        {r2['signal_confidence']}")