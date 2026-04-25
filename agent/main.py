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
    """
    Fires on every Cal.com BOOKING_CREATED event.
    1. Parses attendee info from payload
    2. Fetches enrichment data from HubSpot
    3. Generates 10-section discovery call context brief
    4. Saves brief to outputs/ and logs to Langfuse
    5. Updates HubSpot to DISCOVERY_BOOKED with brief_trace_id
    """
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
    duration       = payload.get("length", 30)
    organizer      = payload.get("organizer", {})
    delivery_lead  = organizer.get("name", "Arun Sharma")

    print(f"[Cal.com] event={event_type}")
    print(f"[Cal.com] attendee={attendee_email} time={meeting_time}")

    # Main booking trace
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

    # ── Fetch enrichment data from HubSpot ───────────────────
    contact_id      = None
    stored_segment  = "unknown"
    stored_ai_score = 0
    stored_velocity = "unknown"
    stored_gap_note = ""
    stored_company  = attendee_name  # fallback if HubSpot lookup fails
    icp_result      = {}
    hiring_signal   = {}
    ai_maturity     = {}
    competitor_gap  = {}

    try:
        import hubspot
        from hubspot.crm.contacts import SimplePublicObjectInput
        from hubspot.crm.contacts.models import (
            PublicObjectSearchRequest, Filter, FilterGroup
        )

        hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))
        f  = Filter(property_name="email", operator="EQ", value=attendee_email)
        fg = FilterGroup(filters=[f])
        search = hs.crm.contacts.search_api.do_search(
            public_object_search_request=PublicObjectSearchRequest(filter_groups=[fg])
        )

        if search.results:
            contact    = search.results[0]
            contact_id = contact.id
            props      = contact.properties or {}

            stored_segment   = props.get("icp_segment", "unknown")
            stored_ai_score  = int(props.get("ai_maturity_score", 0) or 0)
            stored_velocity  = props.get("hiring_signal_summary", "unknown")
            stored_gap_note  = props.get("competitor_gap_note", "")
            # Use stored company name from HubSpot if available
            stored_company   = props.get("company", "") or props.get("hs_company_name", "") or attendee_name

            # Reconstruct minimal enrichment dicts from stored props
            icp_result = {
                "segment":             stored_segment,
                "confidence":          float(props.get("segment_confidence", 0.7) or 0.7),
                "qualified":           True,
                "segment_description": f"Stored segment: {stored_segment}",
                "qualifying_signals":  [f"Segment stored from prior enrichment run"],
                "pitch":               f"Segment {stored_segment} pitch",
            }
            hiring_signal = {
                "prospect_name": attendee_name,
                "hiring_velocity": {
                    "open_roles_today":       0,
                    "open_roles_60_days_ago": 0,
                    "velocity_label":         stored_velocity,
                },
                "buying_window_signals": {
                    "funding_event":     {"detected": False},
                    "layoff_event":      {"detected": False},
                    "leadership_change": {"detected": False},
                },
                "tech_stack":    [],
                "honesty_flags": [],
            }
            ai_maturity = {
                "score":            stored_ai_score,
                "confidence_label": "medium",
                "brief":            f"AI maturity score {stored_ai_score}/3 from prior enrichment.",
            }
            competitor_gap = {
                "gap_findings":        [{"practice": stored_gap_note, "confidence": "medium", "peer_evidence": []}] if stored_gap_note else [],
                "suggested_pitch_shift": "Lead with highest-confidence finding from prior enrichment.",
            }

            print(f"[HubSpot] fetched contact {contact_id} segment={stored_segment}")
        else:
            print(f"[HubSpot] no contact found for {attendee_email} — using defaults")

    except Exception as e:
        print(f"[HubSpot] fetch failed: {e}")

    # ── Generate discovery call context brief ─────────────────
    brief_md    = ""
    brief_trace = None

    try:
        from agent.enrichment.discovery_brief import generate_discovery_brief

        # Parse prospect first name from full name
        first_name = attendee_name.split()[0] if attendee_name and attendee_name != "unknown" else "there"

        # Build Langfuse URL for the thread
        langfuse_host  = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        langfuse_url   = f"{langfuse_host}/trace/{trace.id}"

        brief_md = generate_discovery_brief(
            # Prospect info
            prospect_name       = first_name,
            prospect_title      = "VP Engineering",  # default; update if stored in HubSpot
            prospect_company    = stored_company,
            call_datetime_utc   = meeting_time,
            call_datetime_local = meeting_time,
            delivery_lead       = delivery_lead,
            duration_minutes    = int(duration or 30),
            thread_start_date   = datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            original_subject    = meeting_title,
            langfuse_trace_url  = langfuse_url,
            # Enrichment data
            icp_result          = icp_result,
            hiring_signal       = hiring_signal,
            competitor_gap      = competitor_gap,
            ai_maturity         = ai_maturity,
            # Trace
            trace_id            = trace.id,
        )

        print(f"[DiscoveryBrief] Generated {len(brief_md.split(chr(10)))} lines")

        # Save brief to outputs directory
        import pathlib
        outputs_dir = pathlib.Path("outputs")
        outputs_dir.mkdir(exist_ok=True)
        brief_filename = f"discovery_brief_{attendee_email.replace('@','_at_')}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.md"
        brief_path     = outputs_dir / brief_filename
        brief_path.write_text(brief_md, encoding="utf-8")
        print(f"[DiscoveryBrief] Saved to {brief_path}")

        # Log brief to Langfuse as a separate trace
        brief_trace = create_trace(
            name="discovery_brief_generated",
            user_id=attendee_email,
            metadata={
                "booking_trace_id": trace.id,
                "attendee_email":   attendee_email,
                "segment":          stored_segment,
                "brief_lines":      len(brief_md.splitlines()),
                "brief_file":       brief_filename,
                "meeting_time":     meeting_time,
            }
        )
        print(f"[DiscoveryBrief] Langfuse trace={brief_trace.id}")

    except Exception as e:
        print(f"[DiscoveryBrief] generation failed: {e}")

    # ── Update HubSpot to DISCOVERY_BOOKED ───────────────────
    try:
        import hubspot
        from hubspot.crm.contacts import SimplePublicObjectInput
        from hubspot.crm.contacts.models import (
            PublicObjectSearchRequest, Filter, FilterGroup
        )

        if not contact_id:
            hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))
            f  = Filter(property_name="email", operator="EQ", value=attendee_email)
            fg = FilterGroup(filters=[f])
            sr = hs.crm.contacts.search_api.do_search(
                public_object_search_request=PublicObjectSearchRequest(filter_groups=[fg])
            )
            if sr.results:
                contact_id = sr.results[0].id

        if contact_id:
            hs    = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))
            props = {
                "qualification_status": "DISCOVERY_BOOKED",
                "hs_lead_status":       "IN_PROGRESS",
                "trace_id":             trace.id,
            }
            # Store brief trace ID if generated successfully
            if brief_trace:
                props["competitor_gap_note"] = f"Brief trace: {brief_trace.id}"
            props.update(draft_hubspot_props())  # Policy Rule 6
            hs.crm.contacts.basic_api.update(
                contact_id=contact_id,
                simple_public_object_input=SimplePublicObjectInput(properties=props)
            )
            print(f"[HubSpot] contact {contact_id} → DISCOVERY_BOOKED")
        else:
            print(f"[HubSpot] no contact found for {attendee_email}")

    except Exception as e:
        print(f"[HubSpot] update failed: {e}")

    return JSONResponse({
        "status":              "booking_received",
        "brief_generated":     bool(brief_md),
        "brief_trace_id":      brief_trace.id if brief_trace else None,
        "trace_id": trace.id,
        "event":    event_type,
        "attendee": attendee_email
    })


