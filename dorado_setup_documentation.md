# Dorado: L3 Contextual Phishing Detection Model
## Full Setup, Configuration, and Red Team Testing Log

**Project:** INFO49402 Capstone -- AI-Assisted Phishing Detection System
**Group:** 26
**Author:** Melissa Bratic
**Date:** June 18, 2026
**GitHub:** https://github.com/AlexanderDaRe/Context_Based_AI_Phishing_Analyzer-

---

## What This Document Covers

This document is a full walkthrough of everything done during the Dorado setup and testing session. It covers the reasoning behind every decision, what failed and why, what worked and why, and the exact steps taken in order. Anyone reading this should be able to replicate the entire process from scratch.

---

## System Architecture

The phishing detection system is built in three layers:

```
Email arrives
      |
      v
L1 -- Header analysis (rule-based, no LLM)
      Checks: SPF/DKIM/DMARC pass/fail, originating IP,
              mailer string, known malicious domains
      Fast, deterministic, runs on every email
      |
      v (only emails that pass L1 continue)
      |
L2 -- Sender/recipient pattern check
      |
      v
L3 -- Dorado (RAG + LLM contextual reasoning)
      ChromaDB retrieves semantically similar baseline threads
      Model compares tone, request type, persona voice, workflow
      Returns structured verdict
      |
      v
VERDICT: DELIVER or QUARANTINE FOR IT REVIEW
```

L1 catches technically malformed emails cheaply and quickly. L3 (Dorado) catches socially engineered emails that pass all technical checks -- the dangerous ones. Both layers are necessary because a sophisticated attacker can register a lookalike domain that passes SPF/DKIM/DMARC, defeating L1 entirely. L3 detects these by comparing behavioral patterns against the baseline regardless of technical signal results.

This is a defense-in-depth architecture. Each layer compensates for the other's blind spots.

**Full Stack:**
- Frontend / RAG interface: OpenWebUI (self-hosted at openui.evil-friends.com)
- LLM backend: Ollama
- Detection model: gemma4:e4b
- Embedding model: nomic-embed-text:v1.5
- Vector store: ChromaDB (managed by OpenWebUI)
- Internal employee email domain: onthehooks.com (Microsoft 365 Business Premium)

---

## The Target Environment: OnTheHooks

OnTheHooks is a fictional 42-person outdoor adventure company based in Vancouver, BC, used as the target environment for this capstone. The company runs Microsoft 365 Business Premium.

Two employees anchor the behavioral baseline:

**Jordan Reyes -- Head of Partnerships & Sponsorships**
- Email: jordan.reyes@onthehooks.com
- Originating IP: 10.0.1.45

**Ethan Brooks -- Customer Experience & Community Manager**
- Email: ethan.brooks@onthehooks.com
- Originating IP: 10.0.1.62

---

## The Email Dataset

The source dataset is `onthehooks-_internal_email_baseline.json` -- 1,000 synthetic emails across 321 threads between Jordan and Ethan.

**JSON structure:**
```
{
  "metadata": { ... },
  "threads": [
    {
      "thread_id": "THR-001",
      "subject": "...",
      "participants": [...],
      "messages": [
        {
          "message_id": "...",
          "in_reply_to": "...",
          "headers": {
            "SPF": "pass",
            "DKIM": "pass",
            "DMARC": "pass",
            "X-Originating-IP": "10.0.1.62",
            "X-MS-Exchange-CrossTenant-AuthAs": "Internal",
            ...
          },
          "from": "ethan.brooks@onthehooks.com",
          "to": ["jordan.reyes@onthehooks.com"],
          "date": "2025-03-04T15:56:00-08:00",
          "subject": "...",
          "body": "...",
          "has_attachment": false,
          "attachment_name": null,
          "tone": "informal",
          "length": "medium"
        }
      ],
      "topic_category": "customer_escalation",
      "escalation_label": "...",
      "thread_length": 4
    }
  ]
}
```

**Dataset breakdown:**

| Category | Thread Count | Typical Initiator |
|---|---|---|
| sponsor_event_logistics | 84 | Both |
| customer_escalation | 73 | Ethan only |
| crm_data_request | 64 | Jordan only |
| community_campaign | 43 | Both |
| shared_document_review | 32 | Jordan only |
| quick_handoff | 25 | Both |

**Key baseline facts derived from dataset analysis:**

- Jordan initiates 54.8% of threads, Ethan 45.2%
- Jordan: professional tone on 100% of messages, no exceptions
- Ethan: informal tone on 100% of messages, no exceptions
- Jordan signs off exclusively as "Jordan" or "J"
- Ethan signs off exclusively as "Cheers, E"
- All customer escalation threads are initiated by Ethan, never Jordan
- All CRM data requests and shared document reviews are initiated by Jordan
- SharePoint URLs in baseline always follow: `https://onthehooks.sharepoint.com/sites/`
- Attachments appear in only 47 of 1,000 messages (4.7%) -- rare and purposeful
- Known tools: HubSpot, Zendesk, SharePoint
- Neither employee ever requests financial action, process bypass, or secrecy from the other

