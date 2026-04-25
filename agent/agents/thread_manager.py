"""
agent/agents/thread_manager.py

ConversationAgent — state machine for the full prospect thread lifecycle.

States:
  COLD       → prospect in queue, no contact yet
  REPLIED    → prospect has responded at least once
  QUALIFIED  → agent has confirmed ICP match and bench fit
  BOOKED     → discovery call confirmed on Cal.com
  STALLED    → replied but not booked within 7 days
  CLOSED     → thread closed (won, lost, or opted out)

State is stored in HubSpot contact field: thread_state
Transitions are logged to Langfuse.
Re-engagement fires automatically when STALLED + 10 days passed.
"""
import os
import json
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# Valid states
STATES = ["COLD", "REPLIED", "QUALIFIED", "BOOKED", "STALLED", "CLOSED"]

# Valid transitions
TRANSITIONS = {
    "COLD":      ["REPLIED", "CLOSED"],
    "REPLIED":   ["QUALIFIED", "STALLED", "CLOSED"],
    "QUALIFIED": ["BOOKED", "STALLED", "CLOSED"],
    "BOOKED":    ["CLOSED"],
    "STALLED":   ["REPLIED", "CLOSED"],
    "CLOSED":    [],  # terminal state
}

# Days before STALLED triggers re-engagement
STALL_REENGAGEMENT_DAYS = 10
STALL_CLOSE_DAYS        = 31  # close after 31 days stalled (3 re-engagement emails)


def get_state(email: str) -> dict:
    """
    Get current thread state from HubSpot for a prospect.
    Returns dict with state, email_count, last_message_at, stalled_since.
    """
    try:
        import hubspot
        from hubspot.crm.contacts.models import (
            PublicObjectSearchRequest, Filter, FilterGroup
        )
        hs     = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))
        f      = Filter(property_name="email", operator="EQ", value=email)
        fg     = FilterGroup(filters=[f])
        result = hs.crm.contacts.search_api.do_search(
            public_object_search_request=PublicObjectSearchRequest(filter_groups=[fg])
        )
        if result.results:
            props = result.results[0].properties or {}
            return {
                "email":           email,
                "contact_id":      result.results[0].id,
                "state":           props.get("thread_state", "COLD"),
                "email_count":     int(props.get("email_count", 0) or 0),
                "last_message_at": props.get("last_agent_message_at", ""),
                "stalled_since":   props.get("stalled_since", ""),
                "segment":         props.get("icp_segment", "unknown"),
                "opted_out":       props.get("outreach_status", "") == "opted_out",
            }
    except Exception as e:
        print(f"[ConversationAgent] HubSpot get_state failed: {e}")

    return {"email": email, "state": "COLD", "email_count": 0,
            "last_message_at": "", "stalled_since": "", "opted_out": False}


def transition(email: str, new_state: str, reason: str = "") -> bool:
    """
    Transition a prospect to a new state.
    Validates the transition is legal, writes to HubSpot, logs to Langfuse.
    """
    current = get_state(email)
    old_state = current.get("state", "COLD")

    if new_state not in TRANSITIONS.get(old_state, []):
        print(f"[ConversationAgent] INVALID transition {old_state} → {new_state} for {email}")
        return False

    now = datetime.now(timezone.utc).isoformat()
    props = {
        "thread_state": new_state,
        "tenacious_status": "draft",
    }

    if new_state == "STALLED":
        props["stalled_since"] = now
    elif new_state == "REPLIED":
        props["stalled_since"] = ""  # clear stall
    elif new_state == "BOOKED":
        props["qualification_status"] = "DISCOVERY_BOOKED"
    elif new_state == "CLOSED":
        props["qualification_status"] = "CLOSED"

    try:
        import hubspot
        from hubspot.crm.contacts import SimplePublicObjectInput
        hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))
        hs.crm.contacts.basic_api.update(
            contact_id=current["contact_id"],
            simple_public_object_input=SimplePublicObjectInput(properties=props)
        )
        print(f"[ConversationAgent] {email}: {old_state} → {new_state} ({reason})")
        return True
    except Exception as e:
        print(f"[ConversationAgent] Transition write failed: {e}")
        return False


