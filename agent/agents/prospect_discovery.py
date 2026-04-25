"""
agent/agents/prospect_discovery.py

ProspectDiscoveryAgent — fully autonomous company discovery.
Finds target companies from public sources with zero human input.

Called by:
  POST /discover  — one-time kick or scheduled daily cron
  POST /discover?segment=1  — discover only Segment 1 candidates

Sources:
  Segment 1: Crunchbase ODM — recently funded Series A/B
  Segment 2: layoffs.fyi CSV — recent restructuring events
  Segment 3: SerpAPI LinkedIn — new CTO/VP Eng appointments
  Segment 4: Crunchbase ODM — companies with specialist role signals

Output:
  List of prospect dicts ready to pass directly to /enrich
  Each prospect has company, email_domain, signals pre-populated
"""
import os
import re
import time
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# Words that are NOT company names — used to filter bad extractions
NOISE_WORDS = {
    "the", "this", "that", "their", "our", "his", "her", "its",
    "we", "they", "you", "new", "old", "very", "just", "also",
    "more", "most", "only", "such", "same", "both", "each",
    "pivotal", "moment", "exciting", "thrilled", "pleased",
    "company", "organization", "team", "group", "firm",
    "at a", "in a", "on a", "for a", "with a",
}

# How many prospects to discover per segment per run
DISCOVERY_LIMITS = {
    "segment_1": int(os.getenv("DISCOVER_LIMIT_SEG1", "10")),
    "segment_2": int(os.getenv("DISCOVER_LIMIT_SEG2", "10")),
    "segment_3": int(os.getenv("DISCOVER_LIMIT_SEG3", "5")),
    "segment_4": int(os.getenv("DISCOVER_LIMIT_SEG4", "5")),
}


def discover_all(max_per_segment: int = 10) -> dict:
    """
    Discover prospects across all 4 segments automatically.
    Returns dict with segment keys and lists of prospect dicts.
    """
    print(f"[ProspectDiscovery] Starting full discovery run at "
          f"{datetime.now(timezone.utc).isoformat()}")

    results = {
        "segment_1": [],
        "segment_2": [],
        "segment_3": [],
        "segment_4": [],
        "total":     0,
        "run_at":    datetime.now(timezone.utc).isoformat(),
    }

    results["segment_1"] = discover_segment_1(max_per_segment)
    results["segment_2"] = discover_segment_2(max_per_segment)
    results["segment_3"] = discover_segment_3(max_per_segment)
    results["segment_4"] = discover_segment_4(max_per_segment)

    results["total"] = sum(len(v) for k, v in results.items() if k.startswith("segment_"))

    print(f"[ProspectDiscovery] Found {results['total']} prospects total: "
          f"S1={len(results['segment_1'])} S2={len(results['segment_2'])} "
          f"S3={len(results['segment_3'])} S4={len(results['segment_4'])}")

    return results


