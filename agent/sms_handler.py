"""
agent/sms_handler.py
Africa's Talking SMS handler for warm-lead scheduling.
Handles outbound SMS and inbound STOP opt-outs.
"""
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

def send_sms(phone: str, company: str, email: str = None) -> dict:
    """Send SMS — only to warm leads (REPLIED state or above)."""
    
    # Warm-lead gate — check HubSpot thread state before sending
    if email:
        state = _get_thread_state(email)
        if state == "COLD":
            print(f"[SMS] BLOCKED — {email} is COLD state. SMS only for warm leads.")
            return {
                "status":  "blocked",
                "reason":  "warm_lead_gate — prospect has not replied to email yet",
                "email":   email,
                "phone":   phone,
            }
    
    # rest of your existing send logic below...

def send_sms(phone: str, body: str = "", company: str = "", email: str = "") -> dict:
    """
    Send an SMS via Africa's Talking sandbox.
    Warm-lead gate: checks HubSpot thread state before sending.
    Only sends if prospect is in REPLIED, QUALIFIED, or BOOKED state.
    """
    # Warm-lead gate
    if email:
        state = _get_thread_state(email)
        if state == "COLD":
            print(f"[SMS] BLOCKED — {email} is COLD state. SMS only for warm leads.")
            return {
                "status": "blocked",
                "reason": "warm_lead_gate — prospect has not replied to email yet",
                "email":  email,
                "phone":  phone,
            }
        print(f"[SMS] Gate passed — {email} is {state} state")

    # Build message body if not provided
    if not body:
        body = (
            f"Hi, following up on our email about {company}. "
            f"Happy to jump on a quick call — book here: "
            f"https://cal.com/bethelhem-abay/discovery-call"
        )

    try:
        import africastalking

        africastalking.initialize(
            username=os.getenv("AT_USERNAME", "sandbox"),
            api_key=os.getenv("AT_API_KEY")
        )

        sms       = africastalking.SMS
        response  = sms.send(
            message=body,
            recipients=[phone],
            sender_id=os.getenv("AT_SHORTCODE", "21415")
        )

        recipients = response.get("SMSMessageData", {}).get("Recipients", [])
        if recipients:
            r = recipients[0]
            print(f"[AT] SMS sent to {phone} | status={r.get('status')} | id={r.get('messageId')}")
            return {
                "status":     r.get("status"),
                "message_id": r.get("messageId"),
                "phone":      phone,
                "cost":       r.get("cost"),
                "company":    company,
                "sent_at":    datetime.now(timezone.utc).isoformat(),
            }

        return {"status": "unknown", "phone": phone}

    except Exception as e:
        print(f"[AT] SMS failed: {e}")
        return {"status": "error", "error": str(e), "phone": phone}


def _get_thread_state(email: str) -> str:
    """Get prospect thread state from HubSpot. Defaults to COLD if not found."""
    try:
        import hubspot
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
            state = sr.results[0].properties.get("thread_state", "COLD") or "COLD"
            return state
    except Exception as e:
        print(f"[SMS] HubSpot state check failed: {e}")
    return "COLD"

def send_outreach_sms(phone: str, company: str) -> dict:
    """Send a signal-grounded outreach SMS."""
    message = (
        f"Hi, I noticed {company} is scaling its engineering team. "
        f"Tenacious Consulting helps companies like yours build dedicated "
        f"offshore engineering teams in 2 weeks. Worth a quick call? "
        f"Reply STOP to opt out."
    )
    return send_sms(phone, message)


def send_booking_confirmation_sms(phone: str, meeting_time: str) -> dict:
    """Send booking confirmation after Cal.com booking."""
    message = (
        f"Your discovery call with Tenacious Consulting is confirmed for "
        f"{meeting_time}. We look forward to speaking with you!"
    )
    return send_sms(phone, message)


def handle_opt_out(phone: str) -> dict:
    """Process a STOP opt-out request."""
    print(f"[AT] OPT_OUT received from {phone}")
    return {
        "status":       "opted_out",
        "phone":        phone,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    import json
    result = send_outreach_sms("+254700000000", "Turing Signal")
    print(json.dumps(result, indent=2))

def _get_thread_state(email: str) -> str:
    """Get prospect thread state from HubSpot."""
    try:
        import hubspot
        from hubspot.crm.contacts.models import (
            PublicObjectSearchRequest, Filter, FilterGroup
        )
        import os
        hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))
        f  = Filter(property_name="email", operator="EQ", value=email)
        fg = FilterGroup(filters=[f])
        sr = hs.crm.contacts.search_api.do_search(
            public_object_search_request=PublicObjectSearchRequest(filter_groups=[fg])
        )
        if sr.results:
            return sr.results[0].properties.get("thread_state", "COLD") or "COLD"
    except Exception as e:
        print(f"[SMS] HubSpot state check failed: {e}")
    return "COLD"  # default to COLD if check fails — safe fallback