"""
agent/hubspot_mcp.py
HubSpot CRM integration — contact management and deal tracking.
"""
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()


def get_client():
    import hubspot
    return hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))


def find_contact_by_email(email: str) -> dict:
    """Find a HubSpot contact by email address."""
    try:
        from hubspot.crm.contacts.models import PublicObjectSearchRequest, Filter, FilterGroup

        hs = get_client()
        f = Filter(property_name="email", operator="EQ", value=email)
        fg = FilterGroup(filters=[f])
        search = hs.crm.contacts.search_api.do_search(
            public_object_search_request=PublicObjectSearchRequest(filter_groups=[fg])
        )

        if search.results:
            contact = search.results[0]
            print(f"[HubSpot] Found contact {contact.id} for {email}")
            return {"id": contact.id, "properties": contact.properties}

        print(f"[HubSpot] No contact found for {email}")
        return {}

    except Exception as e:
        print(f"[HubSpot] Search failed: {e}")
        return {}


def update_contact(contact_id: str, properties: dict) -> bool:
    """Update a HubSpot contact's properties."""
    try:
        from hubspot.crm.contacts import SimplePublicObjectInput

        hs = get_client()
        hs.crm.contacts.basic_api.update(
            contact_id=contact_id,
            simple_public_object_input=SimplePublicObjectInput(properties=properties)
        )
        print(f"[HubSpot] Updated contact {contact_id}")
        return True

    except Exception as e:
        print(f"[HubSpot] Update failed: {e}")
        return False


def write_enrichment_results(email: str, enrichment: dict) -> bool:
    """Write enrichment pipeline results to HubSpot contact."""
    contact = find_contact_by_email(email)
    if not contact:
        return False

    icp    = enrichment.get("icp", {})
    hiring = enrichment.get("hiring_signal", {})
    gap    = enrichment.get("competitor_gap", {})
    mat    = enrichment.get("ai_maturity", {})

    properties = {
        "icp_segment":           str(icp.get("segment", "")),
        "segment_confidence":    icp.get("confidence", ""),
        "qualification_status":  "OUTREACH_SENT",
        "ai_maturity_score":     str(mat.get("ai_maturity", 0)),
        "hiring_signal_summary": hiring.get("brief", ""),
        "competitor_gap_note":   gap.get("primary_gap", ""),
        "last_enriched_at":      datetime.now(timezone.utc).isoformat(),
    }

    return update_contact(contact["id"], properties)


def mark_discovery_booked(email: str) -> bool:
    """Update contact status to DISCOVERY_BOOKED after Cal.com booking."""
    contact = find_contact_by_email(email)
    if not contact:
        return False

    return update_contact(contact["id"], {
        "qualification_status": "DISCOVERY_BOOKED",
        "hs_lead_status":       "IN_PROGRESS",
    })


if __name__ == "__main__":
    import json
    contact = find_contact_by_email("cto@turingsignal.com")
    print(json.dumps({"contact_id": contact.get("id")}, indent=2))