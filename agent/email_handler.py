"""
agent/email_handler.py

Resend email integration — dedicated handler per manual Section 10.
Handles outbound sends, reply webhooks, suppression list, draft marking.

Policy compliance:
- X-Tenacious-Status: draft on every outbound email (Rule 6)
- Kill switch gate before every send (Rule 5)
- Suppression list for opted-out domains
"""
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SUPPRESSION_FILE = Path("data/suppression_list.json")
_suppressed: set = set()


def _load_suppression():
    global _suppressed
    if SUPPRESSION_FILE.exists():
        try:
            data = json.loads(SUPPRESSION_FILE.read_text())
            _suppressed = set(data.get("domains", []) + data.get("emails", []))
        except Exception:
            _suppressed = set()


def _save_suppression():
    SUPPRESSION_FILE.parent.mkdir(exist_ok=True)
    SUPPRESSION_FILE.write_text(json.dumps(
        {"emails": [], "domains": list(_suppressed), "updated_at": datetime.now(timezone.utc).isoformat()},
        indent=2
    ))


_load_suppression()


def is_suppressed(email: str) -> bool:
    """Check if an email or its domain is suppressed."""
    if email in _suppressed:
        return True
    domain = email.split("@")[-1] if "@" in email else ""
    return domain in _suppressed


def suppress(email: str):
    """Add email/domain to suppression list."""
    _suppressed.add(email)
    domain = email.split("@")[-1] if "@" in email else ""
    if domain:
        _suppressed.add(domain)
    _save_suppression()
    print(f"[EmailHandler] Suppressed: {email} (domain: {domain})")


def send_email(
    to: str,
    subject: str,
    body_text: str,
    body_html: str = None,
    outbound_variant: str = "signal_grounded",
    trace_id: str = None,
) -> dict:
    """
    Send an email via Resend.
    Checks kill switch and suppression list before sending.

    Args:
        to: Recipient email
        subject: Subject line (max 60 chars recommended)
        body_text: Plain text body
        body_html: HTML body (generated from body_text if not provided)
        outbound_variant: "signal_grounded" or "generic" — tagged in trace
        trace_id: Langfuse trace ID for this interaction

    Returns:
        dict with status, message_id, to (actual), kill_switch_active
    """
    # Kill switch check
    outbound_enabled = os.getenv("TENACIOUS_OUTBOUND_ENABLED", "false").lower() == "true"
    sink_email = os.getenv("STAFF_SINK_EMAIL", "sink@trp1.example")

    actual_to = to if outbound_enabled else sink_email
    if not outbound_enabled:
        print(f"[EmailHandler] Kill switch DISABLED — routing {to} → {sink_email}")

    # Suppression check
    if is_suppressed(to):
        print(f"[EmailHandler] SUPPRESSED — skipping {to}")
        return {
            "status":    "suppressed",
            "to":        to,
            "reason":    "email or domain on suppression list",
        }

    # Build HTML if not provided
    if not body_html:
        body_html = (
            '<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;color:#111;">'
            + body_text.replace("\n", "<br>")
            + '<p style="font-size:11px;color:#999;margin-top:24px;">'
            + 'Reply STOP to unsubscribe.</p></div>'
        )

    try:
        import resend
        resend.api_key = os.getenv("RESEND_API_KEY")

        response = resend.Emails.send({
            "from":    os.getenv("RESEND_FROM_EMAIL", "onboarding@resend.dev"),
            "to":      [actual_to],
            "subject": subject,
            "html":    body_html,
            "headers": {
                "X-Tenacious-Status": "draft",
                "X-Tenacious-Env":    os.getenv("SANDBOX", "true"),
                "X-Outbound-Variant": outbound_variant,
                "X-Trace-ID":         trace_id or "",
            },
        })

        msg_id = getattr(response, "id", None) or (
            response.get("id") if isinstance(response, dict) else "unknown"
        )

        print(f"[EmailHandler] Sent to={actual_to} variant={outbound_variant} id={msg_id}")
        return {
            "status":             "sent",
            "message_id":         msg_id,
            "to":                 actual_to,
            "intended_to":        to,
            "subject":            subject,
            "outbound_variant":   outbound_variant,
            "kill_switch_active": not outbound_enabled,
            "sent_at":            datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        print(f"[EmailHandler] Send failed: {e}")
        return {
            "status":  "error",
            "error":   str(e),
            "to":      actual_to,
        }


def handle_reply_webhook(payload: dict) -> dict:
    """
    Process an inbound email reply webhook from Resend.
    Returns classification and next action.

    Args:
        payload: Webhook payload from Resend

    Returns:
        dict with sender, subject, body, classification, next_action
    """
    sender  = payload.get("from", "unknown")
    subject = payload.get("subject", "")
    body    = payload.get("text", payload.get("html", ""))

    # Classify the reply
    classification = _classify_reply(body)
    next_action    = _get_next_action(classification, sender)

    print(f"[EmailHandler] Reply from={sender} class={classification} action={next_action}")

    return {
        "sender":         sender,
        "subject":        subject,
        "body":           body,
        "classification": classification,
        "next_action":    next_action,
        "received_at":    datetime.now(timezone.utc).isoformat(),
    }


def handle_opt_out(email: str):
    """Process an opt-out (STOP) request."""
    suppress(email)
    print(f"[EmailHandler] OPT_OUT processed for {email}")
    return {"status": "opted_out", "email": email}


def _classify_reply(body: str) -> str:
    """Classify a reply into one of 5 classes."""
    body_lower = body.lower()

    # Hard no
    if any(w in body_lower for w in [
        "not interested", "please remove", "stop emailing", "unsubscribe",
        "opt out", "opt-out", "remove me", "don't contact", "do not contact"
    ]):
        return "hard_no"

    # Soft defer
    if any(w in body_lower for w in [
        "not right now", "maybe later", "too busy", "not a priority",
        "check back", "reach out in", "try again in", "q3", "q4"
    ]):
        return "soft_defer"

    # Objection
    if any(w in body_lower for w in [
        "price", "cost", "expensive", "cheaper", "india", "offshore",
        "already have", "vendor", "incumbent", "poc", "pilot", "small"
    ]):
        return "objection"

    # Curious
    if any(w in body_lower for w in [
        "tell me more", "what do you do", "how does", "what exactly",
        "interested", "curious", "more info", "learn more"
    ]):
        return "curious"

    # Engaged (default for substantive replies)
    if len(body.split()) > 10:
        return "engaged"

    return "ambiguous"


def _get_next_action(classification: str, sender: str) -> str:
    """Map classification to next action."""
    actions = {
        "hard_no":  "opt_out_and_suppress",
        "soft_defer": "log_reengagement_date",
        "objection":  "route_to_objection_handler",
        "curious":    "send_curious_reply_with_cal_link",
        "engaged":    "send_engaged_reply_book_discovery_call",
        "ambiguous":  "route_to_human",
    }
    return actions.get(classification, "route_to_human")