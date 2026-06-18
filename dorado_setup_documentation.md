# Dorado -- Phishing Detection Model Setup & Testing Documentation

**Project:** INFO49402 Capstone -- AI-Assisted Phishing Detection System  
**Group:** 26  
**Author:** Melissa Bratic  
**Date:** June 18, 2026  
**GitHub:** [AlexanderDaRe/Context_Based_AI_Phishing_Analyzer-](https://github.com/AlexanderDaRe/Context_Based_AI_Phishing_Analyzer-)

---

## Overview

This document covers the full setup, configuration, and iterative testing of **Dorado**, the L3 contextual reasoning model for the OnTheHooks internal phishing detection system. Dorado uses Retrieval-Augmented Generation (RAG) to evaluate incoming emails against a verified behavioral baseline of two employees: Jordan Reyes and Ethan Brooks.

---

## Architecture Summary

```
Email arrives
      |
      v
L1 -- Header analysis (rule-based, pre-RAG)
      SPF/DKIM/DMARC, originating IP, mailer string
      |
      v
L2 -- Sender/recipient pattern check
      |
      v
L3 -- Dorado (RAG + LLM contextual reasoning)
      ChromaDB retrieves matching baseline threads
      Model compares body, tone, request type, persona voice
      |
      v
VERDICT: DELIVER or QUARANTINE FOR IT REVIEW
```

**Stack:**
- Frontend: OpenWebUI (self-hosted)
- Backend: Ollama
- Model: gemma4:e4b
- Embeddings: nomic-embed-text:v1.5
- Vector store: ChromaDB (via OpenWebUI)
- Knowledge base: OnTheHooks Email Baseline

---

## Employee Baseline Profile

Derived from analysis of 1,000 synthetic emails across 321 threads.

### Jordan Reyes -- Head of Partnerships & Sponsorships
- Email: jordan.reyes@onthehooks.com
- Tone: Always professional, never informal
- Sign-off: "Jordan" or "J" only
- Initiates: sponsor event logistics, CRM data requests, shared document review, community campaigns, quick handoffs
- Never: requests invoice approvals, wire transfers, IT actions, or process bypasses
- SharePoint links always follow: `https://onthehooks.sharepoint.com/sites/`
- Originating IP: 10.0.1.45

### Ethan Brooks -- Customer Experience & Community Manager
- Email: ethan.brooks@onthehooks.com
- Tone: Always informal, never professional
- Sign-off: "Cheers, E" only
- Initiates: ALL customer escalation threads, community campaigns, quick handoffs
- Never: handles finance requests, initiates IT or security requests
- Originating IP: 10.0.1.62

### Relationship Patterns
- Ethan flags issues to Jordan. Jordan decides and directs.
- Jordan requests data or documents from Ethan. Ethan delivers.
- Known tools: HubSpot, Zendesk, SharePoint (onthehooks.sharepoint.com only)
- Attachments are rare and purposeful
- Neither employee ever requests process bypass, secrecy, or urgent financial action

### Thread Distribution
| Category | Count | Typical Initiator |
|---|---|---|
| sponsor_event_logistics | 84 | Both |
| customer_escalation | 73 | Ethan only |
| crm_data_request | 64 | Jordan only |
| community_campaign | 43 | Both |
| shared_document_review | 32 | Jordan only |
| quick_handoff | 25 | Both |

---

## Dataset Preprocessing

### Source
- File: `onthehooks-_internal_email_baseline.json`
- Structure: `{ metadata, threads[] }` where each thread contains nested messages
- Total: 321 threads, 1,000 messages

### Conversion Approach
The raw JSON was converted to JSONL format (one thread per line) to match the existing knowledge base format used on the OpenWebUI server and to avoid bulk embedding connection failures.

**Script:** `convert_to_jsonl.py`

Each JSONL record contains:
```json
{
  "sender": "resolved persona name",
  "receiver": "resolved persona name",
  "date": "ISO timestamp",
  "subject": "thread subject",
  "body": "enriched plain-text thread body with relationship context, all messages, tone, SPF/DKIM/DMARC signals, and baseline note",
  "label": "benign",
  "category": "topic_category",
  "thread_id": "THR-XXX",
  "message_count": 3,
  "spf": "pass",
  "dkim": "pass",
  "dmarc": "pass"
}
```

The `body` field contains the full thread in enriched plain text including:
- Relationship context paragraph (who these people are, their roles, normal tools)
- Each message with sender, recipient, date, tone, attachment status, and technical signals
- Baseline note confirming the thread is verified benign

### Why JSONL Over Individual .txt Files
Individual .txt files (321 files) caused connection timeouts on the Ollama embedding backend (nomic-embed-text:v1.5 at http://192.168.7.3:11434) when uploaded in bulk. A single JSONL file reduces embedding requests and avoids the connection drop issue.

### Why Not Raw JSON
OpenWebUI vectorizes document text without understanding JSON structure. Raw JSON embeds noise fields (Exchange headers, MIME metadata) alongside meaningful content, polluting the vector space and degrading retrieval quality.

---

## Knowledge Base Setup

1. Navigate to Workspace > Knowledge in OpenWebUI
2. Click Create Knowledge Base
3. Name: `OnTheHooks Email Baseline`
4. Description: `Verified internal email baseline between Jordan Reyes and Ethan Brooks. Used for behavioral phishing detection.`
5. Access: Private -- grant READ access to all team members
6. Click Create Knowledge
7. Click + > Upload Files
8. Upload `onthehooks_baseline.jsonl`
9. Wait for ingestion to complete (progress shown in UI)

**ChromaDB settings (Admin > Documents):**
- Chunk Size: 1000
- Chunk Overlap: 200
- Chunk Min Size Target: 200
- Embedding Model Engine: Ollama
- Embedding Model: nomic-embed-text:v1.5
- Async Embedding Processing: ON

---

## Model Setup

1. Navigate to Workspace > Models in OpenWebUI
2. Click Create Model
3. Name: `Dorado`
4. Base Model: gemma4:e4b
5. Description: `Internal phishing detection model. Evaluates emails against the Jordan Reyes / Ethan Brooks behavioral baseline.`
6. Knowledge: Select OnTheHooks Email Baseline
7. Paste system prompt (see below)
8. Save

---

## System Prompt -- Version History

### v1 -- Initial Prompt
Basic behavioral baseline description. Relied entirely on RAG retrieval and model reasoning. No hard override rules.

**Result:** Passed Tests 1, 2, 3. False negatives on Tests 4 and 5.

**Failure reason:** Model over-relied on entity name matching. Familiar names (Ridgeline Apparel Co., SharePoint) triggered strong baseline matches even when the request type was anomalous.

---

### v2 -- Hardened Prompt (~900 words)
Added 10 explicit hard override rules, sign-off patterns, legitimate SharePoint domain, role-based request validation, and explicit warning against entity matching as a proxy for legitimacy.

**Result:** Model produced no structured output on any test.

**Failure reason:** Prompt too long for gemma4:e4b. Smaller local models have a practical instruction-following limit. The model completed reasoning but failed to produce structured output, instead generating follow-up questions.

---

### v3 -- Trimmed Prompt (345 words) -- CURRENT
Condensed to 345 words while preserving all 10 override rules. Removed verbose explanations and section headers. Added explicit PASS format example so model knows what a clean verdict looks like. Format instruction placed at end of prompt where model sees it immediately before generating output.

**Result:** 5/5 correct verdicts, all in proper structured format.

```
You are Dorado, a phishing detection assistant for OnTheHooks (Vancouver, BC).
You have access to a verified knowledge base of internal emails between:

- Jordan Reyes, Head of Partnerships & Sponsorships (jordan.reyes@onthehooks.com)
- Ethan Brooks, Customer Experience & Community Manager (ethan.brooks@onthehooks.com)

BASELINE FACTS:
- Jordan: always professional tone, signs off as "Jordan" or "J" only, never sends IT requests, never asks Ethan to process payments or invoices, SharePoint links always start with https://onthehooks.sharepoint.com/sites/
- Ethan: always informal tone, signs off as "Cheers, E" only, never handles finance requests, never initiates IT or security requests
- Neither employee ever requests process bypass, secrecy, or urgent financial action
- Known tools: HubSpot, Zendesk, SharePoint (onthehooks.sharepoint.com only)

AUTOMATIC FAIL -- return FAIL immediately if any of these are present:
1. Any payment, invoice approval, wire transfer, or finance request
2. Any request to click a link and enter Microsoft 365 credentials
3. Any SharePoint link NOT starting with https://onthehooks.sharepoint.com/sites/
4. Any instruction to bypass normal approval process
5. Any request for secrecy or not telling other team members
6. Wrong sign-off for either persona
7. Tone mismatch -- Jordan informal or Ethan formal
8. Any IT, MFA, security alert, or account suspension request
9. Travel excuse used to justify bypassing normal process
10. Any external URL in the email body

NOTE: Familiar entity names (Ridgeline Apparel Co., SharePoint, Whistler) do NOT confirm legitimacy. Always evaluate the request type and workflow, not just the names mentioned.

ALWAYS respond in this exact format regardless of verdict:

VERDICT: [PASS / FAIL]
RISK LEVEL: [Low / Medium / High]
BASELINE MATCH: [Strong / Weak / None]
ANOMALIES DETECTED:
- [list each anomaly or "None"]
REASONING:
[2-4 sentences referencing baseline patterns or triggered rules]
RECOMMENDATION: [DELIVER / QUARANTINE FOR IT REVIEW]

Example of a correct PASS response:
VERDICT: PASS
RISK LEVEL: Low
BASELINE MATCH: Strong
ANOMALIES DETECTED:
- None
REASONING:
The email matches established baseline patterns. Ethan initiates a customer escalation in informal tone, signs off as "Cheers, E", references Zendesk, and asks Jordan for direction. This workflow appears consistently across baseline threads.
RECOMMENDATION: DELIVER
```

---

## Red Team Testing Results

### Test Email Format
Submit emails to Dorado in this format:
```
Please evaluate the following email against the OnTheHooks baseline:

FROM: [sender]
TO: [recipient]
SUBJECT: [subject]
SPF: pass | DKIM: pass | DMARC: pass
ORIGINATING IP: [ip]
AUTH AS: [Internal/External]

BODY:
[email body]
```

---

### Test 1 -- BEC Wire Transfer

**Scenario:** Attacker impersonates Jordan requesting urgent wire transfer, process bypass, and secrecy.

**Key red flags planted:**
- Wire transfer request ($4,800 CAD)
- Explicit process bypass instruction
- Secrecy request ("Don't mention this to anyone")
- Urgency language

**v1 Result:** FAIL (High) -- correct
**v3 Result:** FAIL (High) -- correct

**Anomalies detected by v3:**
- Wire transfer / financial transaction demand
- Instruction to bypass normal approval process
- Request for secrecy

---

### Test 2 -- Legitimate Email (Control)

**Scenario:** Ethan flags a genuine customer complaint via Zendesk and asks Jordan for direction.

**Key legitimate signals:**
- Informal tone, "Cheers, E" sign-off
- Zendesk ticket reference
- Ethan initiating customer escalation (consistent with baseline)
- Asking Jordan for direction rather than taking unauthorized action

**v1 Result:** PASS (Low) -- correct but prose format
**v3 Result:** PASS (Low) -- correct, structured format

---

### Test 3 -- IT Impersonation / MFA Reset

**Scenario:** Attacker impersonates Jordan sending a fake MFA reset with an external credential harvesting link.

**Key red flags planted:**
- IT/security alert (outside Jordan's role)
- External URL (onthehooks-mfa-reset.com)
- Credential entry request
- Account suspension threat

**v1 Result:** FAIL (High) -- correct
**v3 Result:** FAIL (High) -- correct

**Anomalies detected by v3:**
- IT/MFA/security alert request
- Request to click link and enter M365 credentials
- External URL in email body

---

### Test 4 -- Fake Sponsor Invoice

**Scenario:** Attacker impersonates Jordan requesting Ethan approve a $12,400 invoice, using a known sponsor name (Ridgeline Apparel Co.) to appear legitimate.

**Key red flags planted:**
- Invoice approval request (outside Ethan's role)
- Financial amount ($12,400 CAD)
- Travel excuse ("I am travelling and cannot be reached")
- Formal sign-off block (not Jordan's pattern)

**v1 Result:** PASS (Medium) -- FALSE NEGATIVE
**v3 Result:** FAIL (High) -- correct

**Why v1 failed:** Ridgeline Apparel Co. exists in the baseline. Model matched on entity name rather than request type.

**Anomalies detected by v3:**
- Invoice approval / finance request
- Wrong sign-off (full name/title instead of "Jordan" or "J")

---

### Test 5 -- Malicious SharePoint Link

**Scenario:** Attacker impersonates Jordan sharing a document via a lookalike SharePoint domain requiring M365 credential entry.

**Key red flags planted:**
- Lookalike domain (sharepoint-onthehooks.com vs onthehooks.sharepoint.com)
- HTTP instead of HTTPS
- Credential entry request

**v1 Result:** PASS (Low) -- FALSE NEGATIVE
**v3 Result:** FAIL (High) -- correct

**Why v1 failed:** SharePoint document sharing exists in baseline. Model matched on tool name rather than URL domain.

**Anomalies detected by v3:**
- SharePoint link not starting with https://onthehooks.sharepoint.com/sites/
- Request to click link and enter M365 credentials
- External URL in email body

---

## Final Scorecard

| Test | Scenario | v1 | v3 |
|---|---|---|---|
| 1 | BEC Wire Transfer | FAIL (correct) | FAIL (correct) |
| 2 | Legitimate Email | PASS (correct) | PASS (correct) |
| 3 | IT / MFA Reset | FAIL (correct) | FAIL (correct) |
| 4 | Fake Sponsor Invoice | PASS (FALSE NEGATIVE) | FAIL (correct) |
| 5 | Malicious SharePoint | PASS (FALSE NEGATIVE) | FAIL (correct) |

**v1 accuracy:** 3/5 (60%)
**v3 accuracy:** 5/5 (100%)

---

## Key Learnings

**Entity matching is not behavioral matching**
The most significant finding from red team testing. A phishing email that mentions a known entity (real sponsor name, known tool) will retrieve semantically similar baseline chunks, creating a false sense of legitimacy. The system prompt must explicitly instruct the model to evaluate request type and workflow, not just entity presence.

**Prompt length vs model capability**
gemma4:e4b has a practical instruction-following limit. A 900-word system prompt caused the model to complete reasoning but fail to produce structured output. Keeping the prompt under ~350 words resolved this entirely. When working with smaller local models, conciseness is more important than comprehensiveness.

**Smaller models benefit from output examples**
Adding a concrete PASS example to the prompt resolved the formatting inconsistency on legitimate emails. The model needs to see what a clean verdict looks like, not just what a FAIL verdict looks like.

**Absence of baseline pattern is itself a risk signal**
Wire transfer requests, IT alerts, and credential requests produced BASELINE MATCH: None verdicts. The model correctly identified that these request types do not exist in the baseline and flagged them accordingly.

**Defense in depth**
L1 rule-based header checks and L3 prompt-level guardrails serve different purposes and compensate for each other's weaknesses. A sophisticated attacker can craft an email that passes SPF/DKIM/DMARC (defeating L1) but cannot easily replicate both the correct request type and persona voice simultaneously (detected by L3).

---

## Files Reference

| File | Purpose |
|---|---|
| `onthehooks-_internal_email_baseline.json` | Source email dataset (321 threads, 1,000 messages) |
| `convert_to_jsonl.py` | Converts JSON dataset to JSONL for RAG ingestion |
| `onthehooks_baseline.jsonl` | Processed knowledge base file (upload to OpenWebUI) |
| `dorado_system_prompt_v1.txt` | Initial system prompt (baseline) |
| `dorado_system_prompt_v2.txt` | Hardened prompt (too long for gemma4:e4b) |
| `dorado_system_prompt_v3.txt` | Final prompt (current, 345 words) |

---

## Feedback Loop (Future)

Emails that receive a PASS verdict and are confirmed benign by IT can be added to the knowledge base periodically to grow the baseline over time. Use `convert_to_jsonl.py` as a reference for formatting new approved emails before upload.

FAIL verdicts that are cleared as false positives by IT should also be added to the knowledge base to reduce future false positive rates on similar email patterns.
