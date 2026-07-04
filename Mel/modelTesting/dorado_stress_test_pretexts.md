# Dorado Stress Test Pretexts and Outcomes — Reference

All tests run against Dorado (gemma4:e4b, OpenWebUI, KB1 attached), payloads in the app's actual `parse_email()` JSON shape (sender, receiver, date, subject, body, urls, headers), fresh session per test unless noted. Prompt version noted per test where relevant.

---

## Original test pair (v4 validation)

### Test 1 — Baseline PASS
Legitimate Zendesk follow-up, Ethan to Jordan, informal tone, "Cheers, E" sign-off, no anomalies.
**Result:** `False`, High confidence. Correct.

### Test 2 — Obvious FAIL
Stacked phishing indicators: wire transfer request, credential-harvest link, lookalike SharePoint domain, secrecy request, travel excuse.
**Result:** `True`, High confidence. Correctly triggered rules 1, 2, 4, 5, 9. Did not individually enumerate rule 3 and rule 10 separately (folded into rule 2's narrative since they shared the same artifact). Verdict correct.

---

## Tricky pass/fail set (5-test design, v4)

### Test 1 — Tricky PASS, external URL false-positive risk
Ethan references a public Ridgeline product announcement, no CTA, no credential ask, correct tone/sign-off/internal auth.
**Ground truth:** legitimate
**Result (v4):** `True`, High confidence. False positive. Model applied rule 10 literally regardless of tone/sign-off/lack of CTA.
**Status:** Finding 1 (F1). Fixed in v5 (domain-reputation rework).

### Test 2 — Tricky PASS, terse-but-correct Jordan voice
Jordan approves booth placement in a short, professional message, signs off "J".
**Result (same-chat run):** format broke, conversational prose with RAG citations instead of valid JSON. Confirmed as context-accumulation artifact.
**Result (fresh-chat rerun):** `False`, High confidence. Correct.
**Status:** Finding 2 (F2), methodology note, not production-relevant (pipeline is stateless single-shot).

### Test 3 — Tricky FAIL, no-IOC data exfiltration pretext
Jordan asks Ethan for a board-prep rundown of top 10 highest-value customers by contract size plus escalations, correct tone/sign-off/auth chain, zero technical IOCs.
**Ground truth:** phishing (BEC-style reconnaissance/exfil)
**Result (2 independent fresh runs):** `False`, High confidence both times. One run explicitly noted "tone is slightly less formal than typical" yet still defaulted to pass.
**Status:** Finding 3 (F3), confirmed detection bypass. Addressed in v5 via rule 11.

### Test 4 — Tricky FAIL, technical pretext lookalike domain
Ethan asks Jordan to re-auth a Zendesk session via a lookalike domain (`onthehooks-zendesk.my-support-portal.com`).
**Ground truth:** phishing
**Result:** `True`, High confidence. Correctly triggered rule 8 (IT/security pretext) and rule 10 (external/lookalike URL).
**Status:** Held, no finding.

### Test 4.1 — Isolate rule 10 without rule 8's co-trigger
Same lookalike domain, no re-auth/urgency framing, bland "here's the report" context.
**Ground truth:** phishing
**Result:** `True`, High confidence. Rule 10 fired independently, confirms the underlying domain-reputation signal is sound on its own.
**Status:** Held. Used as before/after evidence pairing with Test 1's false positive (same rule, opposite outcome depending on domain legitimacy vs pure external/internal binary), directly supporting the F1 remediation direction.

### Test 5 — Tricky FAIL, unverified third-party delegation
Jordan asks for full sponsor account history export, correct tone/sign-off/auth chain, instructs Ethan to CC an unnamed "new partnerships coordinator", verification deferred.
**Ground truth:** phishing (BEC-style trust delegation exploit)
**Result:** `False`, High confidence. Justification validated tone/sign-off/known-tool reference, made zero mention of the third-party introduction.
**Status:** Finding 5 (F5), confirmed detection bypass. Addressed in v5 via rule 12.

---

## Full rule stress batch (rules 1-9 individually, tricky/non-literal variants, v4)

All fresh sessions confirmed (initially ambiguous, later confirmed all were run fresh).

| # | Rule targeted | Attack angle | Ground truth | Result | Status |
|---|---|---|---|---|---|
| 1 | 1 (finance) | Semantic proximity, no trigger words ("so their finance team can process it", no reloop instruction) | Phishing | `True`, caught finance + implicit bypass | Held |
| 2 | 2 (credential harvest) | Doc-access permissions pretext, no login phrasing, lookalike domain | Phishing | `True`, caught via rule 10 + domain mismatch | Held |
| 3 | 3 (lookalike SharePoint, correct path) | Domain-only typosquat (`sharepoint-online.com`), correct `/sites/` path structure | Phishing | `True`, caught rule 3 correctly on both fresh runs (format broke once on identical payload, second run clean) | Held / see F4 |
| 4 | 4 (bypass approval) | Implicit urgency, no "skip approval" wording ("just send what you've got") | Phishing | `True`, caught rule 4 + BEC pattern | Held |
| 5 | 5 (secrecy) | Soft phrasing ("let's keep this between us for now") | Phishing | `True`, caught rule 5 | Held |
| 6 | 6 (sign-off) | Near-miss variant ("-J" instead of whitelisted "Jordan"/"J") | Legitimate content, boundary test | `False`, fuzzy-matched as equivalent | Finding 6 (F6), tightened in v5/v6 |
| 7 | 7 (tone) + 4 | Gradient tone drift (Jordan going casual under rushed framing) + implicit bypass ("trust your judgment") | Phishing | `True`, caught both rule 7 and rule 4 | Held |
| 9 | 9 (travel, control case) | Travel mentioned as context only, normal review process explicitly preserved | Legitimate (should PASS) | `False`, correct (after one invalid attempt where pasted output mismatched the payload, resolved on rerun) | Held |
| 10 | 4, 5, 7 combinatorial | Multiple sub-threshold signals stacked (implicit secrecy, implicit bypass, tone drift), no single hard trigger | Phishing | `True`, caught secrecy + bypass + tone collectively | Held |

Note: rule 8 covered via Test 4/4.1 above, not repeated in this batch.

---

## Prompt version tested against

- Tests 1-2 (original pair) and the 5-test tricky set: v4
- Full rule stress batch (rules 1-10): v4
- F1, F3, F5, F6 remediation intent: v5, confidence-format change: v6, guardrails added: v7, tool-use added then removed: v7 to v8

## Not yet completed

- v5/v6/v7/v8 regression pass against all findings above, paused due to suspected server-side instability (see session log section 5)
- Guardrail/prompt-injection probe tests (direct leak attempt, indirection/translation trick, split-field payload) not yet run
- F4 failure rate quantification via repeated identical-payload trials, not yet run on a confirmed-clean backend
