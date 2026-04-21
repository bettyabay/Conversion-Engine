import os
import time
from dotenv import load_dotenv
from langfuse import Langfuse

load_dotenv()

langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
)

def process_lead(lead_id, company, icp_segment, outbound_variant="signal_grounded"):
    """
    Simulates one full lead processing cycle.
    Every real agent action will call this same structure.
    """

    # ── Root trace — one per lead ──────────────────────────
    # This trace_id is what gets stored in HubSpot and
    # referenced in evidence_graph.json
    trace = langfuse.start_observation(
        name="lead_processing",
        as_type="span",
        metadata={
            "lead_id":              lead_id,
            "company":              company,
            "icp_segment":          icp_segment,
            "environment":          os.getenv("SANDBOX", "true"),
            "outbound_variant":     outbound_variant,
            "qualification_status": "DISCOVERED",
        }
    )

    total_cost = 0.0
    start_time = time.time()

    # ── Span 1: Enrichment pipeline ────────────────────────
    enrichment_span = trace.start_observation(
        name="enrichment_pipeline",
        as_type="span",
        metadata={
            "step":       "crunchbase_pull",
            "lead_id":    lead_id,
            "data_sources": ["crunchbase_odm", "job_posts", "layoffs_fyi"]
        }
    )
    # Simulate enrichment work
    time.sleep(0.1)
    enrichment_span.update(
        metadata={
            "crunchbase_id":      f"{lead_id}_crunchbase",
            "last_enriched_at":   "2026-04-21T18:00:00Z",
            "ai_maturity_score":  1,
            "job_post_velocity":  "HIGH",
            "layoff_signal":      False,
            "leadership_change":  True,
        }
    )
    enrichment_span.end()

    # ── Span 2: ICP classification ─────────────────────────
    icp_span = trace.start_observation(
        name="icp_classification",
        as_type="span",
        metadata={"lead_id": lead_id}
    )
    time.sleep(0.05)
    icp_span.update(
        metadata={
            "segment":            icp_segment,
            "confidence":         0.87,
            "bench_match":        True,
            "pitch_language":     "segment_3_new_cto",
        }
    )
    icp_span.end()

    # ── Generation: Email composition (LLM call) ───────────
    email_generation = trace.start_observation(
        name="email_composition",
        as_type="generation",
        model="claude-sonnet-4-6",
        model_parameters={
            "temperature": 0.3,
            "max_tokens":  500,
        },
        input={
            "lead_id":         lead_id,
            "icp_segment":     icp_segment,
            "outbound_variant": outbound_variant,
            "brief_available": True,
        },
        metadata={
            "outbound_variant": outbound_variant,
            "channel":          "email",
        }
    )
    time.sleep(0.1)
    email_generation.update(
        output={
            "subject":    "Turing Signal's engineering hiring surge — worth 30 mins?",
            "body_words": 142,
            "cta":        "cal.com booking link",
        },
        usage_details={
            "input":  820,
            "output": 310,
        },
        metadata={
            "resend_message_id": "4f195fd2-d46f-497e-909x-test",
            "sent_at":           "2026-04-21T18:00:00Z",
        }
    )
    email_generation.end()

    # Calculate cost (Claude Sonnet 4.6 pricing)
    input_cost  = 820  * (3.0  / 1_000_000)   # $3 per 1M input tokens
    output_cost = 310  * (15.0 / 1_000_000)   # $15 per 1M output tokens
    total_cost  = input_cost + output_cost

    wall_time = time.time() - start_time

    # ── Update root trace with final metrics ───────────────
    trace.update(
        metadata={
            "lead_id":              lead_id,
            "company":              company,
            "icp_segment":          icp_segment,
            "environment":          os.getenv("SANDBOX", "true"),
            "outbound_variant":     outbound_variant,
            "qualification_status": "OUTREACH_SENT",
            "cost_usd":             round(total_cost, 6),
            "wall_time_s":          round(wall_time, 3),
            "email_sent":           True,
            "hubspot_contact_id":   "761306415310",
        }
    )

    trace.end()

    langfuse.flush()

    return {
        "trace_id":    trace.id,
        "lead_id":     lead_id,
        "cost_usd":    round(total_cost, 6),
        "wall_time_s": round(wall_time, 3),
    }


# ── Run the smoke test ─────────────────────────────────────
if __name__ == "__main__":
    result = process_lead(
        lead_id         = "turingsignal_001",
        company         = "Turing Signal",
        icp_segment     = "Segment 3 - New CTO",
        outbound_variant = "signal_grounded"
    )

    print(f"Trace ID:    {result['trace_id']}")
    print(f"Cost:        ${result['cost_usd']}")
    print(f"Wall time:   {result['wall_time_s']}s")
    print(f"Langfuse is alive.")
    print(f"View at:     https://cloud.langfuse.com")