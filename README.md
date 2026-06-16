# HireHuntPilot

HireHuntPilot is a local AI-assisted job application pipeline built around the `hirehunt` discovery framework.

It is designed to:
- discover jobs from configured portals
- enrich job descriptions and application links
- score jobs against your profile with an LLM
- tailor resumes and cover letters per job
- launch browser-driven application flows

## Current Branding

The active package and CLI names are:
- `hirehuntpilot`
- `hirepilot`

The codebase has been renamed around `hirehuntpilot`, and discovery is wired to `hirehunt`.

## How Discovery Works

The active discovery stage uses `hirehunt`, not `jobspy`.

Current discovery path:
- [src/hirehuntpilot/discovery/hirehunt.py](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/discovery/hirehunt.py)
- [src/hirehuntpilot/pipeline.py](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/pipeline.py)

Configured sources can include:
- `linkedin`
- `naukri`
- `indeed`
- `internshala`
- `unstop`
- `shine`

If `hirehunt` is not installed or live discovery fails, the current implementation falls back to synthetic sample jobs so the pipeline can still run.

## Project Layout

Main package:
- [src/hirehuntpilot](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot)

Important modules:
- [src/hirehuntpilot/cli.py](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/cli.py): CLI entrypoint
- [src/hirehuntpilot/config.py](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/config.py): app paths and runtime config
- [src/hirehuntpilot/database.py](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/database.py): SQLite schema and stats
- [src/hirehuntpilot/pipeline.py](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/pipeline.py): stage orchestration
- [src/hirehuntpilot/discovery/hirehunt.py](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/discovery/hirehunt.py): `hirehunt` discovery integration
- [src/hirehuntpilot/enrichment/detail.py](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/enrichment/detail.py): enrichment
- [src/hirehuntpilot/scoring](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/scoring): scoring, tailoring, cover letter, PDF stages
- [src/hirehuntpilot/apply](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/apply): browser/application flow

## Requirements

- Python `3.11+`
- Chrome or Chromium for browser-driven apply flows
- Node.js / `npx` for Playwright MCP usage in apply flows
- Claude Code CLI for the autonomous apply stage
- An LLM provider for scoring/tailoring:
  - `GEMINI_API_KEY`, or
  - `OPENAI_API_KEY`, or
  - `LLM_URL` for a local OpenAI-compatible model

Optional:
- `hirehunt` Python package for live job discovery

## Install

Standard install:

```bash
pip install -e .
```

This exposes:

```bash
hirehuntpilot
hirepilot
```

If you want a local virtual environment:

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

## First Run

Initialize the workspace:

```bash
hirehuntpilot init
```

This creates application data under:
- default: `~/.hirehuntpilot`
- override with: `HIREHUNTPILOT_DIR`

Example using a repo-local runtime folder:

```powershell
$env:HIREHUNTPILOT_DIR=(Join-Path (Get-Location) ".runtime")
hirehuntpilot init
```

## Commands

### Doctor

Verify environment and setup:

```bash
hirehuntpilot doctor
```

### Run

Run the pipeline:

```bash
hirehuntpilot run
```

Run only discovery:

```bash
hirehuntpilot run discover
```

Dry-run discovery:

```bash
hirehuntpilot run --dry-run discover
```

Run selected stages:

```bash
hirehuntpilot run discover enrich
hirehuntpilot run score tailor cover
```

### Apply

Run browser-driven application flow:

```bash
hirehuntpilot apply
```

Dry run:

```bash
hirehuntpilot apply --dry-run
```

Apply to a specific URL:

```bash
hirehuntpilot apply --url "https://example.com/job"
```

### Status

```bash
hirehuntpilot status
```

### Dashboard

```bash
hirehuntpilot dashboard
```

## Pipeline Stages

The current pipeline stages are:

1. `discover`
2. `enrich`
3. `score`
4. `tailor`
5. `cover`
6. `pdf`

`discover` is currently routed through the `hirehunt` integration.

## Search Configuration

Example search config lives at:
- [src/hirehuntpilot/config/searches.example.yaml](/abs/path/C:/Users/anike/Desktop/hirehunterpilot/src/hirehuntpilot/config/searches.example.yaml)

It supports:
- `queries`
- `locations`
- `sources`
- `defaults.results_per_source`
- `defaults.hours_old`

Example source list:

```yaml
sources:
  - linkedin
  - naukri
  - indeed
  - internshala
  - unstop
  - shine
```

## Runtime Data

By default the app stores runtime data under `~/.hirehuntpilot`.

Important files:
- `runtime.db`: SQLite database
- `profile.json`: profile data
- `resume.txt`: base resume text
- `.env`: API keys and LLM config
- `searches.yaml`: search config
- `tailored_resumes/`: generated tailored resumes
- `cover_letters/`: generated cover letters
- `logs/`: pipeline/apply logs

## Notes

- Discovery is actively wired to `hirehunt`.
- Legacy imported discovery modules have been removed. The active discovery path is `hirehunt` only.
- The current app is runnable as `hirehuntpilot`, but parts of the broader architecture still reflect the imported upstream codebase and may need further integration work.

## Verified Commands

The following were smoke-tested successfully in a clean local venv during integration:

```powershell
.\.venvtest\Scripts\python.exe -m hirehuntpilot --help
.\.venvtest\Scripts\python.exe -m hirehuntpilot doctor
$env:HIREHUNTPILOT_DIR=(Join-Path (Get-Location) ".runtime")
.\.venvtest\Scripts\python.exe -m hirehuntpilot run --dry-run discover
.\.venvtest\Scripts\python.exe -m hirehuntpilot run discover
```

## Next Recommended Work

- remove or refactor remaining unused legacy discovery modules
- align the apply layer with your preferred multi-agent orchestration model
- restore or rebuild richer chat/agent behavior if you want the older interactive flow back on top of this base
