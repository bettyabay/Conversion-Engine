# Failure Taxonomy — Conversion Engine for Tenacious Consulting

Groups the 32 probes from probe_library.md by business cost severity.
Used to identify the highest-ROI failure mode for Act IV.

---

## Tier 1 — Brand-Reputation Failures (Irreversible)

These failures cause public or permanent brand damage that cannot be
recovered by fixing the system. One instance can outweigh weeks of
positive outreach.

| Probe | Failure | Why irreversible |
|---|---|---|
| PROBE-A07 | Anti-offshore founder receives outreach | LinkedIn post reaches 10K+ engineers. Cannot unsend. |
| PROBE-B04 | Wrong funding amount cited as verified fact | First sentence is factually wrong. Prospect corrects publicly. |
| PROBE-D05 | Agent pushes back on a deliberate strategic decision | CTO who made a reasoned choice is told by a vendor they are wrong. |
| PROBE-E01 | Multi-thread leakage between co-founder and VP Eng | Perception of coordinated pressure. Both threads die simultaneously. |

**Trigger rate estimate:** Low frequency (1-3% of interactions) but catastrophic per instance.

---

## Tier 2 — Commercial Failures (Recoverable but Costly)

These failures damage a specific deal or relationship but do not
necessarily spread beyond that prospect.

| Probe | Failure | ACV at risk |
|---|---|---|
| PROBE-A01 | Segment 1 pitch to post-layoff company | $240K-$720K |
| PROBE-A02 | Misses Segment 3 transition window | Highest-conversion segment. Window does not re-open. |
| PROBE-C01 | Bench over-commitment (8 engineers, 1 available) | $240K-$720K deal dies at discovery call |
| PROBE-C02 | NestJS capacity pitched while team is committed | Discovery call reveals mismatch. Deal dead. |
| PROBE-G02 | Agent invents pricing number | Commercial commitment delivery lead must contradict |
| PROBE-B03 | Wrong-scale pitch ($50M Series C in Segment 1 template) | Immediate mismatch. Thread ignored. |

**Trigger rate estimate:** Medium (5-10% of interactions without guards).

---

## Tier 3 — Quality Failures (Reduces Reply Rate)

These failures make the outreach feel generic or poorly researched.
They reduce reply rate from the expected 7-12% signal-grounded level
back toward the 1-3% cold-email baseline.

| Probe | Failure | Reply rate impact |
|---|---|---|
| PROBE-B01 | "Aggressive hiring" from 3 open roles | Drops from 7-12% to 1-3% |
| PROBE-B05 | Velocity claim from insufficient_signal | Same |
| PROBE-B06 | Low-confidence gap in Email 1 | Exposed as shallow research |
| PROBE-E02 | Generic peer names for all prospects | Research framing collapses |
| PROBE-D03 | Fourth cold email within 30 days | Spam classification risk |
| PROBE-H01 | Wrong timezone in meeting proposal | 30-40% of bookings lost per stalled-thread baseline |

**Trigger rate estimate:** High without guards (15-25% of interactions).
Most of these are already addressed by current implementation.

---

## Tier 4 — Infrastructure Failures (Pipeline Down)

These failures stop the pipeline from functioning entirely.

| Probe | Failure | Recovery cost |
|---|---|---|
| PROBE-F02 | Retry loop exhausts crawl limit | IP ban + re-registration |
| PROBE-E03 | SMS to opted-out prospect | GDPR/CAN-SPAM legal exposure |

**Trigger rate estimate:** Low but binary — when they trigger, the entire
pipeline goes down or creates legal liability.

---

## Highest-ROI Failure Mode

**PROBE-B01 / PROBE-B05 family: Signal over-claiming**

Rationale:
- Highest trigger rate without guards (~20% of interactions)
- Maps directly to tau2-bench Task 28 (arithmetic over-claiming, failed 4/4 trials)
- Tenacious-specific: style_guide.md makes honesty a brand constraint,
  not just a quality preference. One over-claimed signal invalidates
  the research-finding framing that differentiates Tenacious outreach.
- Addressable mechanically: a confidence gate before any assertion in
  the email composer costs ~400 tokens per interaction.
- Business impact: difference between 7-12% signal-grounded reply rate
  and 1-3% generic cold-email reply rate. At 40 qualified leads/month,
  that is 2-4 replies vs 3-5 replies per week — a measurable delta.

See target_failure_mode.md for full business-cost derivation.