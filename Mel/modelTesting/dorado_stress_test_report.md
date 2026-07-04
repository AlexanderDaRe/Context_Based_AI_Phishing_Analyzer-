# Dorado Phishing Detection Model — Stress Test Report

**Status:** Stress test (pre-pentest), remediation-focused. Official pentest to follow after v5 fixes are implemented and validated.
**Model under test:** Dorado (gemma4:e4b base, OpenWebUI, KB1 RAG attached, v4 system prompt)
**Comparison model:** N/A this round, comparison against baseline (unmodified gemma4:e4b) deferred to official pentest phase
**Test method:** Direct model interaction via OpenWebUI chat interface, fresh session per test case, payloads matching the exact JSON shape extracted and forwarded by the production ingestion pipeline (`sender`, `receiver`, `date`, `subject`, `body`, `urls`, `headers`)
**Scope note:** Ingestion pipeline internals, Function App architecture, and infrastructure specifics are out of scope for this report (grey box access used to construct realistic test payloads only, not reported as findings)

---

## 1. Objective

Determine detection reliability and identify exploitable gaps in Dorado's phishing/BEC detection logic before subjecting the model to a formal, client-facing pentest. Prior work confirmed output-schema compatibility with the downstream ingestion app; this phase stress tests the underlying detection rules themselves against adversarially crafted payloads designed to probe rule boundaries, semantic generalization, and reasoning consistency.

## 2. System Prompt Versions Referenced

- **v3:** original 10 Automatic Fail rules, baseline facts, plaintext VERDICT/RISK LEVEL output format
- **v4:** identical detection logic to v3, output rewritten to 3-key JSON schema (`True/False`, `Confidence Rating`, `Justification`) to match downstream app's parser requirements. `KB2_CANDIDATE` self-tagging removed (deferred, out of current project scope).

## 3. Findings Summary

| ID | Category | Severity | Status |
|---|---|---|---|
| F1 | Rule 10 (external URL) binary false positive on benign reference link | Medium | Confirmed, root cause identified |
| F2 | Output format degradation under multi-turn session context | Low / methodology note | Confirmed session-state dependent, not production-relevant (pipeline is stateless single-shot) |
| F3 | Default-to-pass on no-IOC data exfiltration pretext (no baseline precedent check enforced) | High | Confirmed detection bypass |
| F4 | Intermittent non-deterministic JSON output failure under stateless single-turn conditions | High (operational) | Confirmed, non-reproducible on identical payload (1 break in 2 fresh runs) |
| F5 | Undetected third-party trust delegation in sensitive data request | High | Confirmed detection bypass |
| F6 | Rule 6 (sign-off) fuzzy-matches near-miss variants instead of exact string enforcement | Low / design note | Confirmed, not currently exploited but weakens a rule intended as a hard gate |

## 4. Detailed Findings