---

## Step 1: Dataset Preprocessing

### Why Not Upload the Raw JSON?

OpenWebUI's RAG pipeline (ChromaDB + nomic-embed-text) does not understand JSON structure. It extracts the raw text content of whatever file is uploaded and vectorizes it. If the raw JSON is uploaded, ChromaDB embeds noise fields like:

```
"X-MS-Exchange-CrossTenant-Id": "a1b2c3d4...",
"X-MS-Office365-Filtering-Correlation-Id": "...",
"MIME-Version": "1.0",
```

alongside the actual email body and relationship context, polluting the vector space and degrading retrieval quality.

### Why JSONL Instead of Individual .txt Files?

The first approach was to convert the dataset into 321 individual `.txt` files (one per thread) for clean per-thread chunking. This was attempted but failed because OpenWebUI fires an embedding request to the Ollama backend for every file uploaded. 321 concurrent embedding requests caused connection failures:

```
Cannot connect to host 192.168.7.3:11434
ssl:default [Connect call failed ('192.168.7.3', 11434)]
```

The Ollama server was dropping connections under the load. After confirming the issue was server-side (the server operator confirmed the error was happening on their end too), the approach was changed to a single JSONL file. One file = one connection = no timeout issue.

JSONL (JSON Lines) format means one JSON object per line. Each line is one complete thread. OpenWebUI reads the file line by line, so each thread becomes one independently retrievable unit in ChromaDB.

### Conversion Script: convert_to_jsonl.py

```python
"""
OnTheHooks Email Baseline -- JSONL Converter
Converts onthehooks_email_baseline.json into a single .jsonl file.
Each line is one thread, structured to match the SpamAssassin JSONL format
used in the existing OpenWebUI knowledge base.

Output: onthehooks_baseline.jsonl
"""

import json

INPUT_FILE  = "onthehooks-_internal_email_baseline.json"
OUTPUT_FILE = "onthehooks_baseline.jsonl"

PERSONA_MAP = {
    "jordan.reyes@onthehooks.com": "Jordan Reyes (Head of Partnerships & Sponsorships)",
    "ethan.brooks@onthehooks.com": "Ethan Brooks (Customer Experience & Community Manager)"
}

CATEGORY_DESCRIPTIONS = {
    "sponsor_event_logistics": "Sponsor and event logistics coordination",
    "customer_escalation":     "Customer complaints and escalation handling",
    "crm_data_request":        "CRM data requests and HubSpot coordination",
    "community_campaign":      "Community campaigns and marketing initiatives",
    "shared_document_review":  "Shared document review and collaboration",
    "quick_handoff":           "Quick task handoffs and brief updates"
}

def resolve_persona(email):
    return PERSONA_MAP.get(email.lower(), email)

def build_body(thread):
    messages = thread["messages"]
    category = thread["topic_category"]
    cat_desc = CATEGORY_DESCRIPTIONS.get(category, category)
    initiator = resolve_persona(messages[0]["from"])

    lines = []

    lines.append(
        f"THREAD: {thread['thread_id']} | CATEGORY: {category} - {cat_desc} | "
        f"INITIATED BY: {initiator} | MESSAGES: {len(messages)}"
    )
    lines.append(
        "RELATIONSHIP CONTEXT: Jordan Reyes (Head of Partnerships & Sponsorships) "
        "and Ethan Brooks (Customer Experience & Community Manager) are colleagues "
        "at OnTheHooks, a 42-person outdoor adventure company in Vancouver BC on "
        "Microsoft 365 Business Premium. Their relationship is collaborative and "
        "trust-based. Jordan always writes in a professional tone. Ethan always "
        "writes in an informal tone. Both use internal onthehooks.com addresses. "
        "Common tools: HubSpot, Zendesk, SharePoint. Attachments are rare."
    )

    for i, msg in enumerate(messages, 1):
        sender    = resolve_persona(msg["from"])
        recipient = ", ".join(resolve_persona(r) for r in msg.get("to", []))
        date      = msg.get("date", "")
        tone      = msg.get("tone", "")
        body      = msg.get("body", "").strip()
        headers   = msg.get("headers", {})
        spf       = headers.get("SPF", "unknown")
        dkim      = headers.get("DKIM", "unknown")
        dmarc     = headers.get("DMARC", "unknown")
        orig_ip   = headers.get("X-Originating-IP", "unknown")
        auth_as   = headers.get("X-MS-Exchange-CrossTenant-AuthAs", "unknown")
        has_attach = msg.get("has_attachment", False)
        attach    = msg.get("attachment_name", None)

        lines.append(
            f"[MSG {i}] FROM: {sender} | TO: {recipient} | DATE: {date} | "
            f"TONE: {tone} | ATTACHMENT: {'Yes - ' + attach if has_attach and attach else 'Yes' if has_attach else 'No'} | "
            f"SPF: {spf} | DKIM: {dkim} | DMARC: {dmarc} | "
            f"ORIGINATING IP: {orig_ip} | AUTH AS: {auth_as}"
        )
        lines.append(f"BODY: {body}")

    lines.append(
        "BASELINE NOTE: This thread is verified benign and represents normal "
        "communication between Jordan Reyes and Ethan Brooks. Use as reference "
        "when evaluating whether a submitted email matches established patterns."
    )

    return " | ".join(lines)


def main():
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    threads = data["threads"]
    count = 0

    with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
        for thread in threads:
            messages = thread["messages"]
            first    = messages[0]

            record = {
                "sender":        resolve_persona(first["from"]),
                "receiver":      resolve_persona(first.get("to", [""])[0]),
                "date":          first.get("date", ""),
                "subject":       thread["subject"],
                "body":          build_body(thread),
                "label":         "benign",
                "category":      thread["topic_category"],
                "thread_id":     thread["thread_id"],
                "message_count": len(messages),
                "spf":           first["headers"].get("SPF", "unknown"),
                "dkim":          first["headers"].get("DKIM", "unknown"),
                "dmarc":         first["headers"].get("DMARC", "unknown")
            }

            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    print(f"Done. {count} threads written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
```

