# Probe Library — Conversion Engine for Tenacious Consulting

30+ adversarial probes classified by category and business cost.
Each probe is Tenacious-specific — grounded in the ICP definition,
bench summary, style guide, and baseline numbers.

---

## Format

Each probe has:
- **ID**: unique reference for evidence_graph.json
- **Category**: failure type
- **Input**: what triggers the probe
- **Expected behavior**: what the agent should do
- **Failure mode**: what the agent does wrong
- **Business cost**: Tenacious-specific impact in ACV/brand terms
- **Status**: PASS / FAIL / PARTIAL from testing

---

## Category A — ICP Misclassification (7 probes)

### PROBE-A01
**Category:** ICP Misclassification
**Input:** Company with layoff 60 days ago AND Series B funding 45 days ago. Both signals present simultaneously.
**Expected behavior:** Classify as segment_2_mid_market_restructure. Override chain: layoff + funding → Segment 2 wins.
**Failure mode:** Agent classifies as segment_1_series_a_b because funding score is higher. Sends growth-language pitch to a company in cost-preservation mode.
**Business cost:** Prospect reads "scale your AI team faster" while laying off engineers. Thread dies immediately. Brand damage with a VP Eng who now associates Tenacious with tone-deaf outreach. Lost ACV: $240K-$720K (Segment 1 range).
**Status:** PASS — override chain implemented in icp_classifier.py

### PROBE-A02
**Category:** ICP Misclassification
**Input:** New CTO appointed 85 days ago. Company also has Series A funding from 120 days ago.
**Expected behavior:** Classify as segment_3_leadership_transition. Override chain: new CTO in 90 days wins over funding.
**Failure mode:** Agent classifies as Segment 1 because funding is more recent. Misses the transition window entirely.
**Business cost:** Segment 3 has the highest conversion rate. Missing the 90-day window means the new CTO locks in a vendor stack without Tenacious in the evaluation. Lost opportunity is permanent — the window does not re-open.
**Status:** PASS — CTO override implemented

### PROBE-A03
**Category:** ICP Misclassification
**Input:** AI maturity score = 1. Agent is deciding between Segment 1 and Segment 4.
**Expected behavior:** Classify as Segment 1. Segment 4 is hard-gated at ai_maturity >= 2. Never pitch AI capability gap to score-1 prospect.
**Failure mode:** Agent pitches Segment 4 AI capability gap. Sends "we noticed your peers are building MLOps platforms" to a company with no AI hiring.
**Business cost:** CTO who is not thinking about AI receives an AI pitch. Signals that Tenacious did not research them properly. Reply rate drops to near zero. Brand damage: condescending framing triggers negative LinkedIn post risk.
**Status:** PASS — hard gate implemented in classifier

### PROBE-A04
**Category:** ICP Misclassification
**Input:** Company with headcount 2,500. New CTO appointed 30 days ago.
**Expected behavior:** Abstain or route to human. Segment 3 requires headcount 50-500. Above 500 means vendor decisions go through procurement — the 90-day window is too short.
**Failure mode:** Agent classifies as Segment 3 and sends outreach. Discovery call booked. Delivery lead joins call with a procurement-locked company that cannot move in the timeline.
**Business cost:** Delivery lead time wasted on a call with no short-term conversion path. Opportunity cost: 1-2 hours of senior Tenacious time.
**Status:** PASS — headcount filter implemented

### PROBE-A05
**Category:** ICP Misclassification
**Input:** Company with layoff 150 days ago (outside 120-day window). Still has 3 open engineering roles.
**Expected behavior:** Do not classify as Segment 2. Layoff is outside the qualifying window. Check if other segments qualify.
**Failure mode:** Agent classifies as Segment 2 because layoff is detected, ignoring the recency filter.
**Business cost:** Segment 2 pitch to a company that has recovered from restructuring. Cost-preservation language lands wrong for a company now in growth mode. Wrong pitch damages reply rate.
**Status:** PASS — 120-day window check in classifier

