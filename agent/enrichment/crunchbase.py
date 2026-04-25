"""
agent/enrichment/crunchbase.py

Crunchbase ODM loader — reads the real CSV from Luminati/Bright Data.

Column mapping for this specific dataset:
  name             → company name
  about            → short description
  full_description → long description
  industries       → sector/industry (JSON list)
  num_employees    → headcount band
  uuid             → crunchbase ID
  funding_rounds_list → funding history (JSON)
  founded_date     → founded year
  website          → website URL
  location         → HQ location (JSON)
  country_code     → country
  builtwith_tech   → tech stack
  leadership_hire  → leadership changes
"""
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CSV_PATHS = [
    Path("data/crunchbase_odm.csv"),
    Path("data/crunchbase_companies.csv"),
    Path("data/Crunchbase_Dataset_Sample.csv"),
    Path("crunchbase_odm.csv"),
]

_rows: list = None
_cache: dict = {}


def _load_csv() -> list:
    global _rows
    if _rows is not None:
        return _rows
    for path in CSV_PATHS:
        if path.exists():
            rows = []
            try:
                with open(path, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        rows.append(row)
                print(f"[Crunchbase] Loaded {len(rows)} records from {path}")
                _rows = rows
                return rows
            except Exception as e:
                print(f"[Crunchbase] Failed to load {path}: {e}")
    print("[Crunchbase] ODM CSV not found — all lookups return mock briefs")
    _rows = []
    return []

def get_rows() -> list:
    """Public accessor for loaded ODM rows. Used by competitor_analyst.py."""
    return _load_csv()
    
def get_rows() -> list:
    """Public accessor for the loaded ODM rows. Used by competitor_analyst.py."""
    return _load_csv()

def _normalize(name: str) -> str:
    """Normalize company name for fuzzy matching."""
    return re.sub(r'[^a-z0-9\s]', '', name.lower()).strip()


def _parse_json_field(value: str) -> any:
    """Safely parse a JSON field that may be a string, list, or dict."""
    if not value or value in ('{}', '[]', 'None', 'nan', ''):
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _extract_location(row: dict) -> str:
    """Extract readable location from the location JSON field."""
    loc = _parse_json_field(row.get("location", ""))
    if isinstance(loc, list) and loc:
        # Format: [{"name":"City",...}, {"name":"State",...}, {"name":"Country",...}]
        names = [item.get("name", "") for item in loc if isinstance(item, dict)]
        # Take city and country (first and last)
        if len(names) >= 2:
            return f"{names[0]}, {names[-1]}"
        return names[0] if names else ""
    if isinstance(loc, str) and loc:
        return loc
    # Fall back to region field
    region = row.get("region", "") or row.get("headquarters_regions", "")
    if region:
        parsed = _parse_json_field(region)
        if isinstance(parsed, list) and parsed:
            return parsed[0].get("name", "") if isinstance(parsed[0], dict) else str(parsed[0])
    return row.get("country_code", "")


def _extract_industry(row: dict) -> str:
    """Extract readable industry from the industries JSON field."""
    industries = _parse_json_field(row.get("industries", ""))
    if isinstance(industries, list) and industries:
        names = []
        for item in industries:
            if isinstance(item, dict):
                names.append(item.get("value", item.get("name", "")))
            elif isinstance(item, str):
                names.append(item)
        return ", ".join(names[:3]) if names else "Software"
    if isinstance(industries, str) and industries:
        return industries
    return "Software"


def _extract_funding(row: dict) -> tuple:
    """
    Extract last funding type, amount, and date from funding_rounds_list.
    Returns (funding_type, amount_usd, closed_at_date)
    """
    rounds_raw = row.get("funding_rounds_list", "") or row.get("funding_rounds", "")
    rounds = _parse_json_field(rounds_raw)

    if not rounds or not isinstance(rounds, list):
        return "unknown", 0, None

    # Sort by date descending — most recent first
    def get_date(r):
        return r.get("announced_on", "") or r.get("date", "") or ""

    try:
        rounds_sorted = sorted(rounds, key=get_date, reverse=True)
    except Exception:
        rounds_sorted = rounds

    latest = rounds_sorted[0] if rounds_sorted else {}

    # Funding type
    raw_type = (
        latest.get("funding_type", "") or
        latest.get("series", "") or
        latest.get("investment_type", "") or
        ""
    ).lower().replace(" ", "_").replace("-", "_")

    # Normalize to schema enum
    type_map = {
        "series_a": "series_a", "seriesa": "series_a",
        "series_b": "series_b", "seriesb": "series_b",
        "series_c": "series_c", "seriesc": "series_c",
        "series_d": "series_d_plus", "series_e": "series_d_plus",
        "seed": "seed", "pre_seed": "seed", "pre-seed": "seed",
        "angel": "seed", "convertible_note": "seed",
        "ipo": "series_d_plus", "post_ipo_equity": "series_d_plus",
        "debt_financing": "debt", "venture": "series_a",
        "grant": "other", "corporate_round": "other",
    }
    funding_type = type_map.get(raw_type, "other" if raw_type else "unknown")

    # Amount
    amount = 0
    amount_raw = (
        latest.get("money_raised", "") or
        latest.get("raised_amount_usd", "") or
        latest.get("amount", "") or
        ""
    )
    if amount_raw:
        try:
            clean = str(amount_raw).replace("$", "").replace(",", "").replace(" ", "")
            amount = int(float(clean))
        except (ValueError, TypeError):
            amount = 0

    # Date
    closed_at = latest.get("announced_on", "") or latest.get("date", "")

    return funding_type, amount, closed_at


def _extract_headcount(row: dict) -> str:
    """Extract employee count band."""
    raw = row.get("num_employees", "") or row.get("employee_count", "")
    if not raw or raw in ('{}', 'None', 'nan', ''):
        return "unknown"

    # Try parsing as JSON (sometimes it's a dict)
    parsed = _parse_json_field(str(raw))
    if isinstance(parsed, dict):
        val = parsed.get("value", parsed.get("name", ""))
        return str(val) if val else "unknown"

    return str(raw).strip()


def _extract_tech_stack(row: dict) -> list:
    """Extract tech stack from builtwith_tech field."""
    raw = row.get("builtwith_tech", "") or row.get("siftery_products", "")
    if not raw:
        return []
    parsed = _parse_json_field(raw)
    if isinstance(parsed, list):
        techs = []
        for item in parsed[:10]:
            if isinstance(item, dict):
                name = item.get("name", item.get("value", ""))
                if name:
                    techs.append(name)
            elif isinstance(item, str):
                techs.append(item)
        return techs
    return []


def _extract_leadership_change(row: dict) -> dict:
    """Check for recent leadership changes in leadership_hire field."""
    raw = row.get("leadership_hire", "")
    if not raw:
        return {"detected": False}
    parsed = _parse_json_field(raw)
    if isinstance(parsed, list) and parsed:
        latest = parsed[0] if isinstance(parsed[0], dict) else {}
        role = latest.get("title", latest.get("role", "")).lower()
        is_cto = any(k in role for k in ["cto", "chief technology", "vp eng", "vp of eng", "head of eng"])
        return {
            "detected":        is_cto,
            "role":            latest.get("title", ""),
            "new_leader_name": latest.get("name", ""),
            "started_at":      latest.get("date", ""),
        }
    return {"detected": False}


def find_company(company_name: str) -> dict:
    """
    Find a company in the Crunchbase ODM.
    Returns a firmographic brief dict.
    """
    cache_key = company_name.lower().strip()
    if cache_key in _cache:
        return _cache[cache_key]

    rows = _load_csv()
    name_norm = _normalize(company_name)

    best_match = None
    best_score = 0

    for row in rows:
        row_name = row.get("name", "").strip()
        if not row_name:
            continue
        row_norm = _normalize(row_name)

        # Exact match — highest priority
        if row_norm == name_norm:
            best_match = row
            break

        # Substring match — score by length similarity
        if name_norm in row_norm or row_norm in name_norm:
            score = len(name_norm) / max(len(row_norm), 1)
            if score > best_score:
                best_score = score
                best_match = row

    if best_match:
        result = _build_brief(best_match, company_name)
        _cache[cache_key] = result
        return result

    result = _build_mock_brief(company_name)
    _cache[cache_key] = result
    return result


def _build_brief(row: dict, company_name: str) -> dict:
    """Build firmographic brief from a real Crunchbase row."""
    name = row.get("name", company_name).strip()

    # Description — prefer short, fall back to full
    description = (
        row.get("about", "") or
        row.get("full_description", "")[:300] or
        f"{name} is a technology company."
    ).strip()

    # Industry
    industry = _extract_industry(row)

    # Location
    location = _extract_location(row)

    # Headcount
    headcount = _extract_headcount(row)

    # Funding
    funding_type, amount_usd, closed_at = _extract_funding(row)

    # Website
    website = row.get("website", "") or f"https://www.{name.lower().replace(' ', '-')}.com"

    # Founded year
    founded = row.get("founded_date", "") or ""
    if founded and len(str(founded)) >= 4:
        founded = str(founded)[:4]

    # UUID as crunchbase_id
    cb_id = row.get("uuid", "") or row.get("id", "") or f"cb_{name.lower().replace(' ','_')}"

    # Tech stack
    tech_stack = _extract_tech_stack(row)

    # Leadership change
    leadership = _extract_leadership_change(row)

    print(f"[Crunchbase] Found: {name} | {funding_type} | {headcount} employees | {location}")

    return {
        "crunchbase_id":      cb_id,
        "company_name":       name,
        "description":        description[:500],
        "employee_count":     headcount,
        "hq_location":        location,
        "funding_total_usd":  amount_usd,
        "last_funding_type":  funding_type,
        "last_funding_date":  closed_at,
        "industry":           industry[:100],
        "website":            website,
        "founded_year":       founded,
        "tech_stack":         tech_stack,
        "leadership_change":  leadership,
        "last_enriched_at":   datetime.now(timezone.utc).isoformat(),
        "source":             "crunchbase_odm",
        "confidence":         "high",
    }


def _build_mock_brief(company_name: str) -> dict:
    slug = company_name.lower().replace(" ", "_")
    print(f"[Crunchbase] Not found in ODM — returning mock brief for {company_name}")
    return {
        "crunchbase_id":      f"mock_{slug}",
        "company_name":       company_name,
        "description":        "Software company — no Crunchbase record found",
        "employee_count":     "11-50",
        "hq_location":        "San Francisco, US",
        "funding_total_usd":  5_000_000,
        "last_funding_type":  "seed",
        "last_funding_date":  "2024-01-01",
        "industry":           "Software, SaaS",
        "website":            f"https://www.{company_name.lower().replace(' ','-')}.com",
        "founded_year":       "2021",
        "tech_stack":         [],
        "leadership_change":  {"detected": False},
        "last_enriched_at":   datetime.now(timezone.utc).isoformat(),
        "source":             "mock",
        "confidence":         "low",
    }


def get_companies_by_funding(
    funding_types: list = None,
    max_results: int = 50,
) -> list:
    """Get companies from ODM matching funding type criteria."""
    rows    = _load_csv()
    results = []
    ftypes  = funding_types or ["series_a", "series_b"]

    for row in rows:
        name = (row.get("name", "") or "").strip()
        if not name:
            continue

        # Parse funding from the row directly
        ft, amount, date = _extract_funding(row)

        if ft in ftypes and amount > 0:
            brief = _build_brief(row, name)
            results.append(brief)

        if len(results) >= max_results:
            break

    return results


def get_stats() -> dict:
    rows = _load_csv()
    if not rows:
        return {"error": "ODM not loaded", "paths_checked": [str(p) for p in CSV_PATHS]}
    return {
        "total_records": len(rows),
        "columns":       list(rows[0].keys()),
        "csv_loaded":    True,
    }


if __name__ == "__main__":
    import sys

    print("=== Crunchbase ODM Stats ===")
    stats = get_stats()
    print(f"Records: {stats.get('total_records', 0)}")
    print(f"Columns (first 10): {stats.get('columns', [])[:10]}")

    print("\n=== Sample lookup: Stripe ===")
    r = find_company("Stripe")
    print(f"Found: {r['company_name']} | source={r['source']} | funding={r['last_funding_type']} | industry={r['industry']}")

    print("\n=== Sample lookup: Figma ===")
    r2 = find_company("Figma")
    print(f"Found: {r2['company_name']} | source={r2['source']} | funding={r2['last_funding_type']} | employees={r2['employee_count']}")

    print("\n=== Series A/B companies sample ===")
    companies = get_companies_by_funding(["series_a", "series_b"], max_results=5)
    for c in companies:
        print(f"  {c['company_name']} | {c['last_funding_type']} | {c['employee_count']} employees")