# ── Manual trigger — send outreach email ─────────────────────
@app.post("/trigger/outreach")
async def trigger_outreach(request: Request):
    """
    Send a segment-specific signal-grounded outreach email.

    POST body:
      {
        "lead_id":        "...",
        "company":        "Turing Signal",
        "email":          "cto@turingsignal.com",
        "prospect_name":  "Alex",           # first name for salutation
        "email_number":   1,                # 1, 2, or 3 (cold sequence)
        # Optional — pre-computed enrichment to skip re-running /enrich
        "segment":        "segment_1_series_a_b",
        "hiring_signal":  {...},
        "competitor_gap": {...},
        "ai_maturity":    {...},
        "icp_result":     {...},
      }

    Kill switch: routes to sink if TENACIOUS_OUTBOUND_ENABLED != true.
    Draft marking: X-Tenacious-Status: draft on every email (Policy Rule 6).
    """
    try:
        data = await request.json()
    except Exception:
        data = {}

    lead_id       = data.get("lead_id", "turing_signal_001")
    company       = data.get("company", "Turing Signal")
    email         = data.get("email", os.getenv("RESEND_TO_TEST"))
    prospect_name = data.get("prospect_name", "there")
    email_number  = int(data.get("email_number", 1))
    cal_url       = os.getenv("CAL_URL", "https://cal.com/bethelhem-abay/discovery-call")

    # Kill switch gate
    email_to = gate_outbound(email, "email")

    # Run enrichment if not pre-supplied
    segment      = data.get("segment", "abstain")
    hiring       = data.get("hiring_signal", {})
    gap          = data.get("competitor_gap", {})
    ai_mat       = data.get("ai_maturity", {})
    icp          = data.get("icp_result", {})

    if not segment or segment == "abstain" and not icp:
        # Run full enrichment pipeline to get segment
        try:
            from agent.enrichment.crunchbase import find_company
            from agent.enrichment.jobs import get_hiring_signal
            from agent.enrichment.ai_maturity import score_ai_maturity
            from agent.enrichment.competitor_gap import build_competitor_gap_brief
            from agent.enrichment.layoffs import check_layoff_signal
            from agent.icp_classifier import classify

            cb     = find_company(company)
            hiring = get_hiring_signal(company)
            layoff = check_layoff_signal(company)
            ai_mat = score_ai_maturity(
                company_name=company,
                description=cb.get("description", ""),
                job_titles=hiring.get("_all_open_titles", []),
            )
            gap = build_competitor_gap_brief(
                company_name=company,
                prospect_ai_maturity=ai_mat.get("score", 0),
                funding_type=cb.get("last_funding_type", ""),
                hiring_signal=hiring.get("hiring_velocity", {}).get("velocity_label", ""),
            )
            icp = classify(
                company_name=company,
                funding_type=cb.get("last_funding_type", ""),
                open_eng_roles=hiring.get("hiring_velocity", {}).get("open_roles_today", 0),
                ai_maturity_score=ai_mat.get("score", 0),
            )
            segment = icp.get("segment", "abstain")
            # Inject prospect_name into hiring signal for composer
            hiring["prospect_name"] = company

        except Exception as e:
            print(f"[Enrich] failed during outreach trigger: {e}")

    # Compose segment-specific email
    try:
        from agent.email_composer import (
            compose_cold_email_1,
            compose_cold_email_2,
            compose_cold_email_3,
        )

        # Ensure hiring signal has prospect_name for composer
        if "prospect_name" not in hiring:
            hiring["prospect_name"] = company

        if email_number == 1:
            composed = compose_cold_email_1(
                prospect_first_name=prospect_name,
                segment=segment,
                hiring_signal=hiring,
                ai_maturity=ai_mat,
                icp_result=icp,
                cal_link=cal_url,
            )
        elif email_number == 2:
            composed = compose_cold_email_2(
                prospect_first_name=prospect_name,
                segment=segment,
                hiring_signal=hiring,
                competitor_gap=gap,
                cal_link=cal_url,
            )
        else:
            composed = compose_cold_email_3(
                prospect_first_name=prospect_name,
                company=company,
                segment=segment,
            )

        subject    = composed["subject"]
        body_text  = composed["body"]
        tone_pass  = composed["tone_pass"]
        word_count = composed["word_count"]
        violations = composed["violations"]

        if not tone_pass:
            print(f"[EmailComposer] TONE VIOLATIONS: {violations}")

    except Exception as e:
        print(f"[EmailComposer] failed: {e} — falling back to generic email")
        subject   = f"{company} engineering capacity — worth a conversation?"
        body_text = (
            "Hi " + prospect_name + ",\n\n"
            "I noticed " + company + " has been scaling its engineering team. "
            "Tenacious delivers dedicated engineering squads in 7-14 days — "
            "embedded in your stack, employees not contractors.\n\n"
            "Worth 15 minutes? → " + cal_url + "\n\n"
            + prospect_name + "\nResearch Partner, Tenacious Intelligence Corporation\ngettenacious.com"
        )
        tone_pass  = True
        word_count = 0
        violations = []

    # Convert plain text body to HTML
    html_body = body_text.replace("\n", "<br>")
    html = (
        f'<div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.6;color:#111;">'
        f'{html_body}'
        f'<p style="font-size:11px;color:#999;margin-top:24px;">Reply STOP to unsubscribe.</p>'
        f'</div>'
    )

    # Trace
    trace = create_trace(
        name="outreach_email_sent",
        metadata={
            "lead_id":          lead_id,
            "company":          company,
            "segment":          segment,
            "email_number":     email_number,
            "intended_email":   email,
            "actual_email":     email_to,
            "kill_switch":      not OUTBOUND_ENABLED,
            "tone_pass":        tone_pass,
            "word_count":       word_count,
            "violations":       violations,
            "environment":      os.getenv("SANDBOX", "true"),
        }
    )

    # Send via Resend
    try:
        import resend
        resend.api_key = os.getenv("RESEND_API_KEY")

        response = resend.Emails.send({
            "from":    os.getenv("RESEND_FROM_EMAIL"),
            "to":      [email_to],
            "subject": subject,
            "html":    html,
            "headers": make_draft_headers(),  # Policy Rule 6
        })

        msg_id = getattr(response, "id", None) or (
            response.get("id") if isinstance(response, dict) else "unknown"
        )

        print(f"[Resend] email={email_number} segment={segment} to={email_to} id={msg_id}")
        print(f"[KillSwitch] outbound_enabled={OUTBOUND_ENABLED}")
        print(f"[Tone] pass={tone_pass} words={word_count}")

        # ── HubSpot update ────────────────────────────────────
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
                    "qualification_status": "OUTREACH_SENT",
                    "icp_segment":          str(segment),
                    "last_enriched_at":     datetime.now(timezone.utc).isoformat(),
                    "trace_id":             trace.id,
                }
                props.update(draft_hubspot_props())  # Policy Rule 6
                hs.crm.contacts.basic_api.update(
                    contact_id=sr.results[0].id,
                    simple_public_object_input=SimplePublicObjectInput(properties=props)
                )
                print(f"[HubSpot] contact updated → OUTREACH_SENT segment={segment}")
        except Exception as e:
            print(f"[HubSpot] update failed: {e}")

        return JSONResponse({
            "status":             "email_sent",
            "trace_id":           trace.id,
            "resend_message_id":  msg_id,
            "to":                 email_to,
            "segment":            segment,
            "email_number":       email_number,
            "subject":            subject,
            "word_count":         word_count,
            "tone_pass":          tone_pass,
            "violations":         violations,
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

    # Kill switch gate
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

    # Read optional signal overrides from POST body
    override_funding_type    = data.get("funding_type", None)
    override_funding_amount  = data.get("funding_amount_usd", None)
    override_funding_days    = data.get("funding_days_ago", None)
    override_headcount       = data.get("headcount", None)
    override_open_eng_roles  = data.get("open_eng_roles", None)
    override_has_layoff      = data.get("has_layoff", None)
    override_layoff_days     = data.get("layoff_days_ago", None)
    override_layoff_pct      = data.get("layoff_percentage", None)
    override_has_new_cto     = data.get("has_new_cto", None)
    override_cto_days        = data.get("cto_days_ago", None)
    override_ai_maturity     = data.get("ai_maturity_score", None)
    override_specialist_days = data.get("specialist_role_open_days", None)

    # ResearchAgent — full enrichment pipeline with signal overrides
    from agent.agents.enrichment_pipeline import run as research_run
    research = research_run(
        company=company, email=email,
        funding_type=override_funding_type,
        funding_amount_usd=override_funding_amount,
        funding_days_ago=override_funding_days,
        headcount=override_headcount,
        open_eng_roles=override_open_eng_roles,
        has_layoff=override_has_layoff,
        layoff_days_ago=override_layoff_days,
        layoff_percentage=override_layoff_pct,
        has_new_cto=override_has_new_cto,
        cto_days_ago=override_cto_days,
        ai_maturity_score=override_ai_maturity,
        specialist_role_open_days=override_specialist_days,
    )

    cb_brief = research["crunchbase"]
    hiring   = research["hiring_signal"]
    layoff   = research["layoff_signal"]
    maturity = research["ai_maturity"]
    icp      = research["icp"]

    # InsightAgent — LLM competitor gap (falls back to rule-based)
    try:
        from agent.agents.competitor_analyst import run as insight_run
        gap = insight_run(
            company_name=company,
            hiring_signal_brief=hiring,
            sector=cb_brief.get("industry", "Software / SaaS"),
            use_eval_model=False,
        )
    except Exception as e:
        print(f"[InsightAgent] failed: {e} — using rule-based fallback")
        from agent.enrichment.competitor_gap import build_competitor_gap_brief
        gap = build_competitor_gap_brief(
            company_name=company,
            prospect_ai_maturity=maturity.get("score", 0),
            funding_type=cb_brief.get("last_funding_type", ""),
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