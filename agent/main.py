"""
agent/main.py
FastAPI server — central hub for all webhooks and agent logic.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import uuid
import requests as _requests
import base64 as _base64
from datetime import datetime, timezone
from dotenv import load_dotenv

from agent.enrichment.crunchbase import find_company
from agent.enrichment.jobs import get_hiring_signal
from agent.enrichment.ai_maturity import score_ai_maturity
from agent.enrichment.competitor_gap import build_competitor_gap_brief
from agent.enrichment.layoffs import check_layoff_signal
from agent.icp_classifier import classify

load_dotenv()

app = FastAPI(title="Conversion Engine", version="1.0.0")


# ── Langfuse v4 — raw ingestion API (works with all versions) ─
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

        print(f"[Langfuse] status={resp.status_code} body={resp.text[:200]}")

    except Exception as e:
        print(f"[Langfuse fallback] {e} | id={trace_id}")

    return Trace(trace_id)


def flush_langfuse():
    pass  # ingestion API is synchronous


# ── Health check ──────────────────────────────────────────────
@app.get("/")
async def root():
    return {
        "status":    "alive",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system":    "Conversion Engine v1.0"
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


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
        from hubspot.crm.contacts.models import PublicObjectSearchRequest

        hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))

        search = hs.crm.contacts.search_api.do_search(
            public_object_search_request=PublicObjectSearchRequest(
                filters=[{
                    "propertyName": "email",
                    "operator":     "EQ",
                    "value":        attendee_email
                }]
            )
        )

        if search.results:
            contact_id = search.results[0].id
            hs.crm.contacts.basic_api.update(
                contact_id=contact_id,
                simple_public_object_input=SimplePublicObjectInput(
                    properties={"qualification_status": "DISCOVERY_BOOKED"}
                )
            )
            print(f"[HubSpot] contact {contact_id} -> DISCOVERY_BOOKED")
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
    try:
        data = await request.json()
    except Exception:
        data = {}

    lead_id = data.get("lead_id", "test_001")
    company = data.get("company", "Test Company")
    email   = data.get("email", os.getenv("RESEND_TO_TEST"))

    trace = create_trace(
        name="outreach_triggered",
        metadata={
            "lead_id":     lead_id,
            "company":     company,
            "email":       email,
            "environment": os.getenv("SANDBOX", "true"),
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
        engineering teams without the recruiting overhead.</p>
        <p>Would you be open to a 30-minute discovery call?</p>
        <p><a href="{cal_url}">Book a time here</a></p>
        <p>Best,<br>Tenacious Team</p>
        <p style="font-size:11px;color:#999;">Reply STOP to unsubscribe.</p>
        """

        response = resend.Emails.send({
            "from":    os.getenv("RESEND_FROM_EMAIL"),
            "to":      [email],
            "subject": f"{company} engineering capacity — worth a conversation?",
            "html":    html,
        })

        msg_id = getattr(response, "id", None) or (
            response.get("id") if isinstance(response, dict) else "unknown"
        )

        print(f"[Resend] sent to {email} msg_id={msg_id} trace={trace.id}")

        return JSONResponse({
            "status":            "email_sent",
            "trace_id":          trace.id,
            "resend_message_id": msg_id,
            "to":                email
        })

    except Exception as e:
        print(f"[Resend] error: {e}")
        return JSONResponse(
            {"status": "error", "message": str(e), "trace_id": trace.id},
            status_code=500
        )


