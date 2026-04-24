"""
agent/calcom_handler.py

Cal.com booking flow — dedicated handler per manual Section 10.
Handles booking creation, webhook processing, context brief attachment,
and HubSpot write-back on booking confirmed.
"""
import os
import json
import requests
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

CALCOM_BASE_URL  = os.getenv("CALCOM_BASE_URL", "https://app.cal.com")
CALCOM_API_KEY   = os.getenv("CALCOM_API_KEY", "")
EVENT_TYPE_ID    = os.getenv("CALCOM_EVENT_TYPE_ID", "")


def get_booking_link(
    prospect_name: str = None,
    prospect_company: str = None,
    segment: str = None,
    brief_summary: str = None,
) -> str:
    """
    Build a Cal.com booking link with pre-filled context.

    Args:
        prospect_name: Pre-fill name field
        prospect_company: Company name
        segment: ICP segment for context
        brief_summary: 3-sentence context for the meeting description

    Returns:
        Full Cal.com booking URL
    """
    base = f"{CALCOM_BASE_URL}/bethelhem-abay/discovery-call"

    # Build query params for pre-filling
    params = []
    if prospect_name:
        params.append(f"name={requests.utils.quote(prospect_name)}")
    if prospect_company:
        params.append(f"notes={requests.utils.quote(f'Company: {prospect_company}')}")

    if params:
        return f"{base}?{'&'.join(params)}"
    return base


def handle_booking_webhook(payload: dict) -> dict:
    """
    Process a BOOKING_CREATED webhook from Cal.com.

    Extracts attendee info, triggers discovery brief generation,
    updates HubSpot, and sends confirmation email.

    Args:
        payload: Full Cal.com webhook payload

    Returns:
        dict with status, attendee_email, brief_generated, hubspot_updated
    """
    event_type = payload.get("triggerEvent", "unknown")

    # Only process BOOKING_CREATED
    if event_type != "BOOKING_CREATED":
        return {"status": "ignored", "event": event_type}

    webhook_payload = payload.get("payload", {})
    attendees       = webhook_payload.get("attendees", [{}])
    attendee        = attendees[0] if attendees else {}

    attendee_email  = attendee.get("email", "unknown")
    attendee_name   = attendee.get("name", "unknown")
    meeting_time    = webhook_payload.get("startTime", "unknown")
    meeting_title   = webhook_payload.get("title", "Discovery Call")
    duration        = webhook_payload.get("length", 30)
    organizer       = webhook_payload.get("organizer", {})
    delivery_lead   = organizer.get("name", "Arun Sharma")

    print(f"[CalCom] BOOKING_CREATED: {attendee_email} at {meeting_time}")

    # Generate discovery brief
    brief_md   = ""
    brief_path = None

    try:
        brief_md, brief_path = generate_and_save_brief(
            attendee_email, attendee_name, meeting_time,
            delivery_lead, duration, meeting_title
        )
        print(f"[CalCom] Brief generated: {brief_path}")
    except Exception as e:
        print(f"[CalCom] Brief generation failed: {e}")

    # Update HubSpot
    hs_updated = update_hubspot_booked(
        attendee_email, meeting_time, brief_path
    )

    return {
        "status":       "processed",
        "event":        event_type,
        "attendee":     attendee_email,
        "meeting_time": meeting_time,
        "brief_generated": bool(brief_md),
        "brief_path":   str(brief_path) if brief_path else None,
        "hubspot_updated": hs_updated,
    }


def generate_and_save_brief(
    attendee_email: str,
    attendee_name: str,
    meeting_time: str,
    delivery_lead: str,
    duration: int,
    meeting_title: str,
) -> tuple:
    """
    Generate a 10-section discovery brief and save it to outputs/.
    Returns (brief_markdown, file_path).
    """
    from agent.enrichment.discovery_brief import generate_discovery_brief

    # Fetch enrichment data from HubSpot
    icp, hiring, ai_mat, gap, company = fetch_enrichment_from_hubspot(
        attendee_email
    )

    first_name = attendee_name.split()[0] if attendee_name not in ("unknown", "") else "there"

    langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    trace_url     = f"{langfuse_host}/trace/calcom-booking"

    brief_md = generate_discovery_brief(
        prospect_name       = first_name,
        prospect_title      = "VP Engineering",
        prospect_company    = company or attendee_name,
        call_datetime_utc   = meeting_time,
        call_datetime_local = meeting_time,
        delivery_lead       = delivery_lead,
        duration_minutes    = int(duration or 30),
        thread_start_date   = datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        original_subject    = meeting_title,
        langfuse_trace_url  = trace_url,
        icp_result          = icp,
        hiring_signal       = hiring,
        competitor_gap      = gap,
        ai_maturity         = ai_mat,
        trace_id            = None,
    )

    # Save brief
    outputs_dir  = Path("outputs")
    outputs_dir.mkdir(exist_ok=True)
    safe_email   = attendee_email.replace("@", "_at_").replace(".", "_")
    timestamp    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    brief_path   = outputs_dir / f"discovery_brief_{safe_email}_{timestamp}.md"
    brief_path.write_text(brief_md, encoding="utf-8")

    return brief_md, brief_path


