"""
agent/enrichment/crunchbase.py
Pulls firmographic signals from Crunchbase ODM sample.
"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
 
CRUNCHBASE_PATH = Path(__file__).parent.parent.parent / "data" / "crunchbase_odm_sample.json"
 
 
def find_company(company_name: str) -> dict:
    """
    Find a company in the Crunchbase ODM sample.
    Returns enrichment brief or mock brief if not found.
    """
    companies = _load()
    name_lower = company_name.lower().strip()
 
    for company in companies:
        cb_name = company.get("name", "").lower().strip()
        if name_lower in cb_name or cb_name in name_lower:
            return _build_brief(company)
 
    print(f"[Crunchbase] No match for '{company_name}' — using mock brief")
    return _mock_brief(company_name)
 
 
def _load() -> list:
    if not CRUNCHBASE_PATH.exists():
        print(f"[Crunchbase] Data file not found at {CRUNCHBASE_PATH}")
        return []
    with open(CRUNCHBASE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("companies", [])
 
 
def _build_brief(c: dict) -> dict:
    return {
        "crunchbase_id":      c.get("uuid", c.get("id", "unknown")),
        "company_name":       c.get("name", "unknown"),
        "description":        c.get("short_description", ""),
        "employee_count":     c.get("num_employees_enum", "unknown"),
        "hq_location":        f"{c.get('city','')} {c.get('country_code','')}".strip(),
        "funding_total_usd":  c.get("total_funding_usd", 0),
        "last_funding_type":  c.get("last_funding_type", "unknown"),
        "last_funding_date":  c.get("last_funding_at", "unknown"),
        "industry":           c.get("category_list", "unknown"),
        "website":            c.get("homepage_url", "unknown"),
        "founded_year":       c.get("founded_on", "unknown"),
        "last_enriched_at":   datetime.now(timezone.utc).isoformat(),
        "source":             "crunchbase_odm",
        "confidence":         "high",
    }
 
 
def _mock_brief(company_name: str) -> dict:
    """
    Synthetic brief for prospects not in the ODM sample.
    Used during the challenge week for demo purposes.
    """
    return {
        "crunchbase_id":      f"mock_{company_name.lower().replace(' ','_')}",
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
        "last_enriched_at":   datetime.now(timezone.utc).isoformat(),
        "source":             "mock",
        "confidence":         "low",
    }
 
 
if __name__ == "__main__":
    result = find_company("Turing Signal")
    print(json.dumps(result, indent=2))