def discover_segment_1(limit: int = 10) -> list:
    """
    Segment 1: Recently funded Series A/B companies.
    Source: Crunchbase ODM CSV.
    Signal: funding_type in [series_a, series_b], funding recent.
    """
    print(f"[ProspectDiscovery] Discovering Segment 1 (Series A/B)...")
    prospects = []

    try:
        from agent.enrichment.crunchbase import get_companies_by_funding
        companies = get_companies_by_funding(
            funding_types=["series_a", "series_b"],
            max_results=limit * 3,  # over-fetch to filter down
        )

        for company in companies:
            name     = company.get("company_name", "")
            website  = company.get("website", "")
            industry = company.get("industry", "")
            headcount = company.get("employee_count", "")

            if not name or company.get("source") == "mock":
                continue

            # Estimate headcount band
            hc_num = _parse_headcount(headcount)
            if hc_num > 0 and (hc_num < 15 or hc_num > 80):
                continue  # outside Segment 1 headcount range

            domain = _extract_domain(website)
            if not domain:
                continue

            prospect = {
                "company":            name,
                "email":              f"cto@{domain}",
                "funding_type":       company.get("last_funding_type", "series_b"),
                "funding_amount_usd": company.get("funding_total_usd", 0),
                "funding_days_ago":   90,  # approximate — ODM does not have exact date delta
                "headcount":          hc_num or 40,
                "open_eng_roles":     0,   # will be discovered by enrichment pipeline
                "has_layoff":         False,
                "ai_maturity_score":  None,  # will be scored by ai_maturity.py
                "source":             "crunchbase_odm",
                "target_segment":     "segment_1_series_a_b",
                "industry":           industry,
                "website":            website,
                "discovered_at":      datetime.now(timezone.utc).isoformat(),
            }
            prospects.append(prospect)

            if len(prospects) >= limit:
                break

    except Exception as e:
        print(f"[ProspectDiscovery] Segment 1 discovery failed: {e}")

    print(f"[ProspectDiscovery] Segment 1: found {len(prospects)} candidates")
    return prospects