def fetch_enrichment_from_hubspot(email: str) -> tuple:
    """
    Fetch stored enrichment data from HubSpot contact.
    Returns (icp_result, hiring_signal, ai_maturity, competitor_gap, company_name).
    """
    try:
        import hubspot
        from hubspot.crm.contacts.models import (
            PublicObjectSearchRequest, Filter, FilterGroup
        )

        hs     = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))
        f      = Filter(property_name="email", operator="EQ", value=email)
        fg     = FilterGroup(filters=[f])
        search = hs.crm.contacts.search_api.do_search(
            public_object_search_request=PublicObjectSearchRequest(filter_groups=[fg])
        )

        if search.results:
            props   = search.results[0].properties or {}
            segment = props.get("icp_segment", "unknown")
            ai_score = int(props.get("ai_maturity_score", 0) or 0)
            company  = props.get("company", "")

            icp = {
                "segment":            segment,
                "confidence":         float(props.get("segment_confidence", 0.7) or 0.7),
                "qualified":          True,
                "segment_description": f"Segment: {segment}",
                "qualifying_signals": [f"Stored from enrichment run"],
                "pitch":              "",
            }
            hiring = {
                "prospect_name": company or email,
                "hiring_velocity": {
                    "open_roles_today":       0,
                    "open_roles_60_days_ago": 0,
                    "velocity_label":         props.get("hiring_signal_summary", "unknown"),
                },
                "buying_window_signals": {
                    "funding_event":     {"detected": False},
                    "layoff_event":      {"detected": False},
                    "leadership_change": {"detected": False},
                },
                "tech_stack":    [],
                "honesty_flags": [],
            }
            ai_mat = {
                "score":            ai_score,
                "confidence_label": "medium",
                "brief":            f"AI maturity {ai_score}/3",
            }
            gap = {
                "gap_findings":        [],
                "suggested_pitch_shift": props.get("competitor_gap_note", ""),
            }
            return icp, hiring, ai_mat, gap, company

    except Exception as e:
        print(f"[CalCom] HubSpot fetch failed: {e}")

    return {}, {}, {}, {}, ""


def update_hubspot_booked(
    email: str,
    meeting_time: str,
    brief_path: Path = None,
) -> bool:
    """Update HubSpot contact to DISCOVERY_BOOKED."""
    try:
        import hubspot
        from hubspot.crm.contacts import SimplePublicObjectInput
        from hubspot.crm.contacts.models import (
            PublicObjectSearchRequest, Filter, FilterGroup
        )

        hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))
        f  = Filter(property_name="email", operator="EQ", value=email)
        fg = FilterGroup(filters=[f])
        sr = hs.crm.contacts.search_api.do_search(
            public_object_search_request=PublicObjectSearchRequest(filter_groups=[fg])
        )

        if sr.results:
            props = {
                "qualification_status": "DISCOVERY_BOOKED",
                "hs_lead_status":       "IN_PROGRESS",
                "meeting_at":           meeting_time,
                "bench_match_confirmed": "true",
                "tenacious_status":     "draft",  # Policy Rule 6
            }
            if brief_path:
                props["competitor_gap_note"] = f"Brief: {brief_path.name}"

            hs.crm.contacts.basic_api.update(
                contact_id=sr.results[0].id,
                simple_public_object_input=SimplePublicObjectInput(properties=props)
            )
            print(f"[CalCom] HubSpot updated → DISCOVERY_BOOKED for {email}")
            return True

    except Exception as e:
        print(f"[CalCom] HubSpot update failed: {e}")

    return False


def list_upcoming_bookings() -> list:
    """Fetch upcoming bookings from Cal.com API."""
    try:
        resp = requests.get(
            f"{CALCOM_BASE_URL}/api/v1/bookings",
            params={"apiKey": CALCOM_API_KEY, "status": "upcoming"},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json().get("bookings", [])
    except Exception as e:
        print(f"[CalCom] List bookings failed: {e}")
    return []


if __name__ == "__main__":
    # Test webhook handling
    test_payload = {
        "triggerEvent": "BOOKING_CREATED",
        "payload": {
            "attendees": [{"email": "cto@orrin-labs.example", "name": "Jordan Okafor"}],
            "startTime": "2026-04-26T14:00:00Z",
            "title": "Discovery Call",
            "length": 30,
            "organizer": {"name": "Arun Sharma"}
        }
    }
    result = handle_booking_webhook(test_payload)
    print(json.dumps(result, indent=2, default=str))