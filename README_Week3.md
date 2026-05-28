# INFO49402 — Capstone Group 26
## AI-Assisted Phishing Detection System

**GitHub:** https://github.com/AlexanderDaRe/Context_Based_AI_Phishing_Analyzer

---

## Project Summary

A proof-of-concept phishing detection framework using a layered LLM analysis pipeline to identify phishing emails across technical, behavioral, and contextual dimensions. The system is designed to baseline normal internal communication patterns and detect anomalies indicative of phishing or social engineering attempts.

---

## Team

| Member | Role |
|---|---|
| Melissa Bratic | Social engineering research, phishing scenario development, red team testing, project coordination |
| Jamie | System architecture, infrastructure implementation, project management |
| Alex | Email ingestion, metadata extraction, Ollama/LLM integration, backend processing |
| Josh | User alerting, notification logic, reporting workflows |

---

## Detection Architecture

The pipeline operates across three layers:

| Layer | Type | Description |
|---|---|---|
| L1 | Technical | SPF/DKIM/DMARC alignment, sender domain reputation, URL analysis, homoglyph detection |
| L2 | Behavioral | Sender-recipient communication frequency baseline, send-time anomaly detection, metadata inspection |
| L3 | Contextual | Full email body contextual risk scoring via LLM, writing style baseline comparison, composite phishing confidence score |

---

## Simulated Environment — OnTheHooks.com

To support realistic phishing simulation and LLM behavioral baselining, this week a complete hypothetical company environment was designed and documented.

**Company:** OnTheHooks.com  
**Industry:** Outdoor Adventure & Expedition Tourism  
**Headquarters:** Vancouver, BC, Canada  
**Employees:** 42  
**Cloud Stack:** Microsoft 365 Business Premium, Microsoft Entra ID, Microsoft Intune, Defender for Endpoint, Defender for Office 365, Microsoft Sentinel SIEM  

### Organizational Structure

| Name | Title |
|---|---|
| Avery Chen | Operations Director |
| Jordan Reyes | Head of Partnerships & Sponsorships |
| Maya Patel | Digital Content Producer |
| Ethan Brooks | Customer Experience & Community Manager |
| Sofia Bennett | Lead Cybersecurity & Platform Engineer |

### Internal Infrastructure

| Detail | Value |
|---|---|
| Domain | onthehooks.com |
| Exchange Host | YQRVMX01.onthehooks.local |
| O365 Relay | outlook.office365.com |
| Tenant ID | a1b2c3d4-e5f6-7890-abcd-ef1234567890 |
| Internal IP Range | 10.0.1.0/24 |
| Identity Provider | Microsoft Entra ID with MFA enforced |
| SharePoint Base | https://onthehooks.sharepoint.com/sites/ |

---

## Week 3 Progress

### Synthetic Email Dataset — Behavioral Baseline

This week the primary deliverable was the creation of a **1,000-email synthetic communication dataset** between two OnTheHooks employees to serve as the LLM behavioral baseline for phishing detection.

#### Target Personas

Two employees were selected based on their role overlap, communication frequency, and value as phishing targets:

**Jordan Reyes — Head of Partnerships & Sponsorships**
- Email: jordan.reyes@onthehooks.com
- Workstation IP: 10.0.1.45
- Communication style: Professional, concise under pressure, delegates data requests to Ethan, shares SharePoint links, references sponsors by first name
- Behavioral baseline: Initiates most threads Mon–Wed, desktop Outlook only, sends after hours near deadlines

**Ethan Brooks — Customer Experience & Community Manager**
- Email: ethan.brooks@onthehooks.com
- Workstation IP: 10.0.1.62
- Communication style: Friendly and informal, chatty, adds commentary, precise when escalating, signs off as "Cheers, E"
- Behavioral baseline: Primarily responds to Jordan, high volume Thu–Fri, occasional weekend mobile sends for urgent items, references Zendesk tickets and HubSpot data

#### Dataset Specifications

| Property | Value |
|---|---|
| Total Emails | 1,000 |
| Total Threads | 321 |
| Average Messages per Thread | 3.1 |
| Date Range | January 2025 – March 2025 |
| Escalation Label | `benign` (baseline corpus) |
| File Format | JSON |
| File Size | 2.35 MB |

#### Topic Category Distribution

| Category | Threads | Percentage |
|---|---|---|
| sponsor_event_logistics | 84 | 26.2% |
| customer_escalation | 73 | 22.7% |
| crm_data_request | 64 | 19.9% |
| community_campaign | 43 | 13.4% |
| shared_document_review | 32 | 10.0% |
| quick_handoff | 25 | 7.8% |

#### Message Length Distribution

| Length | Count | Percentage |
|---|---|---|
| Short | 304 | 30.4% |
| Medium | 591 | 59.1% |
| Long | 105 | 10.5% |

#### Email Header Schema