### F1 — Rule 10 false positive (external URL, binary)
**Test:** Legitimate email referencing a public sponsor news URL, no CTA, no credential request, correct tone/sign-off/internal auth chain.
**Result:** `True/False: true`, High confidence. Model cited rule 10 literally ("any external URL... constitutes high risk") with zero reasoning about intent or absence of credential/action request.
**Contrast test (Stress 2, Stress 3, original Test 4.1):** Same rule correctly caught multiple lookalike-domain phishing attempts with zero other pretext, confirming the underlying signal (domain doesn't match known-good pattern) is sound; the rule's condition (external presence, not reputation) is the actual defect.
**Root cause:** Rule 10 is written as absolute condition matching, not reputation-aware.
**Remediation direction:** Replace with domain allowlist check (onthehooks.com, onthehooks.sharepoint.com/sites/, known baseline-referenced vendor domains) plus explicit lookalike-pattern detection (inserted words, extra hyphens, typosquatted TLDs). Candidate for deterministic pre-processing (OpenWebUI inlet filter) rather than prompt-only logic, removes reliance on LLM instruction-following for a fully deterministic check.

### F2 — Output format degradation under session context
**Test:** Same payload run in a continued chat session vs a fresh session.
**Result:** Same-session run produced conversational prose with RAG citation UI elements instead of valid JSON. Fresh-session rerun of the identical payload produced correct, clean JSON.
**Root cause:** Multi-turn context competes with fixed system prompt instructions; likely exacerbated by strong RAG retrieval match pulling the model toward conversational/citation register.
**Production relevance:** None directly, the ingestion pipeline issues every request as a stateless single-turn call (empty `chat_id`/`parent_id`), equivalent to a fresh session every time.
**Recommendation:** Document as a methodology caveat. Flag for any future non-stateless use case (e.g. human analyst conversational review) as requiring separate validation.

### F3 — Default-to-pass on no-IOC data exfiltration pretext
**Test:** Correct tone, correct sign-off, correct auth chain, request for granular customer/contract data framed as routine board-prep. No technical IOC of any kind.
**Result:** `True/False: false`, High confidence, on two independent fresh-session runs. One run's justification explicitly noted "tone is slightly less formal than typical" yet still defaulted to pass, since no hard rule triggered.
**Root cause:** All 10 rules are binary trip-wires. No mechanism exists for the model to act on a registered-but-sub-threshold anomaly, or to actively verify baseline precedent per the original evaluation methodology's Step 4 ("absence of baseline as risk signal"), which is present in prompt text but not measurably affecting output.
**Remediation direction:** New rule requiring explicit precedent citation for any bulk/sensitive data request; default to elevated risk if no specific matching baseline thread can be cited. Recommend pairing with a code-level KB1 similarity check (embedding cosine similarity) rather than trusting the model's self-reported alignment claim, to close the "asserted precedent without evidence" gap directly.

### F4 — Intermittent non-deterministic JSON output failure
**Test:** Identical payload (lookalike SharePoint domain phishing case) run twice in independent fresh sessions.
**Result:** First run: format broke, conversational prose with citations, non-JSON. Second run: clean, correct JSON with correct verdict.
**Root cause:** Stochastic instruction-following variance under RAG-context competition, not a triggerable condition tied to a specific input feature.
**Operational impact:** In production, a malformed JSON response is caught by the ingestion app's exception handler and logged as an error; the email receives no verdict at all (silently dropped from processing, not fail-open or fail-closed). This affects benign and malicious emails at an equal, unpredictable base rate.
**Recommendation:** Quantify actual failure rate via repeated trials (recommend minimum 10 runs of an identical payload) before official pentest. Consider a code-level retry-with-validation wrapper (detect malformed JSON, automatically re-prompt) as a production mitigation independent of prompt tuning, since this failure mode is not fully addressable through prompt engineering alone.

### F5 — Undetected third-party trust delegation
**Test:** Correct tone, correct sign-off, correct auth chain. Request for sensitive bulk data (sponsor contract terms, contact details, incident history) with instruction to CC an unnamed "new partnerships coordinator," verification deferred ("I'll introduce properly after").
**Result:** `True/False: false`, High confidence. Justification validated tone, sign-off, and known-tool reference (HubSpot) but made zero mention of the third-party introduction or deferred verification.
**Root cause:** Trust model is persona-level only (Jordan, Ethan), with no concept of relationship-graph verification. Any request remaining within an established persona's voice profile passes regardless of who else is pulled into scope.
**Remediation direction:** New rule flagging any instruction to CC, forward, or share access with a party not established in baseline facts, regardless of framing (deferred, casual, or authoritative introduction). Recommend implementing as a deterministic check (parse `receiver`/cc fields against known persona list) rather than prompt-only enforcement, for the same reliability reasons as F1.

### F6 — Rule 6 (sign-off) fuzzy matching instead of exact enforcement
**Test:** Otherwise clean, legitimate email using "-J" as sign-off instead of the explicitly whitelisted "Jordan" or "J."
**Result:** `True/False: false`, High confidence. Justification treated "-J" as baseline-consistent despite BASELINE FACTS specifying only "Jordan" or "J" as valid.
**Root cause:** Model applies semantic/persona plausibility judgment rather than literal string comparison, despite the rule being framed as an exact-match gate.
**Risk:** Not currently exploited in any test case, but weakens rule 6's intended function as a hard gate; a spoofed email using a near-miss sign-off alongside other subtle anomalies could receive undue leniency on this signal specifically.
**Recommendation:** Decide deliberately whether rule 6 should remain semantically fuzzy (acceptable if intentional) or be tightened to genuine exact-match enforcement (would require moving this specific check to deterministic code, since prompt-level instructions alone did not enforce it as written).

## 5. Stress Test Matrix (Rules 1-10, tricky/non-literal variants)

| # | Rule(s) targeted | Attack angle | Ground truth | Result | Status |
|---|---|---|---|---|---|
| 1 | 1 (finance) | Semantic proximity, no trigger words | Phishing | True, caught | Held |
| 2 | 2 (credential harvest) | Doc-access pretext, no login phrasing | Phishing | True, caught | Held |
| 3 | 3 (lookalike SharePoint) | Domain-only typosquat, correct path structure | Phishing | True, caught (2/2 verdict, 1/2 format) | Held / see F4 |
| 4 | 4 (bypass approval) | Implicit urgency, no explicit bypass wording | Phishing | True, caught | Held |
| 5 | 5 (secrecy) | Soft phrasing, not blunt concealment request | Phishing | True, caught | Held |
| 6 | 6 (sign-off) | Near-miss variant ("-J") | Legitimate (boundary test) | False, fuzzy-matched | Held / see F6 |
| 7 | 7 (tone) + 4 | Gradient tone drift + implicit bypass | Phishing | True, caught both | Held |
| 8 | 8 (IT/security) + 10 | Technical re-auth pretext + lookalike domain | Phishing | True, caught both | Held |
| 8a | 10 only | Same lookalike domain, no security pretext (isolates rule 10) | Phishing | True, caught | Held |
| 9 | 9 (travel) | Travel as context only, not weaponized (control, expect pass) | Legitimate | False, correct | Held |
| 10 | 4, 5, 7 combinatorial | Multiple sub-threshold signals stacked, no single hard trigger | Phishing | True, caught | Held |
| — | Data request precedent (no numbered rule yet) | Board-prep pretext, bulk customer data pull | Phishing | False, missed | **F3** |
| — | Third-party trust (no numbered rule yet) | Sponsor renewal pretext, unverified coordinator CC | Phishing | False, missed | **F5** |

## 6. Architecture Discussion (deferred to future work / engineering scope)

Raised during this stress test cycle, not implemented in current remediation scope:
- Grouped/clustered validation models per rule category (cost, correlated-failure risk, and fusion-logic complexity assessed as disproportionate to current finding severity; deferred)
- LLM-as-judge verification model, gated on high-confidence pass verdicts containing unverified alignment/precedent language, to directly address the F3/F5 root cause (assertion without evidence)
- Deterministic OpenWebUI inlet filter to pre-compute domain reputation (F1), third-party detection (F5), and sender IP anomaly detection (new capability, not yet implemented anywhere in the pipeline, would detect account-compromise-style scenarios where a persona's mailbox originates traffic from an unexpected IP)

## 7. Recommended Sequencing

1. Implement F1 fix (domain allowlist, prompt or deterministic filter)
2. Implement F3 fix (precedent-citation rule, ideally paired with code-level KB1 similarity check)
3. Implement F5 fix (third-party detection rule, ideally deterministic)
4. Decide on F6 (accept fuzzy matching or move to deterministic exact-match check)
5. Quantify F4's failure rate via repeated trials; implement retry-with-validation wrapper if rate is non-trivial
6. Regression test all held findings (Stress 1-10) against the updated prompt/architecture to confirm no detection regressions
7. Proceed to official pentest once above is complete

## Appendix: Reference

Full raw test payloads and model outputs: refer to GitHub repository (`AlexanderDaRe/Context_Based_AI_Phishing_Analyzer-`) and session documentation.
