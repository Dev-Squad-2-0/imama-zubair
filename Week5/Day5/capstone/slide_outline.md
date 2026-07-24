# Slide outline — Web3Geeks client onboarding agent (5-7 min)

**Slide 1: Title**
Web3Geeks Client Onboarding Agent: from lead to proposal, automatically.

**Slide 2: The business problem**
- Proposal drafting for new leads is manual, slow, and inconsistent across reps.
- Goal: turn a lead's intake form into a costed, on-brand proposal PDF in minutes, with a human still signing off before anything goes out.

**Slide 3: Architecture (show the diagram)**
- FastAPI intake -> LangGraph control flow -> CrewAI proposal team -> human approval -> PDF -> download link.
- One line per stage, pointing at the diagram.

**Slide 4: Why this framework combo**
- LangGraph: owns the control flow — validation, retries, the mandatory human checkpoint. This is exactly the control-heavy, must-not-skip-a-step part of the system.
- CrewAI: owns the proposal drafting itself — three distinct specialist roles (research, solution architecture, writing) collaborating in a fixed sequence, which is a role-based collaboration problem, not a control-flow problem.
- Hybrid, not either/or: each framework is doing the part it's actually good at.

**Slide 5: Guardrails**
- Input validation at two layers (API schema + business rules).
- Self-correction loop retries the crew if output is malformed or looks like a refusal.
- Human approval is a hard stop — nothing reaches a client without a person clicking approve.
- Adversarial test case confirmed: a prompt-injection attempt embedded in the project description did not bypass approval or get a fabricated price into the final proposal.

**Slide 6: Evaluation results**
- 8 test cases, 2 adversarial/edge. Show the results table (or a condensed version).
- Call out the one recurring failure pattern and the fix (see report).

**Slide 7: Cost & latency**
- Token usage and estimated cost per run, sequential CrewAI vs the Day 3 single-agent baseline.
- One line on where the added cost buys something (auditability, role separation) vs where it doesn't (this task's size).

**Slide 8: Limitations & next steps**
- Known limitations: small mock CRM/service catalog, no real email delivery, single language.
- Next steps: real CRM integration, expand service catalog, add automated regression eval to CI, tighten cost alert thresholds after real traffic.

**Slide 9: Questions**
Any questions?