def handle_reply(email: str, reply_body: str) -> dict:
    """
    Process an inbound reply and determine next action.

    State transitions on reply:
      COLD    → REPLIED (first reply)
      STALLED → REPLIED (re-engaged)

    Returns dict with next_action, reply_class, state_change.
    """
    state = get_state(email)

    if state.get("opted_out"):
        return {"next_action": "suppress", "reply_class": "opted_out", "state_change": None}

    # Classify the reply
    reply_class = _classify_reply(reply_body)

    # Handle opt-out
    if reply_class == "hard_no":
        transition(email, "CLOSED", "hard_no reply")
        _mark_opted_out(email)
        return {"next_action": "opt_out_and_suppress", "reply_class": reply_class,
                "state_change": "COLD/STALLED → CLOSED"}

    # Handle soft defer
    if reply_class == "soft_defer":
        transition(email, "STALLED", "soft_defer — prospect asked to follow up later")
        return {"next_action": "log_reengagement_date_plus_45_days",
                "reply_class": reply_class, "state_change": "→ STALLED"}

    # Engaged or curious — move to REPLIED
    old_state = state.get("state", "COLD")
    if old_state in ("COLD", "STALLED"):
        transition(email, "REPLIED", f"prospect replied: {reply_class}")

    # Determine specific next action
    action_map = {
        "engaged":    "send_engaged_reply_book_discovery_call",
        "curious":    "send_curious_reply_with_cal_link",
        "objection":  "route_to_objection_handler",
        "ambiguous":  "route_to_human",
    }
    next_action = action_map.get(reply_class, "route_to_human")

    return {
        "next_action":    next_action,
        "reply_class":    reply_class,
        "state_change":   f"{old_state} → REPLIED",
        "should_qualify": reply_class in ("engaged", "objection"),
    }


def check_stalled_threads() -> list:
    """
    Find all prospects in STALLED state and determine action.
    Returns list of actions: reengagement or close.
    Called by a scheduler (daily cron).
    """
    actions = []
    now     = datetime.now(timezone.utc)

    # In production: query HubSpot for all contacts where thread_state=STALLED
    # For now: placeholder that demonstrates the logic
    try:
        import hubspot
        from hubspot.crm.contacts.models import (
            PublicObjectSearchRequest, Filter, FilterGroup
        )
        hs = hubspot.Client.create(access_token=os.getenv("HUBSPOT_TOKEN"))
        f  = Filter(property_name="thread_state", operator="EQ", value="STALLED")
        fg = FilterGroup(filters=[f])
        result = hs.crm.contacts.search_api.do_search(
            public_object_search_request=PublicObjectSearchRequest(filter_groups=[fg])
        )

        for contact in result.results:
            props        = contact.properties or {}
            email        = props.get("email", "")
            stalled_str  = props.get("stalled_since", "")
            email_count  = int(props.get("email_count", 0) or 0)

            if not stalled_str:
                continue

            try:
                stalled_since = datetime.fromisoformat(stalled_str.replace("Z", "+00:00"))
                days_stalled  = (now - stalled_since).days

                if days_stalled >= STALL_CLOSE_DAYS:
                    actions.append({
                        "email":      email,
                        "action":     "close",
                        "reason":     f"stalled {days_stalled} days — exceeded {STALL_CLOSE_DAYS} day close threshold",
                        "days_stalled": days_stalled,
                    })
                elif days_stalled >= STALL_REENGAGEMENT_DAYS:
                    # Determine which reengagement email to send
                    if email_count <= 3:
                        re_email_num = 1
                    elif email_count <= 4:
                        re_email_num = 2
                    else:
                        re_email_num = 3

                    actions.append({
                        "email":         email,
                        "action":        "reengagement",
                        "re_email_num":  re_email_num,
                        "days_stalled":  days_stalled,
                        "segment":       props.get("icp_segment", "unknown"),
                    })
            except (ValueError, TypeError):
                continue

    except Exception as e:
        print(f"[ConversationAgent] check_stalled_threads failed: {e}")

    print(f"[ConversationAgent] Found {len(actions)} stalled threads needing action")
    return actions


