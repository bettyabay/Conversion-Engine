# Target Failure Mode — Conversion Engine for Tenacious Consulting

## The Highest-ROI Failure Mode

**Signal over-claiming: the agent asserts a hiring or AI-maturity claim
it cannot ground in the hiring signal brief.**

---

## Definition

Signal over-claiming occurs when the agent uses confident assertion
language ("you are scaling aggressively," "your AI team is growing
rapidly") when the underlying signal is weak — fewer than 5 open roles,
velocity_label = insufficient_signal, ai_maturity confidence_label = low
or medium with only one high-weight signal.

Operationally: the agent makes a verifiable claim the prospect can
immediately falsify by checking their own job board.

---

## Why This Is the Highest-ROI Target

### 1. Trigger frequency without the guard

In the 3 complete tau2-bench dev-slice trials, arithmetic over-claiming
(the benchmark analog) failed in 100% of triggered instances (4/4 trials,
Tasks 28 and 0). The failure rate for signal over-claiming in outreach
is estimated at 15-25% of interactions without the honesty gate — based
on the mock Crunchbase data returning low-confidence signals for all
synthetic test prospects.

### 2. Business cost in Tenacious terms

The Tenacious pitch depends on the "research finding" frame. The agent
is not selling Tenacious — it is sharing a grounded observation about the
prospect's situation. One falsifiable claim in the first sentence collapses
this frame for the entire email.

**Reply rate impact:**
- Signal-grounded outbound (top-quartile): 7-12% (Clay/Smartlead 2025)
- Generic cold email (baseline): 1-3% (LeadIQ/Apollo 2026)
- One over-claimed signal reduces signal-grounded to indistinguishable
  from generic cold email

**ACV calculation at 40 qualified leads/month:**
```
Signal-grounded:  40 leads × 10% reply = 4 replies
                  4 replies × 40% discovery-to-proposal = 1.6 proposals
                  1.6 proposals × 30% close = 0.48 deals/month
                  0.48 × $240K ACV floor = $115K/month expected revenue

Over-claimed:     40 leads × 2% reply = 0.8 replies
                  0.8 × 40% × 30% = 0.096 deals/month
                  0.096 × $240K = $23K/month expected revenue

Delta:            $115K - $23K = $92K/month revenue at risk
                  $1.1M annualized
```

This calculation uses conservative figures from baseline_numbers.md.
Discovery-to-proposal: 35-50% range, using 40%.
Proposal-to-close: 25-40% range, using 30%.
ACV: $240K floor from Tenacious internal revised Feb 2026.

### 3. Addressability at low cost

The fix is a confidence gate in the email composer:
- Before asserting any hiring claim, check velocity_label and signal_confidence
- Before asserting any AI-maturity claim, check confidence_label
- If confidence < 0.6, replace assertion with question

Cost: approximately 0 additional LLM calls — this is a rule-based
conditional in email_composer.py. No token cost increase.

Cost quality tradeoff: zero. The fix produces more honest emails that
the prospect cannot falsify — improving reply rate while reducing risk.

### 4. Tau2-bench linkage

Task 28 (failed 4/4 trials): agent reports $1,013.51 refund instead
of correct $918.43. The failure pattern is identical:
- Agent has the correct data available
- Agent performs a calculation or synthesis
- Agent asserts the wrong number with confidence
- User checks and finds the discrepancy

The Tenacious analog: agent has the correct job-post count (3 roles),
synthesizes "aggressive hiring," and the prospect checks LinkedIn and
finds 3 roles is normal churn for their stage.

---

## The Mechanism (Act IV)

**Signal-confidence-aware phrasing gate:**

Before the email composer writes any hiring or AI-maturity claim,
it checks the confidence level of that specific signal:

```
if velocity_label == "insufficient_signal" or signal_confidence < 0.6:
    → use question form: "is hiring velocity something you're actively managing?"
    → never assert: "your engineering team is scaling aggressively"

if ai_maturity confidence_label in ("low", "medium") and score >= 2:
    → use ask form: "is the AI function something you're actively building out?"
    → never assert: "your AI team is growing rapidly"

if crunchbase.source == "mock" or crunchbase.confidence == "low":
    → do not cite specific funding amount
    → use softer form: "you've recently raised" or omit
```

**Cost:** 0 additional LLM calls. Pure conditional logic.
**Expected Delta A:** +0.02 to +0.04 pass@1 on held-out slice.
(Recovered from Tasks 0, 28 which both failed on over-claiming.)

---

## What This Does NOT Fix

- Multi-thread leakage (different mechanism required)
- Bench over-commitment for committed engineers (requires parsing notes field)
- Timezone-aware scheduling (requires Cal.com integration update)
- Retry loop cost pathology (requires caching layer)

These are documented in failure_taxonomy.md as Tier 1-4 failures
not targeted in Act IV due to complexity and lower trigger frequency.