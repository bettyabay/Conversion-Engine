"""
agent/enrichment/layoffs.py

Layoffs signal extractor — loads from the real layoffs.fyi CSV.

CSV columns: Company, Location_HQ, Industry, Laid_Off_Count,
             Percentage, Date, Source, Country, Stage, Funds_Raised_USD

Place the CSV at: data/layoffs.csv
Fallback: API call to layoffs.fyi if CSV not present.
"""
import csv
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Look for the CSV in multiple locations
CSV_PATHS = [
    Path("data/layoffs.csv"),
    Path("layoffs.csv"),
    Path("seed/layoffs.csv"),
]


def _load_csv() -> list:
    """Load layoffs CSV from disk. Returns list of dicts."""
    for path in CSV_PATHS:
        if path.exists():
            rows = []
            with open(path, encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
            print(f"[Layoffs] Loaded {len(rows)} records from {path}")
            return rows
    print("[Layoffs] CSV not found in any expected path — using API fallback")
    return []


def check_layoff_signal(
    company_name: str,
    days_window: int = 120,
) -> dict:
    """
    Check if a company has had a layoff event in the last N days.

    Args:
        company_name: Company name to search for
        days_window: How far back to look (default 120 days per ICP definition)

    Returns:
        dict with has_layoff, layoff_count, layoff_date, percentage,
        signal_label, source_url
    """
    rows = _load_csv()
    company_lower = company_name.lower().strip()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_window)

    matches = []
    for row in rows:
        row_company = row.get("Company", "").lower().strip()

        # Exact match or starts-with match
        if row_company == company_lower or company_lower in row_company or row_company in company_lower:
            # Parse date
            date_str = row.get("Date", "")
            try:
                row_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            if row_date >= cutoff:
                matches.append(row)

    if not matches:
        # Try API fallback
        api_result = _try_api_fallback(company_name, days_window)
        if api_result:
            return api_result

        return {
            "company_name":  company_name,
            "has_layoff":    False,
            "layoff_count":  0,
            "layoff_date":   None,
            "percentage":    None,
            "signal_label":  "NO_LAYOFF_SIGNAL",
            "source":        "layoffs_csv",
            "source_url":    None,
            "retrieved_at":  datetime.now(timezone.utc).isoformat(),
        }

    # Use the most recent match
    matches.sort(key=lambda r: r.get("Date", ""), reverse=True)
    best = matches[0]

    # Parse count and percentage
    count = 0
    try:
        count = int(best.get("Laid_Off_Count", 0) or 0)
    except (ValueError, TypeError):
        pass

    pct = None
    try:
        pct_raw = best.get("Percentage", "")
        if pct_raw:
            pct = float(pct_raw)
            # Convert to percentage if stored as decimal (0.12 → 12%)
            if pct <= 1.0:
                pct = round(pct * 100, 1)
    except (ValueError, TypeError):
        pass

    print(f"[Layoffs] Found layoff for {company_name}: {count} people on {best.get('Date')} ({pct}%)")

    return {
        "company_name":   company_name,
        "has_layoff":     True,
        "layoff_count":   count,
        "layoff_date":    best.get("Date"),
        "percentage":     pct,
        "industry":       best.get("Industry", ""),
        "location":       best.get("Location_HQ", ""),
        "stage":          best.get("Stage", ""),
        "signal_label":   "RESTRUCTURING",
        "source":         "layoffs_csv",
        "source_url":     best.get("Source", ""),
        "retrieved_at":   datetime.now(timezone.utc).isoformat(),
    }


def get_recent_layoffs(
    days_window: int = 120,
    min_count: int = 10,
    us_only: bool = False,
) -> list:
    """
    Get all recent layoff events in the window.
    Useful for finding Segment 2 prospects proactively.

    Returns list of dicts sorted by date descending.
    """
    rows = _load_csv()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_window)
    results = []

    for row in rows:
        date_str = row.get("Date", "")
        try:
            row_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue

        if row_date < cutoff:
            continue

        if us_only and row.get("Country", "") != "United States":
            continue

        count = 0
        try:
            count = int(row.get("Laid_Off_Count", 0) or 0)
        except (ValueError, TypeError):
            pass

        if count < min_count and count != 0:
            continue

        results.append({
            "company":      row.get("Company", ""),
            "industry":     row.get("Industry", ""),
            "location":     row.get("Location_HQ", ""),
            "country":      row.get("Country", ""),
            "stage":        row.get("Stage", ""),
            "layoff_count": count,
            "date":         date_str,
            "source_url":   row.get("Source", ""),
        })

    results.sort(key=lambda r: r["date"], reverse=True)
    return results


def _try_api_fallback(company_name: str, days_window: int) -> dict:
    """Try layoffs.fyi API as fallback when CSV is not available."""
    try:
        import requests
        resp = requests.get(
            "https://layoffs.fyi/api/layoffs",
            timeout=5,
            headers={"User-Agent": "TRP1-Week10-Research (trainee@trp1.example)"}
        )
        if resp.status_code == 200:
            data = resp.json()
            company_lower = company_name.lower()
            cutoff = datetime.now(timezone.utc) - timedelta(days=days_window)

            for item in data:
                if company_lower in item.get("company", "").lower():
                    date_str = item.get("date", "")
                    try:
                        item_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        if item_date >= cutoff:
                            return {
                                "company_name":  company_name,
                                "has_layoff":    True,
                                "layoff_count":  item.get("laid_off_count", 0),
                                "layoff_date":   date_str,
                                "percentage":    item.get("percentage"),
                                "signal_label":  "RESTRUCTURING",
                                "source":        "layoffs_fyi_api",
                                "source_url":    item.get("sources", ""),
                                "retrieved_at":  datetime.now(timezone.utc).isoformat(),
                            }
                    except (ValueError, TypeError):
                        continue
    except Exception as e:
        print(f"[Layoffs] API fallback failed: {e}")
    return None


def get_stats() -> dict:
    """Return summary stats about the loaded CSV."""
    rows = _load_csv()
    if not rows:
        return {"error": "No CSV loaded"}

    # Count by recent windows
    now = datetime.now(timezone.utc)
    windows = {30: 0, 60: 0, 90: 0, 120: 0}
    total_laid_off = 0

    for row in rows:
        date_str = row.get("Date", "")
        try:
            row_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            days_ago = (now - row_date).days
            for window in windows:
                if days_ago <= window:
                    windows[window] += 1
            count = int(row.get("Laid_Off_Count", 0) or 0)
            total_laid_off += count
        except (ValueError, TypeError):
            continue

    return {
        "total_records":   len(rows),
        "total_laid_off":  total_laid_off,
        "events_by_window": windows,
        "csv_loaded":      True,
    }


if __name__ == "__main__":
    import json

    # Test with known companies from the CSV
    print("=== Stats ===")
    print(json.dumps(get_stats(), indent=2))

    print("\n=== Check Meta (known layoff) ===")
    result = check_layoff_signal("Meta")
    print(json.dumps(result, indent=2))

    print("\n=== Check Orrin Labs (no layoff expected) ===")
    result2 = check_layoff_signal("Orrin Labs")
    print(json.dumps(result2, indent=2))

    print("\n=== Recent US layoffs (last 120 days) ===")
    recent = get_recent_layoffs(days_window=120, us_only=True)
    print(f"Found {len(recent)} US layoff events")
    for r in recent[:5]:
        print(f"  {r['company']}: {r['layoff_count']} people on {r['date']}")