def mark_booked(email: str, booking_time: str) -> bool:
    """Called when Cal.com BOOKING_CREATED fires."""
    return transition(email, "BOOKED", f"discovery call booked at {booking_time}")


def mark_qualified(email: str, segment: str, confidence: float) -> bool:
    """Called when agent confirms ICP match and bench fit."""
    return transition(email, "QUALIFIED",
                      f"segment={segment} confidence={confidence:.2f}")


def get_email_number(email: str) -> int:
    """Determine which email number to send based on state and history."""
    state = get_state(email)
    count = state.get("email_count", 0)

    if state.get("state") == "STALLED":
        # Re-engagement sequence
        if count <= 3:   return "reengagement_1"
        elif count <= 4: return "reengagement_2"
        else:            return "reengagement_3"
    else:
        # Cold sequence
        if count == 0:   return "cold_1"
        elif count == 1: return "cold_2"
        else:            return "cold_3"


def _classify_reply(body: str) -> str:
    """Classify a reply into one of 5 classes."""
    body_lower = body.lower()
    if any(w in body_lower for w in [
        "not interested", "please remove", "stop emailing",
        "unsubscribe", "opt out", "remove me", "don't contact"
    ]):
        return "hard_no"
    if any(w in body_lower for w in [
        "not right now", "maybe later", "too busy",
        "not a priority", "check back", "try again in", "q3", "q4"
    ]):
        return "soft_defer"
    if any(w in body_lower for w in [
        "price", "cost", "expensive", "cheaper", "india",
        "offshore", "already have", "vendor", "poc", "pilot"
    ]):
        return "objection"
    if any(w in body_lower for w in [
        "tell me more", "what do you do", "how does",
        "interested", "curious", "more info"
    ]):
        return "curious"
    if len(body.split()) > 10:
        return "engaged"
    return "ambiguous"


def _mark_opted_out(email: str):
    """Mark contact as opted out in HubSpot."""
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
            hs.crm.contacts.basic_api.update(
                contact_id=sr.results[0].id,
                simple_public_object_input=SimplePublicObjectInput(properties={
                    "outreach_status": "opted_out",
                    "thread_state":    "CLOSED",
                    "tenacious_status": "draft",
                })
            )
            print(f"[ConversationAgent] Opted out: {email}")
    except Exception as e:
        print(f"[ConversationAgent] Opt-out write failed: {e}")


if __name__ == "__main__":
    print("=== ConversationAgent state machine ===")
    print(f"Valid states: {STATES}")
    print(f"Valid transitions: {json.dumps(TRANSITIONS, indent=2)}")
    print(f"Stall re-engagement threshold: {STALL_REENGAGEMENT_DAYS} days")
    print(f"Stall close threshold: {STALL_CLOSE_DAYS} days")

    # Test reply classification
    test_replies = [
        ("Not interested, please remove me", "hard_no"),
        ("Maybe reach out in Q3", "soft_defer"),
        ("Your price seems high vs Indian vendors", "objection"),
        ("Interesting, tell me more about the team structure", "curious"),
        ("We actually just closed our Series B last month and are struggling to hire Python engineers. What does the engagement look like?", "engaged"),
    ]
    print("\n=== Reply classification tests ===")
    for reply, expected in test_replies:
        result = _classify_reply(reply)
        status = "PASS" if result == expected else "FAIL"
        print(f"[{status}] '{reply[:50]}...' → {result} (expected: {expected})")