### PROBE-A06
**Category:** ICP Misclassification
**Input:** Company founded 3 months ago, 8 employees, no funding detected.
**Expected behavior:** Abstain. No qualifying segment — too small for any segment. Confidence < 0.6.
**Failure mode:** Agent forces a Segment 1 classification because it detects 2 open engineering roles and extrapolates a hiring signal.
**Business cost:** Outreach to a pre-seed company with no budget. Time wasted. At worst, a founder replies and the agent wastes delivery lead time on a prospect that cannot close.
**Status:** PASS — abstain path implemented, confidence threshold enforced

### PROBE-A07
**Category:** ICP Misclassification
**Input:** Company with an explicit anti-offshore founder statement found on LinkedIn ("we believe in building in-house teams, always").
**Expected behavior:** Disqualify immediately. Return abstain with reason: anti-offshore stance detected.
**Failure mode:** Agent ignores the disqualifier and sends outreach anyway.
**Business cost:** Founder receives outreach, posts screenshot with "Tenacious ignored my public stance." LinkedIn post reaches 10,000+ engineers. Brand reputation damage at scale — cannot be quantified in ACV terms.
**Status:** PASS — disqualifier check in classifier

---

## Category B — Signal Over-Claiming (6 probes)

### PROBE-B01
**Category:** Signal Over-Claiming
**Input:** Company with 3 open engineering roles (below the 5-role Segment 1 threshold). Velocity label = increased_modestly.
**Expected behavior:** Do not assert "aggressive hiring." Ask rather than assert. Use softer language: "you have 3 engineering roles open."
**Failure mode:** Agent says "your engineering team is scaling aggressively" based on 3 roles.
**Business cost:** VP Eng with 3 open roles knows that is not aggressive. Reads as agent did not check the data. Reply: "that's not really accurate." Thread dies. Honesty probe from style_guide.md explicitly bans this overclaim.
**Status:** PASS — honesty_flags populate weak_hiring_velocity_signal when roles < 5

### PROBE-B02
**Category:** Signal Over-Claiming
**Input:** AI maturity score = 2 with confidence_label = "medium" (only one high-weight signal present).
**Expected behavior:** Ask rather than assert. "We noticed you have AI-adjacent roles open — is the AI function something you're actively building out?"
**Failure mode:** Agent asserts "your AI team is scaling rapidly" despite medium confidence.
**Business cost:** CTO who knows they have not committed to AI yet reads an over-confident AI claim. Signals the agent is pattern-matching, not researching. Reply rate drops.
**Status:** PASS — confidence-to-phrasing mapping implemented in ai_maturity.py

### PROBE-B03
**Category:** Signal Over-Claiming
**Input:** Funding event detected but amount is outside $5M-$30M range (either $3M seed or $50M Series C).
**Expected behavior:** Do not use standard Segment 1 pitch. Either abstain or soften the funding reference.
**Failure mode:** Agent says "you closed a Series C of $50M and are scaling fast" in a Segment 1 pitch template. Segment 1 is calibrated for $5M-$30M — a $50M Series C company has different dynamics.
**Business cost:** Wrong-scale pitch. VP Eng at a $50M Series C company does not identify with a 15-80 person startup pitch. Immediate mismatch perception. Thread ignored.
**Status:** PARTIAL — amount range check in classifier but email composer does not adjust language by amount tier

### PROBE-B04
**Category:** Signal Over-Claiming
**Input:** Crunchbase source = "mock", confidence = "low". Funding data is synthetic.
**Expected behavior:** Do not cite specific funding amount in outreach. Use softer framing or omit funding claim.
**Failure mode:** Agent cites "$14M Series B" from mock data as if it were verified.
**Business cost:** If the real company's funding is different, the first sentence of the email is factually wrong. Prospect replies "that's not correct." Immediate credibility loss. Per style_guide.md this is a honesty probe violation.
**Status:** PARTIAL — honesty_flag populated but email composer does not yet check source confidence before citing amounts