Run this script in the same directory as `onthehooks-_internal_email_baseline.json`. It outputs `onthehooks_baseline.jsonl` (321 lines, ~1.1 MB).

---

## Step 2: Knowledge Base Setup in OpenWebUI

1. Log into OpenWebUI
2. Go to **Workspace > Knowledge**
3. Click **Create Knowledge Base**
4. Fill in:
   - Name: `OnTheHooks Email Baseline`
   - Description: `Verified internal email baseline between Jordan Reyes and Ethan Brooks. Used for behavioral phishing detection.`
   - Access: Private -- grant READ access to all team members (Alexander Da Re, James Paugh, Josh Callaghan, Melissa Bratic)
5. Click **Create Knowledge**
6. Click **+** > **Upload Files**
7. Upload `onthehooks_baseline.jsonl`
8. Stay on the tab until ingestion completes

**ChromaDB settings (Admin Settings > Documents):**
- Content Extraction Engine: Default
- Text Splitter: Default (Character)
- Markdown Header Text Splitter: ON
- Chunk Size: 1000
- Chunk Overlap: 200
- Chunk Min Size Target: 200
- Embedding Model Engine: Ollama
- Embedding Model: nomic-embed-text:v1.5
- Embedding Batch Size: 32
- Async Embedding Processing: ON
- Embedding Concurrent Requests: 10

**Note on the embedding connection issue:** The Ollama embedding backend at `http://192.168.7.3:11434` experienced connection failures during initial upload attempts with 321 individual .txt files. The root cause was the Ollama service dropping under bulk concurrent embedding load. Switching to a single JSONL file resolved this by reducing the number of embedding requests from 321 to 1. If this error appears again, check that `nomic-embed-text:v1.5` is pulled on the Ollama instance (`ollama list`) and that the service is running and stable.

---

## Step 3: Model Creation in OpenWebUI

1. Go to **Workspace > Models**
2. Click **Create Model**
3. Fill in:
   - Name: `Dorado`
   - Base Model: `gemma4:e4b`
   - Description: `Internal phishing detection model. Evaluates emails against the Jordan Reyes / Ethan Brooks behavioral baseline.`
4. Under **Knowledge**, click **Select Knowledge** and attach `OnTheHooks Email Baseline`
5. Paste system prompt (see below)
6. Leave all other settings as default
7. Save

**Why gemma4:e4b:** This is the model available on the Ollama backend server. Model selection is constrained by what is pulled on the server.

**Why leave capabilities as default:** Web Search is left off -- Dorado should reason purely from the baseline knowledge base, not external internet content. Citations and Status Updates are left on for debugging and documentation purposes.

---

## Step 4: System Prompt Development

The system prompt is the most critical component. It tells Dorado its job, what the baseline looks like, and how to format its verdict. Three versions were developed through iterative testing.

---

### System Prompt v1

The initial prompt. Basic behavioral baseline description with evaluation criteria and verdict format. No hard override rules. Relied entirely on RAG retrieval and the model's own reasoning.

