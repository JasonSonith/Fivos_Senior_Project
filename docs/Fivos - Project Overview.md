# Fivos - Multi-Agent AI System for Automated Medical Device Data Harvesting and Regulatory Data Validation

**Date:** 01.09.2026
**Client:** Doug Greene - doug.greene@fivoshealth.com
**Company:** Fivos, 8 Commerce Ave, West Lebanon, NH 03784

---

## Overview

### Background

The FDA's Global Unique Device Identification Database (GUDID) is the "source of truth" for medical devices, but discrepancies often exist between this database and the manufacturer's latest digital catalogs. These inconsistencies, ranging from mismatched dimensions to outdated manufacturer/brand names, can lead to inaccurate patient medical records, procurement errors and safety risks. Manually verifying thousands of entries against dynamic manufacturer websites is labor-intensive and error-prone.

### About Fivos

Fivos is an industry-leading provider of comprehensive data solutions, helping to transform patient care by providing real world data to medical registries and device manufacturers. By taking a holistic approach to data capture, insights, and action, we help drive innovation, improve outcomes, and lower costs for unique clinical workflows. Fivos' solutions include registry development and support for medical societies, along with custom data services and advanced reporting for device manufacturers.

### Goals

The system will follow a modular "Collect-Compare-Correct" workflow. To ensure the AI learns from the human reviewer, a feedback system must be implemented for AI model improvement over time.

1. **Develop Agent A (The Harvester):** An autonomous AI agent capable of navigating manufacturer websites, handling dynamic content, and extracting technical specifications into a centralized data lake.
2. **Develop Agent B (The Validator):** An AI agent that compares harvested data against GUDID records to identify discrepancies.
3. **Implement a HITL (Human-in-the-Loop) Interface:** A web dashboard for human experts to review AI-flagged exceptions, provide feedback, and refine the AI's logic through a closed-loop system.

---

## Communication Plan

The Fivos team works from various locations around the US and in Cairo, Egypt. Most meetings will be held remotely via Google Meet. The project sponsor, Doug Greene, is based in Mobile, AL, so it is possible to have some meetings on the USA campus.

### Project Kickoff Meeting

The Project Kickoff Meeting will be held remotely via Google Meet. The purpose of this meeting is to introduce the project to the team and answer any questions about the project. Additional background information on the project can be provided at this time.

### Requirements Gathering Meetings

Various meetings will be scheduled to elicit requirements from various stakeholders for the mockup tool. These meetings will be held remotely via Google Meet.

### Weekly Meetings

A brief weekly status meeting (aka stand up) will be held remotely via Google Meet to discuss progress on current tasks and next steps and to identify any impediments (aka blockers) to completing work.

### Ongoing Communications

We will set up a Google Chat space for this project for ongoing communications amongst the whole team. Communication via email is also available, but Google Chat is the preferred communication channel for the project.

---

## Milestones

### I. Design Requirements Document

The design requirements document identifies the user personas (actors) and use cases (tasks) for each user persona, and the scope of the project (i.e. what is and is not included). Assumptions and constraints may also be documented.

### II. Design Specification

The design specification document includes wireframe diagrams for screens/pages/forms/dialogs and a mapping of use case(s) to each wireframe diagram to ensure all use cases are covered.

### III. Final Report

The final report includes an assessment of the functional specifications, lessons learned during the application building process and recommendations on the future direction of the application.

---

## Requirements / Constraints

### Technology (Tech Stack)

- Ideally, all of the UI and AI coding will be written in Python, but other languages may be used to better suit the team's skillset, especially for the UI component. The UI tech stack can be any of the popular stacks (FastAPI/Django, MEAN/MERN, Next.js, etc.)
- Open Source AI, such as Ollama, running locally (dev PC or server) is preferable, but free-to-use cloud-based AI is acceptable.
- Open Source SQL databases, such as PostgreSQL or SQLite, running locally (dev PC or server) is preferable, but free-to-use cloud-based SQL databases are acceptable. For the data lake, an open source NoSQL database is preferable, but free-to-use cloud-based NoSQL databases are acceptable.
- Github or other git-based repositories are acceptable for source control.