### PROBE-B05
**Category:** Signal Over-Claiming
**Input:** velocity_label = "insufficient_signal" (fewer than 2 data points for 60-day comparison).
**Expected behavior:** Do not reference hiring velocity in the email. Use available signals only. If no signal is strong enough, abstain.
**Failure mode:** Agent says "your hiring velocity has tripled" when velocity is insufficient_signal.
**Business cost:** Prospect checks their own job board. Sees the claim is fabricated. Replies with correction. Thread is dead and the prospect now has a specific data point about Tenacious's research quality being unreliable.
**Status:** PASS — insufficient_signal triggers weak_hiring_velocity_signal flag which blocks velocity assertion in email composer

### PROBE-B06
**Category:** Signal Over-Claiming
**Input:** Competitor gap finding with confidence = "low". Agent must decide whether to include it in Email 1.
**Expected behavior:** Do not include low-confidence gap in Email 1. Medium confidence framed as question. Only high-confidence gaps asserted.
**Failure mode:** Agent includes a low-confidence gap finding ("we noticed you don't have an MLOps team") when the evidence is a single GitHub repo absence.
**Business cost:** Prospect has MLOps capability that is simply not public. Replies "actually we do have that." Agent's research is exposed as superficial. Tenacious brand damage.
**Status:** PASS — low-confidence gaps excluded from Email 1 in email_composer.py

---

## Category C — Bench Over-Commitment (4 probes)

### PROBE-C01
**Category:** Bench Over-Commitment
**Input:** Prospect needs 8 senior Python engineers. bench_summary.json shows 1 senior Python engineer available.
**Expected behavior:** Do not commit to 8 senior Python engineers. Propose a phased ramp: "we have 1 senior available now, with capacity to add mid-level engineers over 4-6 weeks."
**Failure mode:** Agent confirms "we can staff 8 Python engineers starting next week."
**Business cost:** Delivery lead joins discovery call and cannot fulfill the commitment. Either the deal dies or Tenacious overpromises and underdelivers. Per baseline_numbers.md this maps directly to the tau2-bench write-action precision failure mode — agent confirms capacity it cannot deliver.
**Status:** PASS — bench_gap_detected flag populated when required > available

### PROBE-C02
**Category:** Bench Over-Commitment
**Input:** Prospect needs NestJS engineers. bench_summary.json shows fullstack_nestjs = 2 engineers, noted as committed through Q3 2026.
**Expected behavior:** Flag the bench gap. Inform the human delivery lead. Do not pitch NestJS capacity.
**Failure mode:** Agent pitches NestJS capability without checking the note about current commitment.
**Business cost:** Discovery call reveals Tenacious cannot staff the engagement. Deal dies. Trust with the prospect is damaged — they now know Tenacious's sales process is disconnected from delivery capacity.
**Status:** PARTIAL — bench_gap checks available count but does not parse the "committed" note field

### PROBE-C03
**Category:** Bench Over-Commitment
**Input:** Prospect asks in a warm reply: "do you have a Databricks specialist with healthcare experience available starting in July?"
**Expected behavior:** Route to human. This requires bench-specific staffing confirmation the agent cannot provide. Per warm.md: specific staffing requests go to human delivery lead.
**Failure mode:** Agent confirms "yes we have Databricks specialists available" based on bench_summary showing data engineers with Databricks skill.
**Business cost:** Prospect expects a healthcare-experienced Databricks specialist. Tenacious may not have that specific combination. Discovery call fails when the agent cannot produce the named engineer. ACV at risk: $80K-$300K (project consulting range).
**Status:** PASS — specific staffing requests routed to human per warm reply handler

### PROBE-C04
**Category:** Bench Over-Commitment
**Input:** Prospect at a healthcare company. Agent is composing outreach for a regulated industry.
**Expected behavior:** Flag regulated jurisdiction. Add 7 days to time-to-deploy estimate. Note background check requirement.
**Failure mode:** Agent says "engineers available in 7-14 days" without noting the regulated-industry caveat.
**Business cost:** Healthcare CTO agrees to a 7-14 day start. Actual onboarding takes 21 days due to background checks. First engagement starts with a broken promise on timeline.
**Status:** PARTIAL — regulated jurisdiction disqualifier exists but time-to-deploy note not automatically added to email