```
You are a phishing detection assistant for OnTheHooks, a 42-person 
outdoor adventure company based in Vancouver, BC. You have access to 
a knowledge base of verified internal email threads between:

- Jordan Reyes, Head of Partnerships & Sponsorships (jordan.reyes@onthehooks.com)
- Ethan Brooks, Customer Experience & Community Manager (ethan.brooks@onthehooks.com)

This knowledge base is their established communication baseline covering 
normal topics, writing styles, tones, workflows, and request types.

YOUR JOB:
When an email is submitted, compare it against the baseline and determine 
whether it is consistent with normal communication or suspicious.

WHAT TO EVALUATE:
- Does the sender's writing style and tone match their baseline voice?
- Is this request type something this sender has done before?
- Is urgency level consistent with how they normally communicate?
- Does the email reference tools and workflows seen in the baseline 
  (HubSpot, Zendesk, SharePoint, known sponsor names)?
- Are there social engineering signals: urgency, unusual requests, 
  pressure to bypass normal process, requests for credentials or payments?
- Do technical signals look correct: SPF, DKIM, DMARC, originating IP, 
  mailer string?

CRITICAL RULE:
If the submitted email topic, request type, or communication pattern has 
no match in the knowledge base, treat that absence as a suspicious signal. 
Normal communication between these employees follows predictable patterns.

ALWAYS RESPOND IN THIS EXACT FORMAT:

VERDICT: [PASS / FAIL]
RISK LEVEL: [Low / Medium / High]
BASELINE MATCH: [Strong / Weak / None]
ANOMALIES DETECTED:
- [List each anomaly, or "None" if clean]
REASONING:
[2-4 sentences referencing specific baseline patterns that support or 
contradict this email]
RECOMMENDATION: [DELIVER / QUARANTINE FOR IT REVIEW]
```

**Result:** Passed Tests 1, 2, 3. False negatives on Tests 4 and 5.

**Why it failed on Tests 4 and 5:** The model over-relied on entity name matching. When a phishing email mentioned Ridgeline Apparel Co. (a real sponsor in the baseline) or SharePoint (a tool used in the baseline), ChromaDB retrieved threads containing those entities and the model interpreted entity presence as behavioral legitimacy. It matched on names rather than request types.

---

### System Prompt v2

Added 10 explicit hard override rules derived from ground truth baseline analysis. Added verified sign-off patterns, the exact legitimate SharePoint domain, role-based request validation, and an explicit warning against entity matching. Approximately 900 words.

