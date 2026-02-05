# Fivos - Medical Device Data Harvesting & Validation

A multi-agent AI system that automates the process of checking medical device data between manufacturer websites and the FDA's GUDID database.

Built by **Vibe Coders** for [Fivos](https://www.fivoshealth.com) as a senior design project (CIS 497).

## The Problem

The FDA maintains a database called GUDID (Global Unique Device Identification Database) that is supposed to be the single source of truth for medical device information. In practice, the data in GUDID often does not match what manufacturers have on their own websites. Things like wrong dimensions, outdated brand names, or mismatched model numbers can cause real problems with patient records and equipment ordering.

Right now, Fivos employees have to manually check thousands of entries by hand. That is slow, tedious, and easy to mess up. This project automates most of that work.

## How It Works

The system follows a **Collect, Compare, Correct** workflow using two AI agents and a review dashboard.

**Agent A (The Harvester)** crawls manufacturer websites, handles dynamic/JavaScript-rendered pages, and pulls out device specs. All of that data gets stored in a central data lake.

**Agent B (The Validator)** takes the harvested data and compares it against GUDID records. It flags anything that does not match, assigns a confidence score, and categorizes discrepancies by severity.

**The Review Dashboard (HITL)** is a web interface where human reviewers at Fivos can look at what the AI flagged. They see the GUDID value side by side with the manufacturer value and can approve, reject, or correct each item. Their decisions feed back into the system so it gets smarter over time.

## Tech Stack

| Layer | Tools |
|---|---|
| Language | **Python 3.13.7** |
| Web Scraping | Selenium / Playwright |
| AI | Ollama (open source, runs locally) |
| SQL Database | PostgreSQL or SQLite |
| NoSQL / Data Lake | MongoDB (or similar) |
| Frontend | React or Next.js |
| Version Control | Git / GitHub |

> Python 3.13.7 is the target runtime for all backend and AI agent code in this project. Make sure you have it installed before running anything.

## Project Structure

```
├── harvester/          # Agent A - web scraping and data extraction
├── validator/          # Agent B - GUDID comparison and discrepancy detection
├── dashboard/          # HITL review interface (frontend)
├── api/                # Backend API layer
├── db/                 # Database schemas and migrations
├── docs/               # Project documentation
└── README.md
```

## Key Features

- Automated scraping of manufacturer websites with retry logic and timeout handling
- Comparison of harvested data against FDA GUDID records
- Normalization layer to handle differences in units, formatting, and naming conventions
- Confidence scoring for flagged discrepancies
- Web dashboard for human review with filtering, sorting, and reason codes
- Feedback loop so reviewer decisions improve future validation runs
- Role-based access control (Reviewer vs Administrator)
- Audit logging for all reviewer actions and system events
- Reports and performance statistics

## Getting Started

### Prerequisites

- Python 3.13.7
- Node.js (for the frontend)
- PostgreSQL or SQLite
- MongoDB (optional, for the data lake)
- Git

### Installation

```bash
# Clone the repo
git clone https://github.com/your-org/fivos-project.git
cd fivos-project

# Set up Python virtual environment
python3.13 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Set up the frontend
cd dashboard
npm install
```

### Running the Agents

```bash
# Start the Harvester Agent
python harvester/main.py --manufacturer medtronic --mode catalog

# Start the Validator Agent
python validator/main.py --batch HR-10452
```

### Running the Dashboard

```bash
cd dashboard
npm run dev
```

## User Roles

**Reviewer** - Can view flagged discrepancies, approve/reject/correct items, and view reports.

**Administrator** - Can do everything a reviewer can, plus manage user accounts, import GUDID data, and view advanced system metrics.

## Team

| Name | Role |
|---|---|
| Wyatt Ladner | Developer |
| Jason Sonith | Developer |
| Ryan Tucker | Developer |
| Ralph Mouawad | Developer |
| Jonathan Gammill | Developer |

**Project Client:** Doug Greene, Fivos (doug.greene@fivoshealth.com)

## License

This project was built for Fivos as part of a senior design course. Contact the team or client for licensing details.