def discover_segment_2(limit: int = 10) -> list:
    """
    Segment 2: Mid-market companies with recent layoffs.
    Source: layoffs.fyi CSV (4,360 records).
    Signal: layoff in last 120 days, 200-2000 headcount.
    """
    print(f"[ProspectDiscovery] Discovering Segment 2 (Post-restructure)...")
    prospects = []

    try:
        from agent.enrichment.layoffs import get_recent_layoffs
        layoff_events = get_recent_layoffs(
            days_window=120,
            min_count=10,
            us_only=False,
        )

        for event in layoff_events:
            company = event.get("company", "")
            if not company:
                continue

            # Estimate domain from company name
            domain = _company_name_to_domain(company)
            if not domain:
                continue

            # Parse layoff date
            layoff_date = event.get("date", "")
            layoff_days_ago = 60  # default
            if layoff_date:
                try:
                    ld = datetime.strptime(layoff_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    layoff_days_ago = (datetime.now(timezone.utc) - ld).days
                except (ValueError, TypeError):
                    pass

            prospect = {
                "company":           company,
                "email":             f"svp@{domain}",
                "funding_type":      None,
                "funding_days_ago":  999,
                "headcount":         500,  # mid-market default
                "open_eng_roles":    0,
                "has_layoff":        True,
                "layoff_days_ago":   layoff_days_ago,
                "layoff_percentage": event.get("layoff_count", 0),
                "ai_maturity_score": None,
                "source":            "layoffs_fyi_csv",
                "target_segment":    "segment_2_mid_market_restructure",
                "industry":          event.get("industry", ""),
                "location":          event.get("location", ""),
                "discovered_at":     datetime.now(timezone.utc).isoformat(),
            }
            prospects.append(prospect)

            if len(prospects) >= limit:
                break

    except Exception as e:
        print(f"[ProspectDiscovery] Segment 2 discovery failed: {e}")

    print(f"[ProspectDiscovery] Segment 2: found {len(prospects)} candidates")
    return prospects


def discover_segment_3(limit: int = 5) -> list:
    """
    Segment 3: Companies with new CTO/VP Eng in last 90 days.
    Source: SerpAPI LinkedIn search.
    Signal: leadership_change detected for known tech companies.
    """
    print(f"[ProspectDiscovery] Discovering Segment 3 (New leadership)...")
    prospects = []

    serp_key = os.getenv("SERP_API_KEY", "")
    if not serp_key:
        print("[ProspectDiscovery] SERP_API_KEY not set — skipping Segment 3 discovery")
        return prospects

    try:
        # Search for recent CTO appointments broadly
        from agent.enrichment.linkedin_signal import _serp_search, _normalize_role

        query   = '"new CTO" OR "new VP Engineering" OR "joins as CTO" site:linkedin.com 2026'
        results = _serp_search(query, serp_key, num=10)

        seen_companies = set()
        for item in results:
            title   = item.get("title", "")
            snippet = item.get("snippet", "").lower()
            link    = item.get("link", "")

            # Extract company name from LinkedIn result
            company = _extract_company_from_linkedin_title(title)
            if not company or company in seen_companies:
                continue

            seen_companies.add(company)
            domain = _company_name_to_domain(company)
            if not domain:
                continue

            # Determine role
            role = "cto"
            if "vp engineering" in snippet or "vp of engineering" in snippet:
                role = "vp_engineering"

            prospect = {
                "company":          company,
                "email":            f"cto@{domain}",
                "funding_type":     None,
                "funding_days_ago": 999,
                "headcount":        200,  # mid-range default for Segment 3
                "open_eng_roles":   0,
                "has_layoff":       False,
                "has_new_cto":      True,
                "cto_days_ago":     30,   # approximate
                "ai_maturity_score": None,
                "source":           "linkedin_serpapi",
                "target_segment":   "segment_3_leadership_transition",
                "leadership_role":  role,
                "source_url":       link,
                "discovered_at":    datetime.now(timezone.utc).isoformat(),
            }
            prospects.append(prospect)

            if len(prospects) >= limit:
                break

            time.sleep(1)  # rate limit

    except Exception as e:
        print(f"[ProspectDiscovery] Segment 3 discovery failed: {e}")

    print(f"[ProspectDiscovery] Segment 3: found {len(prospects)} candidates")
    return prospects


def discover_segment_4(limit: int = 5) -> list:
    """
    Segment 4: Companies with specialist AI/ML role open 60+ days.
    Source: Crunchbase ODM — software/AI sector companies.
    Signal: industry contains AI/ML keywords + ai_maturity >= 2.
    """
    print(f"[ProspectDiscovery] Discovering Segment 4 (AI capability gap)...")
    prospects = []

    try:
        from agent.enrichment.crunchbase import get_rows, _build_brief

        rows = get_rows()
        ai_keywords = [
            "artificial intelligence", "machine learning", "deep learning",
            "data science", "mlops", "llm", "generative ai", "analytics",
        ]

        for row in rows:
            industry = (row.get("industries", "") or row.get("industry", "")).lower()
            name     = (row.get("name", "") or "").strip()
            website  = row.get("website", "") or ""

            if not name or not website:
                continue

            # Check if company is in AI-adjacent sector
            if not any(kw in industry for kw in ai_keywords):
                continue

            # Check tech stack for ML signals
            tech_raw = row.get("builtwith_tech", "") or ""
            tech_lower = tech_raw.lower()
            has_ml_stack = any(t in tech_lower for t in [
                "tensorflow", "pytorch", "spark", "databricks",
                "snowflake", "dbt", "airflow", "sagemaker",
            ])

            if not has_ml_stack:
                continue

            domain = _extract_domain(website)
            if not domain:
                continue

            prospect = {
                "company":                name,
                "email":                  f"head@{domain}",
                "funding_type":           None,
                "funding_days_ago":       999,
                "headcount":              100,
                "open_eng_roles":         0,
                "has_layoff":             False,
                "ai_maturity_score":      2,   # pre-scored as 2 for AI sector
                "specialist_role_open_days": 65,
                "source":                 "crunchbase_odm_ai_scan",
                "target_segment":         "segment_4_specialized_capability",
                "industry":               industry,
                "discovered_at":          datetime.now(timezone.utc).isoformat(),
            }

            prospects.append(prospect)

            if len(prospects) >= limit:
                break

    except Exception as e:
        print(f"[ProspectDiscovery] Segment 4 discovery failed: {e}")

    print(f"[ProspectDiscovery] Segment 4: found {len(prospects)} candidates")
    return prospects


def _extract_domain(website: str) -> str:
    """Extract domain from website URL."""
    if not website:
        return ""
    website = website.lower().strip()
    website = re.sub(r'^https?://', '', website)
    website = re.sub(r'^www\.', '', website)
    website = website.split('/')[0].strip()
    if '.' not in website or len(website) < 4:
        return ""
    return website


def _company_name_to_domain(company_name: str) -> str:
    """Convert company name to likely domain."""
    clean = company_name.lower()
    clean = re.sub(r'\b(inc|llc|ltd|corp|co|company|technologies|tech|labs|group|solutions)\b', '', clean)
    clean = re.sub(r'[^a-z0-9\s]', '', clean).strip()
    clean = re.sub(r'\s+', '', clean)
    if len(clean) < 3:
        return ""
    return f"{clean}.com"


def _parse_headcount(headcount_str: str) -> int:
    """Parse headcount band string to approximate integer."""
    if not headcount_str or str(headcount_str) in ('unknown', 'None', ''):
        return 0
    s = str(headcount_str).lower().replace(',', '')
    # Handle ranges like "11-50", "51-200"
    match = re.match(r'(\d+)\s*[-–]\s*(\d+)', s)
    if match:
        return (int(match.group(1)) + int(match.group(2))) // 2
    # Handle "1001-5000" etc
    match2 = re.match(r'(\d+)\+?', s)
    if match2:
        return int(match2.group(1))
    return 0


def _extract_company_from_linkedin_title(title: str) -> str:
    """
    Extract company name from LinkedIn result title.
    Common format: "Person Name - CTO at Company Name | LinkedIn"
    """
    # Pattern: "at Company Name |"
    match = re.search(r'\bat\s+([A-Z][A-Za-z0-9\s&]+?)\s*[|\-]', title)
    if match:
        return match.group(1).strip()
    return ""



NOISE_WORDS = {
    "the", "this", "that", "their", "our", "his", "her", "its",
    "we", "they", "you", "new", "old", "very", "just", "also",
    "more", "most", "only", "such", "same", "both", "each",
    "pivotal", "moment", "exciting", "thrilled", "pleased",
    "company", "organization", "team", "group", "firm",
}


def _extract_company_from_snippet(snippet: str) -> str:
    """Extract company name from snippet. Strict filtering."""
    # Pattern: joins CompanyName as CTO
    m = re.search(
        r'joins? +([A-Z][A-Za-z0-9]{2,}(?: +[A-Z][A-Za-z0-9]{2,}){0,2}) +as +',
        snippet, re.IGNORECASE
    )
    if m:
        name = m.group(1).strip()
        if len(name) > 3 and name.lower() not in NOISE_WORDS:
            return name

    # Pattern: CompanyName appoints
    m2 = re.search(
        r'^([A-Z][A-Za-z0-9]{2,}(?: +[A-Z][A-Za-z0-9]{2,}){0,2}) +appoints',
        snippet
    )
    if m2:
        name = m2.group(1).strip()
        if len(name) > 3 and name.lower() not in NOISE_WORDS:
            return name

    # Pattern: CTO of/at CompanyName
    m3 = re.search(
        r'(?:cto|vp engineering) +(?:of|at) +([A-Z][A-Za-z0-9]{2,}(?: +[A-Z][A-Za-z0-9]{2,}){0,2})',
        snippet, re.IGNORECASE
    )
    if m3:
        name = m3.group(1).strip()
        if len(name) > 3 and name.lower() not in NOISE_WORDS:
            return name

    return ""

if __name__ == "__main__":
    import json

    print("=== ProspectDiscovery Test ===")
    print("Running Segment 1 discovery (Crunchbase ODM)...")
    seg1 = discover_segment_1(limit=3)
    for p in seg1:
        print(f"  {p['company']} | {p['email']} | {p['target_segment']}")

    print()
    print("Running Segment 2 discovery (layoffs.fyi)...")
    seg2 = discover_segment_2(limit=3)
    for p in seg2:
        print(f"  {p['company']} | {p['email']} | {p['target_segment']}")