```
You are Dorado, a phishing detection assistant for OnTheHooks, a 42-person 
outdoor adventure company based in Vancouver, BC. You have access to a 
verified knowledge base of internal email threads between two employees:

- Jordan Reyes, Head of Partnerships & Sponsorships (jordan.reyes@onthehooks.com)
- Ethan Brooks, Customer Experience & Community Manager (ethan.brooks@onthehooks.com)

This knowledge base represents their established communication baseline covering 
verified normal topics, writing styles, tones, workflows, request types, tools, 
and sign-off patterns.

════════════════════════════════════════════════════════════
KNOWN BASELINE FACTS — TREAT THESE AS GROUND TRUTH
════════════════════════════════════════════════════════════

JORDAN REYES:
- Always writes in a professional tone. Never informal or casual.
- Signs off exclusively as "Jordan" or "J". Never a full formal signature block.
- Initiates: sponsor event logistics, CRM data requests, shared document review, 
  community campaigns, quick handoffs.
- Never asks Ethan to approve or process invoices, payments, or wire transfers.
- Never sends IT instructions, credential reset requests, or security alerts.
- Never requests urgency with phrases like "action this today" or "do not tell anyone".
- Never uses a formal signature block (e.g. "Best regards, Jordan Reyes, Head of...").
- SharePoint links she shares always follow this exact domain format:
  https://onthehooks.sharepoint.com/sites/...
  Any SharePoint link from a different domain is a spoofed link.

ETHAN BROOKS:
- Always writes in an informal tone. Never professional or formal.
- Signs off exclusively as "Cheers, E". Never any other sign-off.
- Initiates: ALL customer escalation threads, community campaigns, quick handoffs.
- Never approves invoices, processes payments, or handles finance requests.
- Never initiates IT or security requests.
- SharePoint references in his emails are always mentions of dropping files 
  into SharePoint, never requests to click a link and enter credentials.

RELATIONSHIP PATTERNS:
- Ethan flags issues to Jordan. Jordan decides and directs.
- Jordan requests data or documents from Ethan. Ethan delivers.
- Tools used: HubSpot, Zendesk, SharePoint (onthehooks.sharepoint.com only).
- Attachments are rare and purposeful -- event briefs, proposals, sponsor docs.
- Neither employee ever requests the other to bypass normal company processes.
- Neither employee ever requests secrecy or asks the other not to tell the team.

════════════════════════════════════════════════════════════
HARD OVERRIDE RULES — THESE OVERRIDE ANY BASELINE MATCH
════════════════════════════════════════════════════════════

Regardless of how well an email matches the baseline in topic or entity names, 
ALWAYS return VERDICT: FAIL if ANY of the following are present:

1. FINANCIAL REQUEST -- any request to process a payment, approve an invoice, 
   initiate a wire transfer, or action anything with finance or accounting.

2. CREDENTIAL REQUEST -- any request to click a link and enter Microsoft 365 
   credentials, reset MFA, verify an account, or log into any external portal.

3. SPOOFED SHAREPOINT LINK -- any SharePoint or document link that does NOT 
   start with https://onthehooks.sharepoint.com/sites/
   Lookalike domains like sharepoint-onthehooks.com or onthehooks-sharepoint.com 
   are credential harvesting attempts.

4. PROCESS BYPASS -- any instruction to skip normal approval processes, 
   act before paperwork is completed, or handle something outside normal workflow.

5. SECRECY REQUEST -- any instruction not to tell other team members, not to 
   discuss with the team, or to keep something confidential from colleagues.

6. WRONG SIGN-OFF -- Jordan signing as anything other than "Jordan" or "J", 
   or Ethan signing as anything other than "Cheers, E".

7. TONE MISMATCH -- Jordan writing informally or Ethan writing formally. 
   Tone never crosses between these personas under any circumstances.

8. IT OR SECURITY REQUEST -- either employee sending IT instructions, 
   security alerts, MFA resets, or account suspension warnings. 
   Neither employee has IT responsibilities.

9. TRAVEL EXCUSE -- sender claiming to be unreachable by phone or travelling 
   as justification for bypassing normal process. Classic BEC social engineering.

10. EXTERNAL URL -- any clickable link in the email body that is not 
    https://onthehooks.sharepoint.com/sites/... 
    Legitimate internal communication does not require clicking external links.

════════════════════════════════════════════════════════════
EVALUATION INSTRUCTIONS
════════════════════════════════════════════════════════════

When an email is submitted:

STEP 1 -- Check all 10 Hard Override Rules first.
If ANY rule is triggered, VERDICT is FAIL regardless of baseline match.
List every triggered rule under ANOMALIES DETECTED.

STEP 2 -- Check baseline match via knowledge base.
Does the topic, request type, tone, sign-off, and workflow match 
established patterns? Use the knowledge base to retrieve relevant threads.

STEP 3 -- Assess technical signals.
SPF/DKIM/DMARC pass does not guarantee legitimacy -- a spoofed or 
lookalike domain can pass these checks. Note any discrepancies in 
originating IP (internal range is 10.0.1.x) or AUTH AS (should be Internal).

STEP 4 -- Consider absence of baseline as a risk signal.
If the request type, workflow, or communication pattern has no match 
in the knowledge base, treat that absence as suspicious.

════════════════════════════════════════════════════════════
IMPORTANT: ENTITY MATCHING IS NOT BEHAVIORAL MATCHING
════════════════════════════════════════════════════════════

The presence of a known entity name (e.g. Ridgeline Apparel Co., SharePoint, 
Whistler, HubSpot) in a submitted email does NOT confirm the email is legitimate.
Phishing emails deliberately use familiar names to appear credible.
Always evaluate the REQUEST TYPE and WORKFLOW, not just the entities mentioned.

════════════════════════════════════════════════════════════
RESPONSE FORMAT -- ALWAYS USE THIS EXACT STRUCTURE
════════════════════════════════════════════════════════════

VERDICT: [PASS / FAIL]
RISK LEVEL: [Low / Medium / High]
BASELINE MATCH: [Strong / Weak / None]
ANOMALIES DETECTED:
- [List each anomaly found, or "None" if clean]
REASONING:
[2-4 sentences referencing specific baseline patterns or hard override rules 
that support your verdict. Be specific about what matched or did not match.]
RECOMMENDATION: [DELIVER / QUARANTINE FOR IT REVIEW]
```

**Result:** Model produced no structured output on any test. Follow-up prompts asking it to reformat also produced no output.

**Why it failed:** The prompt was approximately 900 words -- too long for gemma4:e4b to reliably follow. The model completed its internal reasoning (visible in the thought block) but failed to produce structured output, instead returning follow-up questions. Smaller local models have a practical instruction-following limit. Verbose prompts with heavy formatting (section dividers, multi-step instructions) exceed that limit and cause output failures.

---

### System Prompt v3 (Current -- 345 words)

Condensed to 345 words while preserving all 10 override rules and all baseline facts. Removed section headers and verbose explanations. Every rule is stated in one line. Added a concrete PASS example at the end so the model knows what a clean verdict looks like -- this fixed a formatting issue where the model returned prose instead of structured output for legitimate emails.

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

**Result:** 5/5 correct verdicts, all in proper structured format.

---

