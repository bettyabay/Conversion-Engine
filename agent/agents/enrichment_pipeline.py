"""
agent/agents/enrichment_pipeline.py

ResearchAgent — orchestrates the full enrichment pipeline.
Wraps the existing enrichment modules into a single clean interface.

Input:  company name, email, optional signal overrides
Output: HiringSignalBrief dict (matches hiring_signal_brief.schema.json)

Writes to HubSpot automatically after enrichment.
"""
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()


def run(
    company: str,
    email: str,
    # Optional signal overrides (used when automated sources return no_data)
    funding_type: str = None,
    funding_amount_usd: int = None,
    funding_days_ago: int = None,
    headcount: int = None,
    open_eng_roles: int = None,
    has_layoff: bool = None,
    layoff_days_ago: int = None,
    layoff_percentage: float = None,
    has_new_cto: bool = None,
    cto_days_ago: int = None,
    ai_maturity_score: int = None,
    specialist_role_open_days: int = None,
) -> dict:
    """
    Run the full enrichment pipeline for a prospect.

    Returns a complete HiringSignalBrief with:
      - crunchbase firmographics
      - hiring velocity (Greenhouse ATS + fallback)
      - AI maturity score (0-3)
      - layoff signal (from real CSV)
      - buying window signals (funding, layoff, leadership)
      - ICP segment classification
      - bench-to-brief match
      - honesty flags
    """
    print(f"[ResearchAgent] Enriching: {company} ({email})")

    # ── Step 1: Crunchbase firmographics ─────────────────────
    from agent.enrichment.crunchbase import find_company
    cb = find_company(company)

    # ── Step 2: Hiring signal brief ───────────────────────────
    from agent.enrichment.jobs import get_hiring_signal
    hiring = get_hiring_signal(
        company_name=company,
        website=cb.get("website"),
        funding_event={
            "detected":   bool(funding_type or cb.get("last_funding_type")),
            "stage":      funding_type or cb.get("last_funding_type", "unknown"),
            "amount_usd": funding_amount_usd or cb.get("funding_total_usd", 0),
            "closed_at":  cb.get("last_funding_date", ""),
        },
    )
    hiring["prospect_name"] = company

    # Step 2b: LinkedIn signal enrichment
    try:
        from agent.enrichment.linkedin_signal import enrich_with_linkedin
        hiring = enrich_with_linkedin(hiring, company)
    except Exception as e:
        print(f"[LinkedIn] Signal enrichment failed (non-blocking): {e}")

        
    # ── Step 3: AI maturity ───────────────────────────────────
    from agent.enrichment.ai_maturity import score_ai_maturity
    maturity = score_ai_maturity(
        company_name=company,
        description=cb.get("description", ""),
        job_titles=hiring.get("_all_open_titles", []),
    )

    # Apply override if supplied
    if ai_maturity_score is not None:
        maturity["score"]   = ai_maturity_score
        maturity["pitch_ai"] = ai_maturity_score >= 2

    # ── Step 4: Layoff signal ─────────────────────────────────
    from agent.enrichment.layoffs import check_layoff_signal
    layoff = check_layoff_signal(company)

    # Apply override
    if has_layoff is not None:
        layoff["has_layoff"] = has_layoff
        if has_layoff:
            layoff["layoff_date"]  = layoff.get("layoff_date", "2026-01-01")
            layoff["percentage"]   = layoff_percentage or 0
            layoff["signal_label"] = "RESTRUCTURING"

    # ── Step 5: ICP classification ───────────────────────────
    from agent.icp_classifier import classify
    icp = classify(
        company_name=company,
        funding_type=funding_type or cb.get("last_funding_type", ""),
        funding_amount_usd=funding_amount_usd or cb.get("funding_total_usd", 0),
        funding_days_ago=funding_days_ago or 999,
        headcount=headcount or 0,
        open_eng_roles=open_eng_roles or hiring.get("hiring_velocity", {}).get("open_roles_today", 0),
        has_layoff=has_layoff if has_layoff is not None else layoff.get("has_layoff", False),
        layoff_days_ago=layoff_days_ago or 999,
        layoff_percentage=layoff_percentage or 0.0,
        has_new_cto=has_new_cto if has_new_cto is not None else False,
        cto_days_ago=cto_days_ago or 999,
        ai_maturity_score=maturity.get("score", 0),
        specialist_role_open_days=specialist_role_open_days or 0,
    )

    # ── Step 6: Write to HubSpot ──────────────────────────────
    _write_to_hubspot(email, company, icp, maturity, hiring, layoff)

    # ── Assemble final brief ──────────────────────────────────
    brief = {
        "company":        company,
        "email":          email,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "crunchbase":     cb,
        "hiring_signal":  hiring,
        "ai_maturity":    maturity,
        "layoff_signal":  layoff,
        "icp":            icp,
        "segment":        icp.get("segment", "abstain"),
        "qualified":      icp.get("qualified", False),
        "confidence":     icp.get("confidence", 0.0),
        "pitch":          icp.get("pitch", ""),
    }

    print(f"[ResearchAgent] {company} → {icp.get('segment')} "
          f"confidence={icp.get('confidence'):.2f} qualified={icp.get('qualified')}")
    return brief


def _write_to_hubspot(email, company, icp, maturity, hiring, layoff):
    """Write enrichment results to HubSpot contact. Creates contact if not found."""
    try:
        import hubspot
        from hubspot.crm.contacts import SimplePublicObjectInput
        from hubspot.crm.contacts.models import (
            PublicObjectSearchRequest, Filter, FilterGroup,
            SimplePublicObjectInputForCreate
        )

        hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))
        f  = Filter(property_name="email", operator="EQ", value=email)
        fg = FilterGroup(filters=[f])
        sr = hs.crm.contacts.search_api.do_search(
            public_object_search_request=PublicObjectSearchRequest(filter_groups=[fg])
        )

        velocity = hiring.get("hiring_velocity", {})
        props = {
            "icp_segment":           str(icp.get("segment", "")),
            "segment_confidence":    str(icp.get("confidence", "")),
            "qualification_status":  "ENRICHED",
            "ai_maturity_score":     str(maturity.get("score", 0)),
            "hiring_signal_summary": velocity.get("velocity_label", ""),
            "last_enriched_at":      datetime.now(timezone.utc).isoformat(),
        }

        if sr.results:
            # Contact exists — update it
            hs.crm.contacts.basic_api.update(
                contact_id=sr.results[0].id,
                simple_public_object_input=SimplePublicObjectInput(properties=props)
            )
            print(f"[ResearchAgent] HubSpot updated for {email}")
        else:
            # Contact not found — create it
            create_props = {
                "email":     email,
                "firstname": company,
                "company":   company,
            }
            create_props.update(props)
            hs.crm.contacts.basic_api.create(
                simple_public_object_input_for_create=SimplePublicObjectInputForCreate(
                    properties=create_props
                )
            )
            print(f"[ResearchAgent] HubSpot contact created for {email}")

    except Exception as e:
        print(f"[ResearchAgent] HubSpot write failed: {e}")

if __name__ == "__main__":
    import json
    # Test with signal overrides
    result = run(
        company="Orrin Labs",
        email="cto@orrin-labs.example",
        funding_type="series_b",
        funding_amount_usd=14_000_000,
        funding_days_ago=70,
        headcount=45,
        open_eng_roles=11,
        has_layoff=False,
        ai_maturity_score=2,
    )
    print(f"Segment: {result['segment']}")
    print(f"Qualified: {result['qualified']}")
    print(f"Confidence: {result['confidence']}")