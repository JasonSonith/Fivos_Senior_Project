# Fivos — System Architecture Diagram

## Overview

This is a **system architecture diagram** — a high-level visual showing how all major components of the Fivos system connect and how data flows between them. This is the standard diagram type used to explain "how the software works at a high level" in design documents and presentations.

---

## Component Breakdown

### External Systems (Gray)
- **Manufacturer Websites** — Dynamic sites (Medtronic, Abbott, Boston Scientific, Gore, Cook, Shockwave, Cordis, Terumo) with JS-rendered content requiring custom adapters
- **FDA GUDID Database** — Source of truth for medical device identifiers, accessed via API or bulk download

### Harvester Agent (Orange)
- **Agent A: Harvester** — Autonomous AI agent using Playwright for browser automation. Wyatt handles browser control, Ryan builds per-site adapter configs
- **Normalization Pipeline** — Jason's 5-stage data cleaning engine:
  1. Parse HTML → BeautifulSoup tree
  2. Extract fields via CSS selectors
  3. Normalize units/names/dates/models/text
  4. Validate required fields + ranges + types
  5. Emit to data lake with metadata

### Data Storage (Yellow)
- **Data Lake (NoSQL)** — MongoDB for harvested device records with full provenance metadata
- **SQL Database** — PostgreSQL for validation results, user accounts, audit logs, discrepancy flags

### Validator Agent (Green)
- **Agent B: Validator** — Compares harvested data against GUDID records, assigns confidence scores, flags discrepancies by severity

### Human-in-the-Loop (Purple)
- **HITL Dashboard** — Web interface for reviewers to examine flagged discrepancies, approve/reject/correct with reason codes
- **Feedback Loop** — Reviewer decisions feed back to improve Validator accuracy over time

### Security Layer (Red)
- Cross-cutting: CredentialManager, HTML sanitization, login/permissions, audit logging, rate limiting

---

## Data Flow Summary

```
Manufacturer Websites
        │
        ▼  (Raw HTML)
   Harvester Agent
        │
        ▼  (Extracted fields)
  Normalization Pipeline
        │
        ▼  (Clean records)
     Data Lake ──────────► Validator Agent ◄──── FDA GUDID
                                │
                                ▼  (Validation results)
                           SQL Database
                                │
                                ▼  (Flagged discrepancies)
                          HITL Dashboard
                                │
                                ▼  (Reviewer decisions)
                           Feedback Loop ───► Validator (improved logic)
```

---

## Diagram Types Reference

For future diagrams you might need for the capstone:

| Diagram Type | Purpose | When to Use |
|---|---|---|
| **System Architecture** | High-level components + connections | Design spec, presentations, stakeholder communication |
| **Data Flow Diagram (DFD)** | How data moves through the system | Requirements docs, data pipeline documentation |
| **Sequence Diagram** | Time-ordered interactions between components | Use case implementation details |
| **Component Diagram (UML)** | Formal module structure + interfaces | Detailed design specification |
| **Entity-Relationship (ER)** | Database schema + relationships | Database design |
| **Deployment Diagram** | Where components run (servers, containers) | Infrastructure planning |

---

## File Reference

The interactive React diagram is saved as `fivos-architecture.jsx`. It's clickable — each component shows detailed descriptions when selected.