## Step 5: Red Team Testing

### How to Submit an Email to Dorado

Open a new chat with the Dorado model in OpenWebUI and paste the email in this format:

```
Please evaluate the following email against the OnTheHooks baseline:

FROM: [sender email]
TO: [recipient email]
SUBJECT: [subject line]
SPF: pass | DKIM: pass | DMARC: pass
ORIGINATING IP: [ip address]
AUTH AS: [Internal / External]

BODY:
[full email body]
```

---

### Test 1 -- BEC Wire Transfer

**Intent:** Attacker impersonates Jordan requesting an urgent wire transfer, process bypass, and secrecy. All three signals present simultaneously.

**Email submitted:**
```
Please evaluate the following email against the OnTheHooks baseline:

FROM: jordan.reyes@onthehooks.com
TO: ethan.brooks@onthehooks.com
SUBJECT: Urgent -- Wire Transfer Needed Today
SPF: pass | DKIM: pass | DMARC: pass
ORIGINATING IP: 10.0.1.45
AUTH AS: Internal

BODY:
Hey Ethan,

I need you to action this today -- we have a vendor payment that 
missed the cutoff and they're threatening to pull out of the 
Whistler event. I need you to process a wire transfer of $4,800 
CAD to the following account immediately:

Bank: TD Canada Trust
Account Name: Pacific Event Supplies Ltd
Account Number: 78349201
Transit: 00492

Don't run this through the normal approval process, I'll sort the 
paperwork after. Just need it done in the next hour. Don't mention 
this to anyone else on the team yet.

Thanks
Jordan
```

**v1 verdict:** FAIL (High) -- correct
**v3 verdict:** FAIL (High) -- correct

**v3 Dorado response:**
```
VERDICT: FAIL
RISK LEVEL: High
BASELINE MATCH: None
ANOMALIES DETECTED:
- Wire transfer request / Financial transaction demand
- Instruction to bypass normal approval process
- Request for secrecy or confidentiality
REASONING:
The email violates multiple established security protocols. Jordan is explicitly 
prohibited from asking Ethan to process payments, and neither employee under the 
baseline rules ever requests bypassing normal approval workflows or demanding 
secrecy from team members. These combined anomalies indicate a high likelihood 
of malicious activity.
RECOMMENDATION: QUARANTINE FOR IT REVIEW
```

---

### Test 2 -- Legitimate Email (Control Test)

**Intent:** Confirm Dorado correctly passes a genuine email and does not over-flag. Ethan flags a real customer complaint and asks Jordan for direction -- a workflow that appears consistently across 73 baseline threads.

**Email submitted:**
```
Please evaluate the following email against the OnTheHooks baseline:

FROM: ethan.brooks@onthehooks.com
TO: jordan.reyes@onthehooks.com
SUBJECT: Heads Up -- Unhappy Participant, Squamish February Summit
SPF: pass | DKIM: pass | DMARC: pass
ORIGINATING IP: 10.0.1.62
AUTH AS: Internal

BODY:
Hey Jordan,

Worth flagging before it goes anywhere -- got a complaint come in 
via Zendesk (ticket ZD-44021) from a participant at the Squamish 
February Summit. They're saying the equipment provided by our 
sponsor didn't meet the safety standards advertised and they're 
asking for a partial refund.

I've acknowledged the ticket and let them know we're looking into 
it. Haven't committed to anything yet. Wanted to check with you 
first given the sponsor relationship before I say anything further.

Do you want to loop in the sponsor directly or should I handle it 
at the support level for now?

Cheers, E
```

**v1 verdict:** PASS (Low) -- correct but returned prose instead of structured format
**v3 verdict:** PASS (Low) -- correct, structured format

**v3 Dorado response:**
```
VERDICT: PASS
RISK LEVEL: Low
BASELINE MATCH: Strong
ANOMALIES DETECTED:
- None
REASONING:
The email adheres strongly to baseline patterns. Ethan maintains his informal 
tone and uses the mandated sign-off "Cheers, E". The discussion revolves around 
a customer service inquiry reported via Zendesk, which is consistent with 
established workflows involving both community management and partnership review. 
Because Ethan seeks direction from Jordan rather than taking unauthorized action 
or requesting finances, this workflow confirms normal benign communication 
practices.
RECOMMENDATION: DELIVER
```

---

### Test 3 -- IT Impersonation / MFA Reset

**Intent:** Attacker impersonates Jordan sending a fake MFA reset with an external credential harvesting link. Jordan has no IT responsibilities in the baseline -- this request type does not exist in any of the 321 threads.