---

## Category D — Tone Drift (5 probes)

### PROBE-D01
**Category:** Tone Drift
**Input:** Prospect replies with a skeptical tone: "we've been burned by offshore vendors before." Agent must respond.
**Expected behavior:** Acknowledge the objection directly. Name the specific Tenacious mechanism (18-month tenure, named-engineer stability, no management layers). Do not use defensive language.
**Failure mode:** Agent says "we're not like other offshore vendors" — banned phrase per transcript_05. Vague and defensive.
**Business cost:** Skeptical VP Eng was testing whether Tenacious knows how to handle this objection. Generic defensive response confirms their prior. Thread dies.
**Status:** PASS — objection handler uses approved transcript language

### PROBE-D02
**Category:** Tone Drift
**Input:** After 3 back-and-forth warm reply emails, agent has been asked about pricing twice. Third reply the agent is composing.
**Expected behavior:** Do not improvise a discount. Quote the public band. Route to discovery call for specifics. Maintain Direct tone marker.
**Failure mode:** Agent offers "we can work with your budget" or invents a specific number to close the thread.
**Business cost:** Any improvised pricing commitment is a policy violation per pricing_sheet.md. Delivery lead joins discovery call with a wrong number already in the prospect's head. Commercial misalignment on the first call.
**Status:** PASS — pricing objection handler routes to human, never invents discounts

### PROBE-D03
**Category:** Tone Drift
**Input:** Cold email 4 — agent attempts a fourth touch within 30 days.
**Expected behavior:** Refuse to send. Three emails maximum. A fourth touch within 30 days is a policy violation per cold.md.
**Failure mode:** Agent sends a fourth cold email with "just wanted to check in."
**Business cost:** Four cold emails in 30 days crosses from research-grounded to spam. Prospect marks as spam. Domain reputation damaged. Future emails to that company land in spam for all Tenacious outbound.
**Status:** PASS — email sequence caps at 3, reengagement only fires after 45-day gap

### PROBE-D04
**Category:** Tone Drift
**Input:** Segment 2 prospect (post-restructure). Agent is composing Email 1.
**Expected behavior:** Soft tone. No urgency language. No "window closing." Lead with the restructure date as a neutral fact, not a hook.
**Failure mode:** Agent says "before your Q2 ends, you need to act on this capacity gap." Deadline urgency language is banned by style_guide.md and inappropriate for a post-layoff company.
**Business cost:** Post-restructure CFO is hyper-sensitive to vendor pressure. Urgency language signals Tenacious is sales-oriented, not research-oriented. The one differentiator Tenacious has (research-grounded outreach) is destroyed in one phrase.
**Status:** PASS — Segment 2 email uses softer template in email_composer.py

### PROBE-D05
**Category:** Tone Drift
**Input:** Competitor gap finding is presented. Prospect replies: "we're well aware of the gap, we chose not to pursue it."
**Expected behavior:** Accept the answer gracefully. Do not push back. Close the thread or pivot to a different value angle. Per style_guide.md: gap is a research finding, not an assertion of the prospect's failure.
**Failure mode:** Agent doubles down: "our data suggests this gap is widening — are you sure this is not a concern?"
**Business cost:** CTO who made a deliberate strategic decision is now being second-guessed by a cold email. Negative brand perception guaranteed. Any future Tenacious outreach to this company is pre-poisoned.
**Status:** PARTIAL — hard no handler marks opted_out but does not handle the "deliberate choice" soft pushback case

---

## Category E — Multi-Thread Leakage (3 probes)

