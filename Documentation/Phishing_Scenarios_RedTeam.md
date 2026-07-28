# Phishing Simulation Scenarios — OnTheHooks.com
## Red Team Scenario Design Document

**Project:** INFO49402 Capstone — Group 26  
**Author:** Melissa Bratic  
**Purpose:** Define realistic phishing scenarios targeting simulated OnTheHooks personas for AI-assisted phishing detection testing  
**Classification:** Academic use only — all content fictional

---

## Overview

The following scenarios are designed to test the AI phishing detection pipeline against realistic attack chains targeting two OnTheHooks employees: **Jordan Reyes** (Head of Partnerships & Sponsorships) and **Ethan Brooks** (Customer Experience & Community Manager). Each scenario is mapped to the detection pipeline's three analysis layers (L1 Technical, L2 Behavioral, L3 Contextual) and assigned an escalation tier (T0–T4).

The goal of each scenario from an attacker's perspective is to gain initial access and then move laterally or extract value from within the environment. Scenario design follows realistic red team methodology grounded in the established behavioral baseline.

---

## Target Profiles

| Target | Role | Value to Attacker |
|---|---|---|
| Jordan Reyes | Head of Partnerships & Sponsorships | Access to sponsor contracts, external vendor relationships, SharePoint, financial approval workflows |
| Ethan Brooks | Customer Experience & Community Manager | Access to HubSpot (customer PII), Zendesk (ticket history), community email lists, internal Teams channels |

---

## Scenario 1 — Fake Sponsor Invoice

**Target:** Jordan Reyes  
**Escalation Tier:** T3 (High)  
**Vector:** External email spoofing a known sponsor contact  
**Lure:** Ridgeline Apparel Co. invoice requiring urgent payment approval  

### Attack Chain