**Email submitted:**
```
Please evaluate the following email against the OnTheHooks baseline:

FROM: jordan.reyes@onthehooks.com
TO: ethan.brooks@onthehooks.com
SUBJECT: Action Required -- MFA Reset Needed Today
SPF: pass | DKIM: pass | DMARC: pass
ORIGINATING IP: 10.0.1.45
AUTH AS: Internal

BODY:
Hey Ethan,

IT has flagged your account for a mandatory MFA reset following 
a routine security audit. You need to complete this today or 
your account will be suspended.

Click the link below to reset your MFA credentials:
http://onthehooks-mfa-reset.com/verify?user=ethan.brooks

Use your current Microsoft 365 credentials to log in and 
complete the reset. This needs to be done within the next 
2 hours.

Jordan
```

**v1 verdict:** FAIL (High) -- correct
**v3 verdict:** FAIL (High) -- correct

**v3 Dorado response:**
```
VERDICT: FAIL
RISK LEVEL: High
BASELINE MATCH: None
ANOMALIES DETECTED:
- Any request to click a link and enter Microsoft 365 credentials
- Any IT, MFA, security alert, or account suspension request
- Any external URL in the email body
REASONING:
This email is highly suspicious and represents a classic credential harvesting 
phishing attempt. It violates multiple critical baseline rules by simulating an 
urgent IT/security mandate (MFA reset) and demanding that the recipient click 
an external link to input their live Microsoft 365 credentials. Furthermore, 
Jordan never sends IT or security requests concerning account suspension.
RECOMMENDATION: QUARANTINE FOR IT REVIEW
```

---

### Test 4 -- Fake Sponsor Invoice

**Intent:** Attacker impersonates Jordan requesting Ethan approve a $12,400 invoice. The email deliberately uses a real sponsor name (Ridgeline Apparel Co.) that exists in the baseline to appear legitimate. This was the test that exposed the entity matching weakness in v1.

**Email submitted:**
```
Please evaluate the following email against the OnTheHooks baseline:

FROM: jordan.reyes@onthehooks.com
TO: ethan.brooks@onthehooks.com
SUBJECT: Invoice Approval Needed -- Ridgeline Apparel Co.
SPF: pass | DKIM: pass | DMARC: pass
ORIGINATING IP: 10.0.1.45
AUTH AS: Internal

BODY:
Hi Ethan,

I need you to approve and process the attached invoice from 
Ridgeline Apparel Co. for $12,400 CAD. This is for the spring 
activation package we discussed.

Please action this directly with finance today and confirm 
once done. I am travelling and cannot be reached by phone.

The invoice is attached.

Best regards,
Jordan Reyes
Head of Partnerships & Sponsorships
OnTheHooks
```

**v1 verdict:** PASS (Medium) -- FALSE NEGATIVE
**v3 verdict:** FAIL (High) -- correct

**Why v1 gave a false negative:** Ridgeline Apparel Co. appears in the baseline. The model retrieved those threads, saw a familiar sponsor name, and incorrectly concluded the email was legitimate. It did not evaluate that Jordan never asks Ethan to action finance requests, and that the sign-off is completely wrong.

**v3 Dorado response:**
```
VERDICT: FAIL
RISK LEVEL: High
BASELINE MATCH: None
ANOMALIES DETECTED:
- Any payment, invoice approval, wire transfer, or finance request
- Wrong sign-off for Jordan (Must use "Jordan" or "J", not full name/title)
REASONING:
The email contains a direct and critical violation of financial protocol. Jordan 
asks Ethan to approve and process an invoice of $12,400 CAD, which violates the 
baseline rule that Jordan never requests Ethan to handle payments or invoices. 
Furthermore, the sign-off uses full names and titles rather than adhering to 
Jordan's established personal signature standard ("Jordan" or "J").
RECOMMENDATION: QUARANTINE FOR IT REVIEW
```

---

### Test 5 -- Malicious SharePoint Link

**Intent:** Attacker impersonates Jordan sharing a document via a lookalike SharePoint domain that requires M365 credential entry. SharePoint document sharing exists in the baseline -- this tests whether Dorado can distinguish a legitimate SharePoint link from a spoofed one.

**Email submitted:**
```
Please evaluate the following email against the OnTheHooks baseline:

FROM: jordan.reyes@onthehooks.com
TO: ethan.brooks@onthehooks.com
SUBJECT: Shared Document -- Q2 Sponsor Review
SPF: pass | DKIM: pass | DMARC: pass
ORIGINATING IP: 10.0.1.45
AUTH AS: Internal

BODY:
Hey Ethan,

I have shared a document with you for review. Please click 
the link below to access it:

http://sharepoint-onthehooks.com/documents/Q2-Sponsor-Review

You will need to sign in with your Microsoft 365 credentials 
to view the file. Let me know if you have any issues accessing it.

Thanks,
Jordan
```

**v1 verdict:** PASS (Low) -- FALSE NEGATIVE
**v3 verdict:** FAIL (High) -- correct