Every email in the dataset includes a full realistic M365 header object. Headers are consistent with legitimate internal Microsoft 365 traffic and serve as the ground truth for L1 technical analysis:

```json
{
  "Message-ID": "<MSG-XXX-YYY.username@onthehooks.com>",
  "In-Reply-To": "<parent-message-id>",
  "References": "<chain of prior message IDs>",
  "From": "Jordan Reyes <jordan.reyes@onthehooks.com>",
  "To": "Ethan Brooks <ethan.brooks@onthehooks.com>",
  "Date": "Tue, 14 Jan 2025 09:23:00 -0800",
  "SPF": "pass",
  "DKIM": "pass",
  "DMARC": "pass",
  "X-MS-Exchange-CrossTenant-AuthAs": "Internal",
  "X-MS-Exchange-Organization-SCL": "-1",
  "X-Originating-IP": "10.0.1.45",
  "X-Mailer": "Microsoft Outlook 16.0",
  "X-MS-Exchange-CrossTenant-Id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

Threading is correctly implemented: `In-Reply-To` references the immediate parent message ID, and `References` contains the full chain of prior message IDs in the thread.

#### JSON Dataset Structure

```json
{
  "metadata": {
    "dataset": "OnTheHooks Internal Email Baseline",
    "participants": ["jordan.reyes@onthehooks.com", "ethan.brooks@onthehooks.com"],
    "date_range": "2025-01-06 to 2025-03-28",
    "total_threads": 321,
    "total_emails": 1000,
    "escalation_label": "benign",
    "purpose": "LLM behavioral baseline training for phishing detection"
  },
  "threads": [
    {
      "thread_id": "THR-001",
      "subject": "...",
      "participants": ["..."],
      "messages": [...],
      "topic_category": "sponsor_event_logistics",
      "escalation_label": "benign",
      "thread_length": 4
    }
  ]
}
```

---

## Files Produced This Week

| File | Description |
|---|---|
| `OnTheHooks_Hypothetical_Company_Environment.docx` | Full hypothetical company design document including org structure, Microsoft 365 environment, security posture, behavioral baselines, and threat simulation scenarios |
| `OnTheHooks_Persona_Reference.md` | Detailed persona specification for Jordan Reyes and Ethan Brooks — roles, communication styles, behavioral patterns, company references, and infrastructure constants |
| `GPT_Master_Prompt.md` | LLM generation specification used to produce synthetic email traffic — includes system prompt, JSON schema, header rules, threading logic, and batch generation methodology |
| `onthehooks_email_baseline.json` | Synthetic email dataset — 1,000 emails across 321 threads between Jordan Reyes and Ethan Brooks, with full M365 headers, realistic content, and consistent behavioral patterns |

---

## Next Steps (Week 4)

- Ingest `onthehooks_email_baseline.json` into the Ollama/LLM pipeline for behavioral baselining
- Begin generating phishing variant dataset (T1–T4 escalation tiers) using the same JSON schema with injected header and behavioral anomalies
- Evaluate L1 technical layer against header anomalies in phishing samples
- Validate L3 contextual scoring against the established behavioral baseline
- Begin logging and metrics collection (click rates, detection latency, true/false positive rates)
- Continue Azure architecture setup for pipeline deployment

---

## Phishing Simulation Framework (7 Phases)

| Phase | Description |
|---|---|
| 1 | Pre-Engagement & Scoping — objectives, scope, infrastructure, Ollama pipeline setup |
| 2 | External Direct-Send Phishing — vendor invoice lure, SaaS password reset, HR/payroll spoof |
| 3 | Internal Trust-Based Phishing — IT credential reset, shared doc lure, MFA fatigue, BEC wire transfer |
| 4 | AI Detection & Analysis Pipeline — L1/L2/L3 layered analysis, composite scoring |
| 5 | Escalation Tier Testing — T0 (baseline) through T4 (BEC critical) |
| 6 | Logging, Evidence & Metrics — click rates, detection latency, true/false positive rates |
| 7 | Reporting & AI Tuning — post-simulation analysis, prompt tuning, detection delta measurement |

### Escalation Tiers

| Tier | Scenario | Risk Level |
|---|---|---|
| T0 | Routine IT email, no link | Low |
| T1 | IT email with internal link to known portal | Low |
| T2 | IT email with urgency + credential reset link | Medium |
| T3 | IT email with unknown link + financial action | High |
| T4 | BEC-style wire transfer request | Critical |

---

## Authorization

All simulations are conducted within a fictional environment under a fabricated authorization contract for academic purposes only.

**Service Provider:** 123 HackMe Security Consulting  
**Client:** On The Hooks Fishing Org  
**Lead Assessor:** Melissa Bratic  
**Reference:** 123HM-2024-PT-0047  
**Engagement Period:** November 18, 2024 – March 28, 2025  

*All content, personas, company environments, and email data in this repository are entirely fictional and intended strictly for educational and academic cybersecurity research purposes.*
