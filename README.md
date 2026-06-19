# HireHuntPilot

HireHuntPilot is a local AI-assisted job pipeline built on top of `hirehunt`.

It does four main things:
- discover jobs from configured portals through `hirehunt`
- enrich postings with full descriptions and apply links
- score and tailor applications with your configured LLM
- launch browser-driven apply flows for jobs that are ready

## What It Uses

### Discovery

Discovery is `hirehunt`-only.

Configured sources can include:
- `linkedin`
- `naukri`
- `indeed`
- `internshala`
- `unstop`
- `shine`

Active integration:
- [src/hirehuntpilot/discovery/hirehunt.py](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/discovery/hirehunt.py)

### Runtime Storage

Local runtime data lives under `~/.hirehuntpilot` by default.

Important files:
- `runtime.db` — SQLite source of truth
- `profile.json` — applicant profile
- `resume.txt` — base resume text
- `searches.yaml` — search config
- `tailored_resumes/` — generated job-specific resumes
- `cover_letters/` — generated cover letters
- `logs/` — runtime logs
- `secrets.json` — encrypted local secrets on Windows

### AI Providers

The setup flow supports:
- `anthropic`
- `groq`
- `openai`
- `gemini`
- `local` OpenAI-compatible endpoints

Secrets like API keys are stored encrypted in the local app directory on Windows via DPAPI. Non-secret config stays in `.env`.

## Install

```bash
pip install -e .
```

CLI entrypoints:

```bash
hirehuntpilot
hirepilot
```

If you want a local virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

## First Run

Run the setup wizard:

```bash
hirehuntpilot init
```

This sets up:
- your resume and profile
- search queries and target locations
- your LLM provider and model
- encrypted local secret storage for API keys
- optional auto-apply dependencies

Use a repo-local runtime folder if you want:

```powershell
$env:HIREHUNTPILOT_DIR=(Join-Path (Get-Location) ".runtime")
hirehuntpilot init
```

## Main Commands

### Check setup

```bash
hirehuntpilot doctor
```

### Run discovery

```bash
hirehuntpilot run discover
```

### Run enrichment

```bash
hirehuntpilot run enrich
```

### Run the full pipeline

```bash
hirehuntpilot run
```

### Run selected AI stages

```bash
hirehuntpilot run score tailor cover pdf
```

### Run browser apply

```bash
hirehuntpilot apply
```

Dry run:

```bash
hirehuntpilot apply --dry-run
```

### Check pipeline status

```bash
hirehuntpilot status
```

### Open dashboard

```bash
hirehuntpilot dashboard
```

## Pipeline Stages

Stages run in this order:

1. `discover`
2. `enrich`
3. `score`
4. `tailor`
5. `cover`
6. `pdf`

The `discover` stage now shows a styled preview table with source, location, and job URL so you can inspect live results quickly.

## Search Config

Example file:
- [src/hirehuntpilot/config/searches.example.yaml](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/config/searches.example.yaml)

It supports:
- `queries`
- `locations`
- `sources`
- `defaults.results_per_source`
- `defaults.hours_old`

Example:

```yaml
sources:
  - linkedin
  - naukri
  - indeed
  - internshala
  - unstop
  - shine
```

## Requirements

- Python `3.11+`
- Chrome or Chromium for browser apply flows
- Node.js / `npx` for Playwright MCP usage
- Claude Code CLI for the autonomous apply stage
- `hirehunt==0.5.0`

## Notes

- Discovery is routed through `hirehunt`, not the older imported discovery adapters.
- SQLite is the main runtime store.
- Secrets are not supposed to be kept in plaintext `.env` during normal setup.