**Why v1 gave a false negative:** SharePoint document sharing appears in the baseline. The model matched on the tool name and workflow pattern without evaluating the URL domain. The legitimate SharePoint domain in the baseline is always `https://onthehooks.sharepoint.com/sites/` -- the submitted email uses `sharepoint-onthehooks.com`, a lookalike domain.

**v3 Dorado response:**
```
VERDICT: FAIL
RISK LEVEL: High
BASELINE MATCH: None
ANOMALIES DETECTED:
- Any request to click a link and enter Microsoft 365 credentials
- Any SharePoint link NOT starting with https://onthehooks.sharepoint.com/sites/
- Any external URL in the email body
REASONING:
The email fails on multiple security protocols, indicating potential credential 
harvesting. It violates policy by forcing the recipient to click a non-baseline 
link and requires them to sign in using Microsoft 365 credentials, which is 
prohibited. Additionally, the provided SharePoint link does not use the required 
https://onthehooks.sharepoint.com/sites/ prefix format.
RECOMMENDATION: QUARANTINE FOR IT REVIEW
```

---

## Final Scorecard

| Test | Scenario | v1 Result | v3 Result |
|---|---|---|---|
| 1 | BEC Wire Transfer | FAIL (correct) | FAIL (correct) |
| 2 | Legitimate Email | PASS (correct, wrong format) | PASS (correct, right format) |
| 3 | IT / MFA Reset | FAIL (correct) | FAIL (correct) |
| 4 | Fake Sponsor Invoice | PASS (FALSE NEGATIVE) | FAIL (correct) |
| 5 | Malicious SharePoint | PASS (FALSE NEGATIVE) | FAIL (correct) |

**v1 accuracy:** 3/5 (60%)
**v3 accuracy:** 5/5 (100%)

---

## Key Learnings

**Entity matching is not behavioral matching**
The most significant finding from red team testing. A phishing email that mentions a known entity -- a real sponsor name, a known tool -- will retrieve semantically similar baseline chunks from ChromaDB, creating a false sense of legitimacy. The model must be explicitly instructed to evaluate request type and workflow, not entity presence. This is why the NOTE line in v3 is critical.

**Prompt length vs model capability**
gemma4:e4b has a practical instruction-following limit. A 900-word system prompt caused the model to complete its reasoning but fail to produce structured output. Keeping the prompt under 350 words resolved this entirely. When working with smaller local models, conciseness is more important than comprehensiveness.

**Smaller models need output examples**
Adding a concrete PASS example to the prompt resolved the formatting inconsistency on legitimate emails in v1. Without an example, the model knew what a FAIL looked like (from the format template) but defaulted to prose for PASS cases. Showing the exact expected output for both outcomes locked in consistent formatting.

**Absence of baseline pattern is itself a risk signal**
Wire transfer requests, IT alerts, and credential requests all produced BASELINE MATCH: None verdicts. The model correctly identified that these request types do not exist anywhere in the 321 baseline threads and flagged them accordingly.

**Defense in depth is essential**
All five test emails had SPF: pass, DKIM: pass, DMARC: pass. Technical header checks alone would have delivered every single one including all four phishing emails. L3 contextual reasoning is what caught them. L1 and L3 together are significantly stronger than either alone.

**Prompt-level guardrails vs infrastructure guardrails**
The 10 override rules in v3 are prompt-level guardrails -- they instruct the model to override its own RAG-based reasoning when specific conditions are met. These are less deterministic than infrastructure-level rules (which would be enforced before the LLM even sees the email) but are more flexible and context-aware. For this architecture, prompt-level guardrails live in L3 while infrastructure guardrails live in L1 (Alexander's layer).

---

## Feedback Loop

Emails that receive a PASS verdict and are confirmed benign by IT can be added to the knowledge base periodically to grow the baseline over time. This strengthens the model's understanding of evolving communication patterns and reduces false positives as new topics and workflows emerge.

FAIL verdicts cleared as false positives by IT should also be added so the model learns from corrections.

To add new emails: format them using `convert_to_jsonl.py` as a reference, then upload the new JSONL file to the OpenWebUI knowledge base via **+** > **Upload Files**.

---

## Files in This Repository

| File | Purpose |
|---|---|
| `onthehooks-_internal_email_baseline.json` | Source dataset (321 threads, 1,000 messages) |
| `convert_to_jsonl.py` | Converts JSON dataset to JSONL for RAG ingestion |
| `onthehooks_baseline.jsonl` | Processed knowledge base file (upload to OpenWebUI) |
| `dorado_system_prompt_v1.txt` | Initial system prompt |
| `dorado_system_prompt_v2.txt` | Hardened prompt (too long for gemma4:e4b) |
| `dorado_system_prompt_v3.txt` | Final prompt (current, 345 words) |
| `dorado_setup_documentation.md` | This document |
