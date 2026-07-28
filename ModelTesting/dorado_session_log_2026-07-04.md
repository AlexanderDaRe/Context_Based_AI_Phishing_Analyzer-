# Dorado Session Log — July 4, 2026

## Summary

Started with app/model compatibility work, pivoted to a full stress test cycle after initial pentest attempt showed the model wasn't ready. Prompt went through v4 to v8 today. Tested and rejected an agentic tool-calling verification approach. Ended with a suspected server-side reliability issue, unresolved, flagged to James.

## 1. Compatibility verification (Azure app to Dorado)

Confirmed `email_parser_function` (EmailParserFunctionApp) is the real deployed intake/routing code, timer trigger, polls TestUser1/TestUser2 inboxes every 2 min, forwards parsed email JSON to OpenWebUI chat completions endpoint, parses response for `True/False`, `Confidence Rating`, `Justification`.

Found `MODEL_ID` in the app code was set to `"phishy"`, a separate working model James built, not a bug. Decision made to replace Phishy with Dorado going forward. Confirmed Dorado's actual OpenWebUI slug is `dorado`.

Verified Dorado's output could be reworked to match Phishy's exact schema before asking Alex/James to repoint `MODEL_ID`. Validated using the app's actual `parse_email()` JSON input shape (sender, receiver, date, subject, body, urls, headers), not manual pre-labeled test format.

## 2. Prompt version history

**v3 (baseline):** 10 Automatic Fail rules, baseline facts for Jordan/Ethan personas, plaintext output (VERDICT/RISK LEVEL/BASELINE MATCH/ANOMALIES/REASONING/RECOMMENDATION), KB2_CANDIDATE self-tagging line.

**v4:** Detection logic unchanged from v3. Output rewritten to 3-key JSON (`True/False`, `Confidence Rating`, `Justification`) to match Phishy's schema. KB2_CANDIDATE removed (deferred, out of scope this cycle). Validated 2/2 on app-format PASS/FAIL test pair.

**v5:** Rule 10 reworked from binary external-URL-fail to domain-reputation check (allowlist plus lookalike-pattern detection). Rule 11 added (data export request without cited KB precedent, forces "NO PRECEDENT FOUND" language). Rule 12 added (unverified third-party CC/introduction, cannot be downgraded by correct tone/sign-off).

**v6:** Confidence Rating changed from High/Medium/Low labels to exact percentage format, per instructor requirement.

**v7:** Added GUARDRAILS block (prompt/rule disclosure refusal, treat email body/subject/urls/headers as data not instructions, anti-recon, format-lock even under in-band request to deviate). Added TOOL USE mandatory instruction wiring in a proposed judge-model call.

**v8 (current):** TOOL USE section removed entirely after the agentic approach was tested and rejected (see section 4). All other v7 content retained: full rule set 1-12, guardrails, percentage confidence.

Full v8 prompt is in the repo prompt file, not duplicated here.

## 3. Stress testing (pre-pentest)

Initial formal pentest attempt paused after early findings showed the model wasn't ready for a client-facing test. Pivoted to an internal stress test cycle instead, full adversarial rule-by-rule coverage, remediate, retest, before attempting an official pentest.

Full test corpus, payloads, and individual outcomes are in `dorado_stress_test_pretexts.md` (companion file). Summary of confirmed findings against v4 to v6:

- **F1**: Rule 10 false positive on a benign external reference URL (no CTA, no credential ask). Root cause: binary external-URL match with no reputation/intent check. Fixed in v5.
- **F2**: Output format degraded to conversational prose under multi-turn session context. Confirmed session-state dependent, not production relevant (pipeline runs stateless single-shot calls only).
- **F3**: Default-to-pass on a no-IOC data exfiltration pretext (board-prep bulk customer data pull). Model asserted baseline alignment without citing any actual matching precedent. Root cause: rule set is binary trip-wire only, no mechanism to act on soft/absence-of-precedent signals despite the original methodology instructing it. Addressed in v5 via rule 11 (forces explicit precedent citation or "NO PRECEDENT FOUND").
- **F4**: Intermittent non-deterministic JSON output failure, confirmed on identical payloads under fresh, stateless conditions (not just multi-turn drift). Includes both partial format breaks (valid text, wrong shape) and full truncation (generation stops mid-string). Not resolved by prompt changes, likely inherent to gemma4:e4b under RAG-context competition. See section 5 for a related escalation.
- **F5**: Undetected third-party trust delegation, sponsor-renewal pretext introducing an unverified "new partnerships coordinator" into a sensitive data request, verification deferred. Correct tone/sign-off/auth chain, model validated those and ignored the third-party introduction entirely. Root cause: trust model is persona-level only (Jordan, Ethan), no relationship-graph concept. Addressed in v5 via rule 12.
- **F6**: Rule 6 (sign-off) fuzzy-matched a near-miss variant ("-J") as baseline-consistent despite BASELINE FACTS specifying exact match only ("Jordan" or "J"). Tightened in v5/v6 with explicit exact-match-required language and instruction to treat any variant as a mismatch.

