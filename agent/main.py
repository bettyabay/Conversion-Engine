"""
agent/main.py
FastAPI server — central hub for all webhooks and agent logic.

Policy compliance:
- Kill switch: TENACIOUS_OUTBOUND_ENABLED gate on every outbound
- Draft marking: X-Tenacious-Status: draft on all emails
- Draft marking: tenacious_status=draft on all HubSpot records
- See policy/data_handling_policy.md Rules 5 and 6
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import uuid
import requests as _requests
import base64 as _base64
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Conversion Engine", version="1.0.0")


# ── Kill switch — TENACIOUS_OUTBOUND_ENABLED gate ────────────
# Policy Rule 5: every outbound must pass through this gate.
# Default is DISABLED. Set TENACIOUS_OUTBOUND_ENABLED=true in .env
# to enable actual sending. Without this, all outbound routes to sink.

OUTBOUND_ENABLED = os.getenv("TENACIOUS_OUTBOUND_ENABLED", "false").lower() == "true"
STAFF_SINK_EMAIL = os.getenv("STAFF_SINK_EMAIL", "sink@trp1.example")
STAFF_SINK_PHONE = os.getenv("STAFF_SINK_PHONE", "+10000000000")


def gate_outbound(destination: str, destination_type: str = "email") -> str:
    """
    Kill switch gate. Returns the actual destination to use.
    If TENACIOUS_OUTBOUND_ENABLED is not true, routes to staff sink.
    Policy Rule 5: bypassing this gate in code is a policy violation.
    """
    if OUTBOUND_ENABLED:
        return destination
    else:
        sink = STAFF_SINK_EMAIL if destination_type == "email" else STAFF_SINK_PHONE
        print(f"[KillSwitch] DISABLED — routing {destination} → sink {sink}")
        return sink


def make_draft_headers() -> dict:
    """
    Email headers required by Policy Rule 6.
    All Tenacious-branded output must be marked draft.
    """
    return {
        "X-Tenacious-Status": "draft",
        "X-Tenacious-Env":    os.getenv("SANDBOX", "true"),
    }


def draft_hubspot_props() -> dict:
    """
    HubSpot properties required by Policy Rule 6.
    Every HubSpot record must include tenacious_status=draft.
    """
    return {"tenacious_status": "draft"}


# ── Langfuse v4 — raw ingestion API ──────────────────────────
def create_trace(name: str, metadata: dict = None, user_id: str = None):
    trace_id = str(uuid.uuid4())

    class Trace:
        def __init__(self, tid):
            self.id = tid
        def update(self, **kwargs): pass
        def span(self, **kwargs): return self
        def end(self, **kwargs): pass

    try:
        public_key  = os.getenv("LANGFUSE_PUBLIC_KEY", "")
        secret_key  = os.getenv("LANGFUSE_SECRET_KEY", "")
        host        = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        credentials = _base64.b64encode(
            f"{public_key}:{secret_key}".encode()
        ).decode()

        payload = {
            "batch": [{
                "id":        str(uuid.uuid4()),
                "type":      "trace-create",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "body": {
                    "id":       trace_id,
                    "name":     name,
                    "userId":   user_id or "system",
                    "metadata": metadata or {},
                }
            }]
        }

        resp = _requests.post(
            f"{host}/api/public/ingestion",
            json=payload,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type":  "application/json"
            },
            timeout=5
        )

        if resp.status_code == 207:
            print(f"[Langfuse] trace={name} id={trace_id}")
        else:
            print(f"[Langfuse] status={resp.status_code} body={resp.text[:100]}")

    except Exception as e:
        print(f"[Langfuse fallback] {e} | id={trace_id}")

    return Trace(trace_id)


# ── Health check ──────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "status":           "alive",
        "timestamp":        datetime.now(timezone.utc).isoformat(),
        "system":           "Conversion Engine v1.0",
        "outbound_enabled": OUTBOUND_ENABLED,
    }


@app.get("/health")
async def health():
    return {"status": "ok", "outbound_enabled": OUTBOUND_ENABLED}


# ── Email reply webhook ───────────────────────────────────────
@app.post("/webhook/email")
async def email_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    sender  = data.get("from", "unknown")
    subject = data.get("subject", "")

    trace = create_trace(
        name="email_reply_received",
        metadata={
            "from":        sender,
            "subject":     subject,
            "environment": os.getenv("SANDBOX", "true"),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        }
    )

    print(f"[Email webhook] from={sender} subject={subject} trace={trace.id}")

    return JSONResponse({
        "status":   "received",
        "trace_id": trace.id,
        "message":  "Email webhook processed"
    })


# ── SMS webhook ───────────────────────────────────────────────
@app.post("/webhook/sms")
async def sms_webhook(request: Request):
    try:
        form    = await request.form()
        sender  = form.get("from", "unknown")
        message = form.get("text", "").strip()
    except Exception:
        sender  = "unknown"
        message = ""

    if message.upper() in ["STOP", "UNSUBSCRIBE", "QUIT", "CANCEL", "END"]:
        print(f"[SMS] OPT_OUT from {sender}")
        trace = create_trace(
            name="sms_opt_out",
            metadata={"sender": sender, "message": message}
        )
        return JSONResponse({
            "status":   "opt_out_processed",
            "trace_id": trace.id
        })

    trace = create_trace(
        name="sms_received",
        metadata={
            "sender":      sender,
            "message":     message,
            "environment": os.getenv("SANDBOX", "true"),
        }
    )

    print(f"[SMS webhook] from={sender} msg={message} trace={trace.id}")
    return JSONResponse({"status": "received", "trace_id": trace.id})


# ── Cal.com booking webhook ───────────────────────────────────
@app.post("/webhook/calcom")
async def calcom_webhook(request: Request):
    try:
        data = await request.json()
    except Exception:
        data = {}

    event_type     = data.get("triggerEvent", "unknown")
    payload        = data.get("payload", {})
    attendees      = payload.get("attendees", [{}])
    attendee_email = attendees[0].get("email", "unknown") if attendees else "unknown"
    attendee_name  = attendees[0].get("name", "unknown") if attendees else "unknown"
    meeting_time   = payload.get("startTime", "unknown")
    meeting_title  = payload.get("title", "Discovery Call")

    print(f"[Cal.com] event={event_type}")
    print(f"[Cal.com] attendee={attendee_email} time={meeting_time}")

    trace = create_trace(
        name="calcom_booking",
        user_id=attendee_email,
        metadata={
            "event_type":     event_type,
            "attendee_email": attendee_email,
            "attendee_name":  attendee_name,
            "meeting_time":   meeting_time,
            "meeting_title":  meeting_title,
            "environment":    os.getenv("SANDBOX", "true"),
        }
    )

    print(f"[Cal.com] Booking trace ID: {trace.id}")

    # Update HubSpot contact to DISCOVERY_BOOKED
    try:
        import hubspot
        from hubspot.crm.contacts import SimplePublicObjectInput
        from hubspot.crm.contacts.models import PublicObjectSearchRequest, Filter, FilterGroup

        hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))

        f  = Filter(property_name="email", operator="EQ", value=attendee_email)
        fg = FilterGroup(filters=[f])
        search = hs.crm.contacts.search_api.do_search(
            public_object_search_request=PublicObjectSearchRequest(filter_groups=[fg])
        )

        if search.results:
            contact_id = search.results[0].id
            props = {
                "qualification_status": "DISCOVERY_BOOKED",
                "hs_lead_status":       "IN_PROGRESS",
            }
            props.update(draft_hubspot_props())  # Policy Rule 6
            hs.crm.contacts.basic_api.update(
                contact_id=contact_id,
                simple_public_object_input=SimplePublicObjectInput(properties=props)
            )
            print(f"[HubSpot] contact {contact_id} → DISCOVERY_BOOKED")
        else:
            print(f"[HubSpot] no contact found for {attendee_email}")

    except Exception as e:
        print(f"[HubSpot] {e}")

    return JSONResponse({
        "status":   "booking_received",
        "trace_id": trace.id,
        "event":    event_type,
        "attendee": attendee_email
    })


# ── Manual trigger — send outreach email ─────────────────────
@app.post("/trigger/outreach")
async def trigger_outreach(request: Request):
    """
    Send a signal-grounded outreach email.
    POST body: {"lead_id": "...", "company": "...", "email": "..."}
    Kill switch: routes to sink if TENACIOUS_OUTBOUND_ENABLED != true
    """
    try:
        data = await request.json()
    except Exception:
        data = {}

    lead_id = data.get("lead_id", "turing_signal_001")
    company = data.get("company", "Turing Signal")
    email   = data.get("email", os.getenv("RESEND_TO_TEST"))

    # ── Kill switch gate ──────────────────────────────────────
    email_to = gate_outbound(email, "email")

    trace = create_trace(
        name="outreach_triggered",
        metadata={
            "lead_id":          lead_id,
            "company":          company,
            "intended_email":   email,
            "actual_email":     email_to,
            "kill_switch":      not OUTBOUND_ENABLED,
            "environment":      os.getenv("SANDBOX", "true"),
        }
    )

    try:
        import resend
        resend.api_key = os.getenv("RESEND_API_KEY")

        cal_url = "https://cal.com/bethelhem-abay/discovery-call"

        html = f"""
        <p>Hi,</p>
        <p>I noticed <strong>{company}</strong> has been scaling its engineering team.
        Tenacious Consulting helps companies like yours build dedicated offshore
        engineering teams without the recruiting overhead — engineers available
        in 7-14 days, embedded in your stack.</p>
        <p>Would you be open to a 30-minute discovery call?</p>
        <p><a href="{cal_url}">Book a time here</a></p>
        <p>Best,<br>Tenacious Team<br>gettenacious.com</p>
        <p style="font-size:11px;color:#999;">Reply STOP to unsubscribe.</p>
        """

        response = resend.Emails.send({
            "from":    os.getenv("RESEND_FROM_EMAIL"),
            "to":      [email_to],
            "subject": f"{company} engineering capacity — worth a conversation?",
            "html":    html,
            "headers": make_draft_headers(),  # Policy Rule 6
        })

        msg_id = getattr(response, "id", None) or (
            response.get("id") if isinstance(response, dict) else "unknown"
        )

        print(f"[Resend] sent to {email_to} msg_id={msg_id} trace={trace.id}")
        print(f"[KillSwitch] outbound_enabled={OUTBOUND_ENABLED}")

        return JSONResponse({
            "status":            "email_sent",
            "trace_id":          trace.id,
            "resend_message_id": msg_id,
            "to":                email_to,
            "kill_switch_active": not OUTBOUND_ENABLED,
        })

    except Exception as e:
        print(f"[Resend] error: {e}")
        return JSONResponse(
            {"status": "error", "message": str(e), "trace_id": trace.id},
            status_code=500
        )


# ── SMS trigger ───────────────────────────────────────────────
@app.post("/trigger/sms")
async def trigger_sms(request: Request):
    """
    Send an SMS outreach message.
    POST body: {"phone": "...", "company": "..."}
    Kill switch: routes to sink if TENACIOUS_OUTBOUND_ENABLED != true
    SMS is secondary channel — warm leads only (policy/data_handling_policy.md)
    """
    try:
        data = await request.json()
    except Exception:
        data = {}

    phone   = data.get("phone", "+254700000000")
    company = data.get("company", "Turing Signal")

    # ── Kill switch gate ──────────────────────────────────────
    phone_to = gate_outbound(phone, "sms")

    trace = create_trace(
        name="sms_outreach_triggered",
        metadata={
            "intended_phone": phone,
            "actual_phone":   phone_to,
            "company":        company,
            "kill_switch":    not OUTBOUND_ENABLED,
        }
    )

    try:
        import africastalking
        africastalking.initialize(
            username=os.getenv("AT_USERNAME", "sandbox"),
            api_key=os.getenv("AT_API_KEY")
        )
        sms = africastalking.SMS
        message = (
            f"Tenacious: {company} scaling engineering? "
            f"We deploy teams in 7-14 days. "
            f"Worth a call? Reply STOP to opt out."
        )
        response = sms.send(
            message=message,
            recipients=[phone_to],
            sender_id=os.getenv("AT_SHORTCODE", "21415")
        )
        print(f"[AT] SMS sent to {phone_to}: {response}")
        return JSONResponse({
            "status":           "sms_sent",
            "trace_id":         trace.id,
            "to":               phone_to,
            "kill_switch_active": not OUTBOUND_ENABLED,
        })
    except Exception as e:
        print(f"[AT] SMS failed: {e}")
        return JSONResponse(
            {"status": "error", "message": str(e), "trace_id": trace.id},
            status_code=500
        )


# ── Full enrichment pipeline ──────────────────────────────────
@app.post("/enrich")
async def enrich_prospect(request: Request):
    """
    Runs the full enrichment pipeline on a prospect.
    POST body: {"company": "Acme Corp", "email": "cto@acme.com"}
    """
    try:
        data = await request.json()
    except Exception:
        data = {}

    company = data.get("company", "Turing Signal")
    email   = data.get("email", "cto@turingsignal.com")

    trace = create_trace(
        name="prospect_enriched",
        user_id=email,
        metadata={"company": company, "email": email}
    )

    from agent.enrichment.crunchbase import find_company
    from agent.enrichment.jobs import get_hiring_signal
    from agent.enrichment.ai_maturity import score_ai_maturity
    from agent.enrichment.competitor_gap import build_competitor_gap_brief
    from agent.enrichment.layoffs import check_layoff_signal
    from agent.icp_classifier import classify

    cb_brief  = find_company(company)
    hiring    = get_hiring_signal(company, cb_brief.get("website"))
    layoff    = check_layoff_signal(company)
    maturity  = score_ai_maturity(
        company_name=company,
        description=cb_brief.get("description", ""),
        job_titles=hiring.get("_all_open_titles", []),
    )
    gap = build_competitor_gap_brief(
        company_name=company,
        prospect_ai_maturity=maturity.get("score", 0),
        funding_type=cb_brief.get("last_funding_type", ""),
        hiring_signal=hiring.get("hiring_velocity", {}).get("velocity_label", ""),
        has_layoff=layoff.get("has_layoff", False),
    )
    icp = classify(
        company_name=company,
        funding_type=cb_brief.get("last_funding_type", ""),
        funding_days_ago=999,
        headcount=0,
        open_eng_roles=hiring.get("hiring_velocity", {}).get("open_roles_today", 0),
        has_layoff=layoff.get("has_layoff", False),
        ai_maturity_score=maturity.get("score", 0),
    )

    # HubSpot write-back
    try:
        import hubspot
        from hubspot.crm.contacts import SimplePublicObjectInput
        from hubspot.crm.contacts.models import PublicObjectSearchRequest, Filter, FilterGroup

        hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))
        f  = Filter(property_name="email", operator="EQ", value=email)
        fg = FilterGroup(filters=[f])
        search = hs.crm.contacts.search_api.do_search(
            public_object_search_request=PublicObjectSearchRequest(filter_groups=[fg])
        )

        if search.results:
            contact_id = search.results[0].id
            props = {
                "icp_segment":           str(icp.get("segment", "")),
                "segment_confidence":    str(icp.get("confidence", "")),
                "qualification_status":  "OUTREACH_SENT",
                "ai_maturity_score":     str(maturity.get("score", 0)),
                "hiring_signal_summary": hiring.get("hiring_velocity", {}).get("velocity_label", ""),
                "competitor_gap_note":   gap.get("gap_findings", [{}])[0].get("practice", "")[:255] if gap.get("gap_findings") else "",
                "last_enriched_at":      datetime.now(timezone.utc).isoformat(),
                "trace_id":              trace.id,
            }
            props.update(draft_hubspot_props())  # Policy Rule 6
            hs.crm.contacts.basic_api.update(
                contact_id=contact_id,
                simple_public_object_input=SimplePublicObjectInput(properties=props)
            )
            print(f"[HubSpot] Updated {email} with enrichment data")
        else:
            print(f"[HubSpot] Contact not found for {email}")

    except Exception as e:
        print(f"[HubSpot] Write-back failed: {e}")

    result = {
        "company":       company,
        "email":         email,
        "trace_id":      trace.id,
        "crunchbase":    cb_brief,
        "hiring_signal": hiring,
        "ai_maturity":   maturity,
        "layoff_signal": layoff,
        "competitor_gap": gap,
        "icp":           icp,
        "qualified":     icp.get("qualified", False),
        "segment":       icp.get("segment"),
        "pitch":         icp.get("pitch", ""),
    }

    print(f"[Enrich] {company} → {icp.get('segment')} "
          f"confidence={icp.get('confidence')} qualified={icp.get('qualified')}")

    return JSONResponse(result)


# ── Integration health check ──────────────────────────────────
@app.get("/test/integrations")
async def test_integrations():
    results = {}

    required = [
        "RESEND_API_KEY", "HUBSPOT_TOKEN",
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
        "CALCOM_API_KEY", "WEBHOOK_BASE_URL",
        "TENACIOUS_OUTBOUND_ENABLED",
    ]
    results["env_vars"] = {
        k: "set" if os.getenv(k) else "MISSING"
        for k in required
    }
    results["kill_switch"] = {
        "TENACIOUS_OUTBOUND_ENABLED": os.getenv("TENACIOUS_OUTBOUND_ENABLED", "false"),
        "outbound_active": OUTBOUND_ENABLED,
        "sink_email": STAFF_SINK_EMAIL,
    }

    try:
        import hubspot
        hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))
        hs.crm.contacts.basic_api.get_page(limit=1)
        results["hubspot"] = "connected"
    except Exception as e:
        results["hubspot"] = f"error: {str(e)[:80]}"

    try:
        import resend
        resend.api_key = os.getenv("RESEND_API_KEY")
        results["resend"] = "configured"
    except Exception as e:
        results["resend"] = f"error: {str(e)[:80]}"

    t = create_trace("integration_test", {"test": True})
    results["langfuse"] = f"ok trace_id={t.id}"

    return JSONResponse(results)