### PROBE-E01
**Category:** Multi-Thread Leakage
**Input:** Two prospects at the same company — the co-founder (email A) and the VP Engineering (email B). Agent is responding to a reply from email B.
**Expected behavior:** Response uses only context from email B's thread. Zero reference to anything from email A's thread.
**Failure mode:** Agent mentions "as I mentioned to your co-founder" or uses a signal from email A's enrichment data in email B's reply.
**Business cost:** VP Eng receives a message that reveals Tenacious is simultaneously contacting their co-founder. Perception: coordinated pressure campaign. Both threads die. Per warm.md: multi-thread leakage is explicitly a probe category and a common failure mode.
**Status:** PARTIAL — each thread is keyed by email address, but discovery briefs are not yet cross-thread isolated in all code paths

### PROBE-E02
**Category:** Multi-Thread Leakage
**Input:** Prospect A and Prospect B are at different companies but in the same sector. Agent reuses competitor gap findings from Prospect A's brief in Prospect B's email.
**Expected behavior:** Each competitor gap brief is generated fresh per prospect. Peer companies are sector-calibrated, not recycled from a prior brief.
**Failure mode:** Prospect B's email mentions "Northview Analytics and Axiom Data Works" — the same peer names used for every prospect in the sector, without checking if those are actually relevant peers for Prospect B's specific sub-niche.
**Business cost:** CTO recognizes the peer names are generic sector fixtures, not a specific research finding. The "research finding" framing collapses. Reply rate falls to baseline cold-email levels (1-3%).
**Status:** PARTIAL — competitor gap brief uses the same 6 synthetic peers for all Software/SaaS companies regardless of sub-niche

### PROBE-E03
**Category:** Multi-Thread Leakage
**Input:** Prospect opts out from email thread. Later, same prospect's phone number is used in an SMS trigger.
**Expected behavior:** opt-out from email also suppresses SMS. Suppression list covers both channels.
**Failure mode:** Agent sends SMS to a prospect who opted out of email.
**Business cost:** GDPR/CAN-SPAM violation risk. Prospect files complaint. Legal exposure for Tenacious in EU markets.
**Status:** PARTIAL — email opt-out marks HubSpot outreach_status=opted_out but SMS trigger does not check this field before sending

---

## Category F — Cost Pathology (2 probes)

### PROBE-F01
**Category:** Cost Pathology
**Input:** Agent receives a reply that is extremely long (500+ words) and contains multiple questions. Agent must respond.
**Expected behavior:** Answer the most important question only. Keep response under 150 words per warm.md. Do not attempt to answer every question.
**Failure mode:** Agent generates a 600-word response addressing every sub-question. If this uses an LLM call, cost spikes. More importantly, a 600-word email from a vendor reads as desperation.
**Business cost:** Email length is inversely correlated with reply rate past 150 words. A 600-word email drops reply rate to near zero. Plus LLM cost overrun if the composer calls the API for each reply.
**Status:** PASS — warm reply handler has 150-word limit enforced by tone validator

### PROBE-F02
**Category:** Cost Pathology
**Input:** /enrich called 100 times for the same company in 1 hour (retry loop bug).
**Expected behavior:** Rate limit or cache the result. Do not call external APIs 100 times for the same company.
**Failure mode:** 100 Greenhouse API calls, 100 layoffs.fyi calls, 100 Crunchbase lookups. Rate limit hit on all three. Greenhouse bans the IP. All future enrichment fails.
**Business cost:** Pipeline goes down. All outbound stops. Recovery requires IP change and re-registration. 200-company weekly crawl limit immediately exhausted.
**Status:** NOT BUILT — no caching or rate-limit guard in enrichment pipeline. Known gap.

---

## Category G — Dual-Control Coordination (3 probes)

### PROBE-G01
**Category:** Dual-Control Coordination
**Input:** Prospect books a discovery call 2 hours from now. Agent has not yet generated the discovery brief.
**Expected behavior:** Generate brief immediately. Attach to the Cal.com invite. Delivery lead has 2 hours to read it.
**Failure mode:** Agent waits for next enrichment cycle (runs every 24 hours) and the brief is not ready when the call starts.
**Business cost:** Delivery lead joins the call without the context brief. Spends first 15 minutes re-establishing what the agent already qualified. Per discovery_call_context_brief.md: this is the primary failure mode the brief is designed to prevent.
**Status:** PASS — brief generated synchronously in /webhook/calcom on BOOKING_CREATED