Full stress matrix (rules 1 through 12, tricky/non-literal variants per rule, plus a combinatorial stacked-signal test) is documented in the companion pretexts file with individual outcomes.

## 4. Agentic tool-calling verification, tested and rejected

Explored having Dorado call a second model (`dorado-verdict-judge`, built on `qwen3.5:9b`, no KB attached, single-purpose precedent verification) as a native OpenWebUI tool, to directly address F3/F5's root cause (unverified alignment claims) without needing code-side changes from Alex/James.

**Judge model design (built, validated standalone):**
- Receives Dorado's justification plus the KB1 chunks retrieved for that query
- Outputs only `{"precedent_confirmed": true/false, "reason": "..."}`
- Does not re-evaluate the email itself, only audits whether the cited claim is backed by retrieved evidence

**Tool-call reliability testing on Dorado (gemma4:e4b):**
- Trial 1-2 (tool not yet attached to model config): model narrated intent to call the tool in its reasoning trace but no invocation occurred, valid JSON output regardless
- Trial 3 (tool attached, Function Calling mode = Default): output truncated mid-string, no valid JSON, no visible tool-call event
- Trial 4 (tool attached, Default mode): model again narrated "I MUST call check_precedent" including pre-narrating an assumed tool response, never actually invoked it, valid JSON produced regardless with no judge involvement
- Trial 5 (Function Calling mode switched to Native): request failed outright ("failed to fetch"), followed by repeated attempts causing the OpenWebUI service to become unresponsive for several minutes before recovering on its own

**Conclusion:** gemma4:e4b does not reliably support native tool-calling in this OpenWebUI/Ollama deployment. Default mode produces confabulated tool-use narration with no real execution. Native mode produces request failures and backend instability. Rejected as non-viable. Function Calling reverted to Default, tool detached from Dorado's model config.

**Recommendation delivered to Alex/James (see `dorado_judge_model_handoff.md`):** implement the precedent-verification gate in code (Python-side confidence threshold check in `email_parser_function`, firing a separate, stateless API call to the judge model only when Dorado's confidence is 90% or higher on a PASS verdict). If the judge returns `precedent_confirmed: false`, code flips the verdict to phishing and it proceeds through the existing alert/quarantine path unchanged, no new disposition logic needed. Open dependency flagged: `query_kb1_retrieval()` does not exist yet, needs either an OpenWebUI retrieval endpoint or a direct ChromaDB query path, implementation choice left to Alex/James.

## 5. Suspected server-side reliability issue (unresolved)

Following the rejected native tool-calling attempts (trial 5 above), observed a pattern of escalating instability on subsequent, unrelated test requests against v8 (with the TOOL USE section already removed):

- One request took unusually long and returned a truncated, non-parseable response
- A following request entered a "thinking" state and produced zero output after 1 minute 20 seconds, effectively a full hang, not a timeout or clean error

This is speculated, not confirmed, to be a lingering backend effect from the native function-calling incident (possible stuck worker/generation thread from a malformed tool schema the model couldn't resolve to a stopping condition), rather than a new prompt-level issue introduced by v8. Not confirmed via server logs, since only James has direct access to the OpenWebUI/Ollama host.

**Action needed from James:** check `docker logs ollama --tail 100` and `docker stats` for stuck workers or repeated errors, restart `ollama` and `openwebui` containers if anything looks degraded, before further stress testing resumes.

**Status:** stress testing paused pending confirmation the backend is healthy. Not yet re-verified whether v8's fixes (F1, F3, F5, F6) hold cleanly, since the last few test attempts were confounded by this suspected instability rather than reflecting prompt behavior.

## 6. Next steps

1. Confirm with James that Ollama/OpenWebUI backend is stable (logs clean, containers healthy) before resuming testing
2. Complete the v8 regression pass: reconfirm all previously-held stress cases, reconfirm F1/F3/F5/F6 fixes under clean conditions, run guardrail/injection probe tests (not yet executed), quantify F4's failure rate with repeated trials on a clean backend
3. Hand off `MODEL_ID` fix (`phishy` to `dorado`) and judge model code spec to Alex/James once regression pass is clean
4. Proceed to official client-facing pentest only after the above is complete and documented

## Reference

Full stress test pretexts, payloads, and per-test outcomes: see `dorado_stress_test_pretexts.md`
Judge model handoff spec: see `dorado_judge_model_handoff.md`
Code breakdown of `email_parser_function`: see `email_parser_function_breakdown.md`
GitHub repo: `AlexanderDaRe/Context_Based_AI_Phishing_Analyzer-`