1. Attacker registers a lookalike domain (`ridgelineapparel-co.com` or `ridgline-apparel.com`)
2. Sends an email impersonating Marcus (Jordan's known contact at Ridgeline Apparel Co.) referencing a real upcoming event to establish legitimacy
3. Email contains a revised invoice PDF with an embedded malicious link, or a direct request to update banking details for payment processing
4. Jordan, mid-partnership-cycle and accustomed to invoice handling, clicks the link or forwards to finance without verifying the sender domain

### Why It Works

Jordan communicates with external vendors constantly. Invoice emails are routine and expected. The attacker leverages an established relationship name and real event context. No unusual behaviour is required from the target.

### Post-Access Objective

Credential harvest via cloned O365 login page. If a payload executes, establishes a beachhead on Jordan's workstation for lateral movement toward finance systems and SharePoint.

### Lateral Movement Opportunities

- SharePoint access exposes sponsor contracts, proposals, and internal event briefs
- Jordan's Outlook access allows further internal phishing from a trusted sender
- Financial approval workflows reachable if Jordan has delegated access

### Detection Signals

| Layer | Signal |
|---|---|
| L1 Technical | SPF/DKIM fail on lookalike domain; sender domain not onthehooks.com |
| L2 Behavioral | No prior communication history from that sending domain |
| L3 Contextual | Urgency language combined with financial action request; deviates from Jordan's established baseline |

---

## Scenario 2 — Internal IT Impersonation / MFA Reset

**Target:** Ethan Brooks  
**Escalation Tier:** T4 (Critical)  
**Vector:** Spoofed or compromised internal account impersonating Sofia Bennett (Cybersecurity & Platform Engineer)  
**Lure:** MFA device re-enrollment notice due to "policy update"  

### Attack Chain

1. Email arrives appearing to be from `sofia.bennett@onthehooks.com` informing Ethan his Entra ID MFA device needs to be re-enrolled due to a policy update
2. Link directs to a cloned O365 MFA setup page hosted on an attacker-controlled domain
3. Ethan submits credentials and current MFA token (real-time relay / AiTM attack)
4. Attacker captures valid session token, bypassing MFA entirely
5. Attacker authenticates to Ethan's M365 account from an external IP

### Why It Works

Ethan is non-technical. An MFA re-enrollment email from the internal cybersecurity engineer is entirely plausible and carries implied authority. There is no reason for Ethan to scrutinise it.

### Post-Access Objective

Full access to Ethan's M365 account. From there:

- **HubSpot** — customer PII, contact lists, engagement data
- **Zendesk** — support ticket history, customer communications
- **Outlook** — internal email access enabling further phishing as a trusted internal sender
- **Teams** — org structure intelligence, project details, access level reconnaissance
- **SharePoint community site** — newsletter assets, campaign data

### Lateral Movement Opportunities

- Send internal phishing as Ethan to Jordan or Avery Chen — passes all L1 header checks (legitimate internal account)
- HubSpot API token potentially reusable for external data exfiltration
- Teams message history reveals who has elevated access, pending projects, and system credentials shared informally

### Detection Signals

| Layer | Signal |
|---|---|
| L1 Technical | If spoofed: SPF/DKIM/DMARC failure, CrossTenant-AuthAs mismatch. If compromised account used: headers pass cleanly |
| L2 Behavioral | Unusual originating IP (not 10.0.1.62); atypical send time; new device fingerprint |
| L3 Contextual | Credential request combined with urgency; language inconsistent with Sofia's established communication style |

### Note on Compromised Account Variant

If the attacker uses a genuinely compromised internal account rather than a spoof, L1 detection fails entirely. Detection responsibility falls on L2 (IP/device anomaly) and L3 (language baseline deviation). This is the most realistic and hardest-to-detect variant and represents the primary stress test for the contextual analysis layer.

---

## Scenario 3 — BEC Wire Transfer via Internal Relay

**Target:** Ethan Brooks (as relay); Finance as ultimate target  
**Escalation Tier:** T4 (Critical)  
**Vector:** Spoofed or compromised Jordan Reyes account  
**Lure:** Urgent vendor payment request delegated to Ethan  

### Attack Chain

1. Attacker sends as Jordan (compromised account or convincing spoof) to Ethan
2. Email references a real event (Whistler Spring Series) and claims a vendor needs an urgent EFT payment to hold their booking
3. Jordan states she is "on a call" and asks Ethan to coordinate with finance directly
4. Ethan, accustomed to handling delegated logistics tasks from Jordan, forwards the request or contacts finance himself
5. If Ethan attempts to verify with Jordan directly, attacker can delay or intercept via a second spoofed reply

### Why It Works

Jordan delegating tasks to Ethan is normal baseline behaviour. The request is time-sensitive with a plausible business reason. Ethan is not authorising the payment — he is acting as a relay — which reduces his scrutiny. The real target (finance) receives the request from a trusted internal sender.

### Post-Access Objective

Direct financial fraud via fraudulent vendor payment. Secondary objective: if Ethan interacts with any links in the chain, credential compromise as a fallback.

### Detection Signals

| Layer | Signal |
|---|---|
| L1 Technical | If spoofed: sender domain mismatch, header anomalies. If compromised: headers pass |
| L2 Behavioral | Originating IP differs from Jordan's baseline (10.0.1.45); unusual send time |
| L3 Contextual | BEC language fingerprint — urgency, financial action, unavailability framing; deviates from Jordan's established communication patterns with Ethan |

---

## Scenario 4 — Malicious SharePoint Notification

**Target:** Jordan Reyes  
**Escalation Tier:** T2/T3 (Medium–High)  
**Vector:** Spoofed SharePoint or DocuSign notification email  
**Lure:** "Sponsor contract ready for your signature"  

### Attack Chain

1. Email arrives styled as a SharePoint file share notification or DocuSign envelope alert
2. Link redirects to a cloned SharePoint or O365 authentication page
3. Jordan re-authenticates, credentials and session token captured
4. Attacker gains access to Jordan's M365 account

### Why It Works

Jordan shares and receives SharePoint links as a core part of her daily workflow. A document-ready notification requires zero pretexting and fits naturally into her expected email volume.

### Post-Access Objective

Credential harvest and session token capture. Access to Jordan's SharePoint, Outlook, and partner-facing materials.

### Detection Signals

| Layer | Signal |
|---|---|
| L1 Technical | Destination URL does not match onthehooks.sharepoint.com; sender domain not Microsoft or onthehooks.com |
| L2 Behavioral | Notification-style email with no prior thread context; no established relationship with sending domain |
| L3 Contextual | Generic language lacking the event/sponsor specificity present in Jordan's real communications |

---

## Detection Layer Summary

| Scenario | Tier | L1 Headers | L2 Behavioral | L3 Contextual |
|---|---|---|---|---|
| Fake sponsor invoice | T3 | SPF/DKIM fail on lookalike domain | No prior sender history | Urgency + financial action |
| MFA reset (spoofed) | T4 | SPF/DKIM/DMARC fail | Unusual IP and send time | Credential request, atypical language |
| MFA reset (compromised) | T4 | Pass — hardest case | New IP/device anomaly | Language deviation from Sofia baseline |
| BEC wire transfer (spoofed) | T4 | Header anomalies | IP/time deviation from Jordan baseline | BEC language pattern |
| BEC wire transfer (compromised) | T4 | Pass — hardest case | IP deviation | BEC language vs Jordan baseline |
| Malicious SharePoint link | T2/T3 | URL/domain mismatch | No thread context | Generic vs personalised language |

---

## Key Detection Insight

The **compromised internal account** variants (Scenarios 2 and 3, compromised path) represent the most realistic and most difficult detection challenge. L1 technical analysis passes entirely. Detection depends on:

- **L2:** Originating IP differing from the persona's established workstation baseline, unusual send time, or new device fingerprint registered in Entra ID
- **L3:** Language and behavioural patterns deviating from the LLM's trained baseline for that sender — the primary reason the 1,000-email behavioral baseline dataset was built

This is the core value proposition of the contextual LLM layer: detecting attacks that bypass all technical controls by identifying that the *person* is not behaving like themselves.

---

## Next Steps

- Generate phishing email JSON dataset for each scenario using the existing schema (`onthehooks_email_baseline.json`) with injected header and behavioral anomalies
- Label each phishing sample with the appropriate escalation tier (`phishing_t2`, `phishing_t3`, `phishing_t4`)
- Feed labeled dataset into detection pipeline and measure true positive / false positive rates against the benign baseline
- Tune L3 prompt and scoring thresholds based on detection results

---

*All scenarios, personas, company environments, and email content in this document are entirely fictional and intended strictly for educational and academic cybersecurity research purposes as part of INFO49402 Capstone Group 26.*
