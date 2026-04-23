"""
agent/sms_handler.py
Africa's Talking SMS handler for warm-lead scheduling.
Handles outbound SMS and inbound STOP opt-outs.
"""
import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()


def send_sms(phone: str, message: str) -> dict:
    """
    Send an SMS via Africa's Talking sandbox.
    Returns response dict with messageId and status.
    """
    try:
        import africastalking

        africastalking.initialize(
            username=os.getenv("AT_USERNAME", "sandbox"),
            api_key=os.getenv("AT_API_KEY")
        )

        sms = africastalking.SMS
        response = sms.send(
            message=message,
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
                "sent_at":    datetime.now(timezone.utc).isoformat(),
            }

        return {"status": "unknown", "phone": phone}

    except Exception as e:
        print(f"[AT] SMS failed: {e}")
        return {"status": "error", "error": str(e), "phone": phone}


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