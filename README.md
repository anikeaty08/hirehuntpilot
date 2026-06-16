# HireHuntPilot

`HireHuntPilot` is a local multi-agent orchestrator for discovering jobs, qualifying them, preparing application artifacts, and coordinating application workflows.

Current implementation focus:

- SQLite-backed task queue and event log
- Supervisor + specialized agents
- Encrypted local config
- CLI triggers for run, prepare, apply, doctor, and status
- Optional Google Sheets sync and notification adapters

## Install

```bash
pip install -e .
```
`RenderCV` is a required dependency. The project now expects Python 3.12+ and installs `rendercv[full]` as part of the base environment.

## Commands

```bash
hirehuntpilot init
hirehuntpilot setup
hirehuntpilot setup-status
hirehuntpilot setup-profile
hirehuntpilot setup-resume
hirehuntpilot setup-ai
hirehuntpilot setup-notifications
hirehuntpilot setup-portals
hirehuntpilot doctor
hirehuntpilot run
hirehuntpilot prepare
hirehuntpilot apply --dry-run
hirehuntpilot status
```

## Onboarding

`hirehuntpilot init` bootstraps the encrypted config, creates the local SQLite runtime workspace, and then launches staged setup. `hirehuntpilot setup` reruns the same onboarding flow later without resetting existing data.

The setup flow is split into phases so users can opt in, skip, or return later:

- profile
- resume
- ai
- notifications
- portals

The primary runtime state is local SQLite under `.hirehuntpilot/runtime.db`.

`hirehuntpilot setup-status` shows both saved setup states and live readiness checks.

## AI Setup

`hirehuntpilot setup-ai` provides the guided provider/model selection flow directly:

```bash
hirehuntpilot setup-ai
```

Supported provider paths in the guided setup:

- OpenAI API key
- Google Gemini API key
- Groq API key
- Mistral API key
- Local OpenAI-compatible server such as Ollama or LM Studio

The setup flow stores the API key in the encrypted config, lets you select from curated current model presets, supports custom model IDs, and verifies the provider/model before finishing.

## Resume Pipeline

The resume pipeline is RenderCV-based. `resume.json` is the canonical source profile. The staged resume setup collects structured profile data, optionally runs LLM-based normalization for spelling and clarity, stores the cleaned profile as JSON, and then the resume agent selects job-relevant content for each application, writes a job-specific RenderCV YAML file, and renders a PDF during `hirehuntpilot prepare`.

Example config:

```yaml
resume:
  mode: rendercv
  json_path: /path/to/resume.json
  rendercv_path: /path/to/resume_rendercv.yaml
  rendercv_theme: classic
```

`hirehuntpilot prepare` now treats the RenderCV render step as required. If the `rendercv` CLI is missing or PDF generation fails, preparation fails instead of silently falling back.

`hirehuntpilot prepare` also requires AI setup to be complete so resume tailoring is model-backed rather than falling back silently.
