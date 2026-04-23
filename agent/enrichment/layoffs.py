"""
agent/enrichment/layoffs.py
Detects restructuring/layoff signals for Segment 2 classification.
"""
import requests
from datetime import datetime, timezone


def check_layoff_signal(company_name: str) -> dict:
    """
    Check if a company has had recent layoffs.
    Returns layoff_signal dict.
    """
    # Try layoffs.fyi public data
    signal = _check_layoffs_fyi(company_name)
    if not signal:
        signal = _no_signal(company_name)
    return signal


def _check_layoffs_fyi(company_name: str) -> dict:
    try:
        url = "https://layoffs.fyi/api/layoffs"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        name_lower = company_name.lower()
        matches = [
            r for r in data
            if name_lower in r.get("company", "").lower()
        ]
        if not matches:
            return None
        latest = matches[0]
        return {
            "company_name":    company_name,
            "has_layoff":      True,
            "layoff_count":    latest.get("laid_off", "unknown"),
            "layoff_date":     latest.get("date", "unknown"),
            "percentage":      latest.get("percentage", "unknown"),
            "signal_label":    "RESTRUCTURING",
            "source":          "layoffs.fyi",
            "retrieved_at":    datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        print(f"[Layoffs] {e}")
        return None


def _no_signal(company_name: str) -> dict:
    return {
        "company_name":  company_name,
        "has_layoff":    False,
        "layoff_count":  0,
        "layoff_date":   None,
        "percentage":    None,
        "signal_label":  "NO_LAYOFF_SIGNAL",
        "source":        "layoffs.fyi",
        "retrieved_at":  datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(check_layoff_signal("Turing Signal"), indent=2))