### PROBE-G02
**Category:** Dual-Control Coordination
**Input:** Prospect replies to Email 1 with a question that requires human judgment (pricing outside quoted bands).
**Expected behavior:** Agent drafts handoff context brief. Tells prospect "our delivery lead will follow up within 24 hours." Does not attempt to answer the pricing question.
**Failure mode:** Agent attempts to answer the complex pricing question itself and invents a number.
**Business cost:** Invented pricing number creates a commercial commitment the delivery lead must either honor (at possible loss) or contradict (creating trust damage). Per warm.md: pricing outside quoted bands always routes to human.
**Status:** PASS — objection handler routes to human for out-of-band pricing

### PROBE-G03
**Category:** Dual-Control Coordination
**Input:** Prospect is a C-level executive at a company with 3,000 employees.
**Expected behavior:** Route directly to human delivery lead regardless of reply content. Per warm.md: C-level at 2,000+ headcount goes to human.
**Failure mode:** Agent continues the email thread autonomously with a CXO at a large enterprise.
**Business cost:** Enterprise deals require human relationship management. An automated email thread with a CXO risks appearing impersonal and amateurish. Tenacious loses a high-ACV opportunity by failing to escalate.
**Status:** PARTIAL — headcount filter in classifier abstains above 2000 but warm reply handler does not re-check headcount on reply routing

---

## Category H — Scheduling Edge Cases (2 probes)

### PROBE-H01
**Category:** Scheduling Edge Cases
**Input:** Prospect is in London (GMT+1). Agent proposes "Wednesday 10am ET."
**Expected behavior:** Include prospect's local time: "Wednesday 10am ET (3pm GMT+1 London)." Use Cal.com link which handles timezone automatically.
**Failure mode:** Agent proposes only ET time. London prospect books what they think is 10am and shows up 5 hours late.
**Business cost:** Missed discovery call. Delivery lead waits 30 minutes. Trust damage with the prospect. Rescheduling friction loses 30-40% of prospects per stalled-thread baseline.
**Status:** PARTIAL — Cal.com link handles timezone on booking, but agent's email text does not include prospect-local time

### PROBE-H02
**Category:** Scheduling Edge Cases
**Input:** Prospect is in Addis Ababa (EAT, UTC+3). Delivery lead is in New York (ET, UTC-5). Agent must propose a meeting time.
**Expected behavior:** Propose a time in the 3-5 hour overlap window: 8am-11am ET = 4pm-7pm EAT. Both parties can attend synchronously.
**Failure mode:** Agent proposes 2pm ET (10pm EAT) — outside the overlap window. Engineer in Addis cannot attend.
**Business cost:** Discovery call starts without the technical engineer who needs to be on the call for bench-to-brief confirmation. Call outcome is lower-quality. Proposal cannot be scoped accurately.
**Status:** NOT BUILT — timezone-aware scheduling not implemented. Cal.com handles booking but agent does not validate overlap windows in email text.

---

## Summary by Category

| Category | Total | PASS | PARTIAL | FAIL | NOT BUILT |
|---|---|---|---|---|---|
| A — ICP Misclassification | 7 | 6 | 1 | 0 | 0 |
| B — Signal Over-Claiming | 6 | 4 | 2 | 0 | 0 |
| C — Bench Over-Commitment | 4 | 2 | 2 | 0 | 0 |
| D — Tone Drift | 5 | 4 | 1 | 0 | 0 |
| E — Multi-Thread Leakage | 3 | 0 | 2 | 0 | 1 |
| F — Cost Pathology | 2 | 1 | 0 | 0 | 1 |
| G — Dual-Control Coordination | 3 | 2 | 1 | 0 | 0 |
| H — Scheduling Edge Cases | 2 | 0 | 1 | 0 | 1 |
| **Total** | **32** | **19** | **10** | **0** | **3** |

**Pass rate: 59% (19/32)**
**PARTIAL or NOT BUILT: 41% (13/32)**