# ── Integration health check ──────────────────────────────────
@app.get("/test/integrations")
async def test_integrations():
    results = {}

    required = [
        "RESEND_API_KEY", "HUBSPOT_TOKEN",
        "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY",
        "CALCOM_API_KEY", "WEBHOOK_BASE_URL"
    ]
    results["env_vars"] = {
        k: "set" if os.getenv(k) else "MISSING"
        for k in required
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


# ── Full enrichment pipeline ──────────────────────────────
@app.post("/enrich")
async def enrich_prospect(request: Request):
    """
    Runs the full enrichment pipeline on a prospect.
    POST body: {"company": "Acme Corp", "email": "cto@acme.com"}
    Returns: enrichment brief + ICP segment + outreach pitch
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

    # Step 1 — Firmographics
    cb_brief = find_company(company)

    # Step 2 — Hiring signal
    hiring   = get_hiring_signal(company, cb_brief.get("website"))

    # Step 3 — AI maturity
    maturity = score_ai_maturity(
        company_name=company,
        description=cb_brief.get("description", ""),
        job_titles=hiring.get("top_roles", []),
    )

    # Step 4 — Layoff signal
    layoff   = check_layoff_signal(company)

    # Step 5 — Competitor gap
    gap      = build_competitor_gap_brief(
        company_name=company,
        funding_type=cb_brief.get("last_funding_type", ""),
        ai_maturity=maturity.get("ai_maturity", 0),
        hiring_signal=hiring.get("signal_label", ""),
    )

    # Step 6 — ICP classification
    icp      = classify(
        company_name=company,
        funding_type=cb_brief.get("last_funding_type", ""),
        has_layoff_signal=layoff.get("has_layoff", False),
        has_new_cto=False,
        ai_maturity=maturity.get("ai_maturity", 0),
        hiring_signal=hiring.get("signal_label", ""),
        description=cb_brief.get("description", ""),
    )

    result = {
        "company":          company,
        "email":            email,
        "trace_id":         trace.id,
        "crunchbase":       cb_brief,
        "hiring_signal":    hiring,
        "ai_maturity":      maturity,
        "layoff_signal":    layoff,
        "competitor_gap":   gap,
        "icp":              icp,
        "qualified":        icp.get("qualified", False),
        "segment":          icp.get("segment"),
        "pitch":            icp.get("pitch", ""),
    }

    print(f"[Enrich] {company} → Segment {icp.get('segment')} "
          f"confidence={icp.get('confidence')} qualified={icp.get('qualified')}")


    # Write enrichment results back to HubSpot
    try:
        import hubspot
        from hubspot.crm.contacts import SimplePublicObjectInput
        from hubspot.crm.contacts.models import PublicObjectSearchRequest

        hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))

        search = hs.crm.contacts.search_api.do_search(
            public_object_search_request=PublicObjectSearchRequest(
                filters=[{
                    "propertyName": "email",
                    "operator": "EQ",
                    "value": email
                }]
            )
        )

        if search.results:
            contact_id = search.results[0].id
            hs.crm.contacts.basic_api.update(
                contact_id=contact_id,
                simple_public_object_input=SimplePublicObjectInput(
                    properties={
                        "icp_segment":           str(icp.get("segment", "")),
                        "segment_confidence":    icp.get("confidence", ""),
                        "qualification_status":  "OUTREACH_SENT",
                        "ai_maturity_score":     str(maturity.get("ai_maturity", 0)),
                        "hiring_signal_summary": hiring.get("brief", ""),
                        "competitor_gap_note":   gap.get("primary_gap", ""),
                        "last_enriched_at":      datetime.now(timezone.utc).isoformat(),
                    }
                )
            )
            print(f"[HubSpot] Updated {email} with enrichment data")
        else:
            print(f"[HubSpot] Contact not found for {email}")

    except Exception as e:
        print(f"[HubSpot] Write-back failed: {e}")
        
    return JSONResponse(result)

    @app.post("/setup/hubspot-properties")


async def setup_hubspot_properties():
    """Creates all custom contact properties in HubSpot."""
    try:
        import hubspot
        from hubspot.crm.properties import ModelProperty, PropertyCreate

        hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))

        properties_to_create = [
            ("icp_segment",          "ICP Segment",          "string"),
            ("segment_confidence",   "Segment Confidence",   "string"),
            ("ai_maturity_score",    "AI Maturity Score",    "string"),
            ("qualification_status", "Qualification Status", "string"),
            ("hiring_signal_summary","Hiring Signal Summary","string"),
            ("competitor_gap_note",  "Competitor Gap Note",  "string"),
            ("last_enriched_at",     "Last Enriched At",     "string"),
            ("trace_id",             "Trace ID",             "string"),
        ]

        created = []
        skipped = []

        for name, label, field_type in properties_to_create:
            try:
                hs.crm.properties.core_api.create(
                    object_type="contacts",
                    property_create=PropertyCreate(
                        name=name,
                        label=label,
                        type=field_type,
                        field_type="text",
                        group_name="contactinformation",
                    )
                )
                created.append(name)
                print(f"[HubSpot] Created property: {name}")
            except Exception as e:
                skipped.append(name)
                print(f"[HubSpot] Skipped {name}: {e}")

        return JSONResponse({
            "created": created,
            "skipped": skipped,
            "message": "HubSpot properties setup complete"
        })

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)