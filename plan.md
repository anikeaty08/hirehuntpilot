Build a fully open-source, local single-user Python CLI package called
`hirehuntpilot` that acts as an autonomous job application agent.

It uses the `hirehunt` PyPI package (https://pypi.org/project/hirehunt/)
for job searching across Indian portals and automates the full pipeline:
search → resume tailoring → apply → notify → track.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PRODUCT BOUNDARY (V1 — DO NOT EXCEED)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Local, single-user CLI only
- One config file, one resume base, one Google Sheet
- One linked Telegram chat (single user, not a multi-user bot)
- One set of portal browser sessions
- No hosted backend, no multi-user bot architecture
- No plugin system yet
- No autonomous submission without --dry-run verified first
- Portal support in v1: Naukri + Internshala (Shine + Unstop later)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 PACKAGE STRUCTURE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

hirehuntpilot/
├── hirehuntpilot/
│   ├── __init__.py
│   ├── cli.py                  ← All CLI commands via Typer
│   ├── config.py               ← AES-256 encrypted config load/save/update
│   ├── doctor.py               ← Full health check suite
│   ├── search.py               ← hirehunt SearchEngine wrapper
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── adapter.py          ← Unified AI interface
│   │   ├── tailorer.py         ← Resume tailoring per job
│   │   └── chatgpt_auth.py     ← Playwright ChatGPT web session
│   ├── resume/
│   │   ├── __init__.py
│   │   ├── extractor.py        ← PDF text extraction via PyMuPDF
│   │   ├── builder.py          ← LaTeX → PDF via pdflatex + Jinja2
│   │   ├── updater.py          ← Add skills/exp, recompile
│   │   └── templates/          ← 10–50 Jinja2-ified .tex templates
│   ├── browser/
│   │   ├── __init__.py
│   │   ├── session.py          ← Playwright login + persistent sessions
│   │   └── applier.py          ← Form detection, fill, upload, submit
│   ├── storage/
│   │   ├── __init__.py
│   │   └── sheets.py           ← Google Sheets CRUD + dedup
│   └── notifiers/
│       ├── __init__.py
│       ├── telegram.py         ← Notifications + remote trigger commands
│       └── whatsapp.py         ← Twilio WhatsApp notifications
├── pyproject.toml
├── README.md
└── LICENSE                     ← MIT

App directories (created on first run):
~/.hirehuntpilot/
├── config.yaml                 ← AES-256 encrypted
├── resume.json                 ← Structured resume data
├── base_resume.pdf             ← Original uploaded or built PDF
├── sessions/                   ← Playwright browser sessions per portal
│   ├── naukri/
│   ├── internshala/
│   └── chatgpt/
├── resumes/                    ← Versioned tailored resumes per job
│   └── resume_v1_{job_id}.pdf
├── screenshots/                ← Apply confirmation screenshots
└── logs/                       ← Structured logs per run

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⚙️ CLI COMMANDS (FULL SURFACE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

pip install hirehuntpilot
playwright install chromium

hirehuntpilot init                  ← One-time full setup wizard
hirehuntpilot doctor                ← Validate all integrations

hirehuntpilot run                   ← Search + discover jobs
hirehuntpilot run -w 4              ← 4 parallel search workers

hirehuntpilot apply                 ← Tailor + apply pipeline
hirehuntpilot apply -w 3            ← 3 parallel Playwright browsers
hirehuntpilot apply --dry-run       ← Simulate, do not submit
hirehuntpilot apply --headed        ← Visible browser for debugging

hirehuntpilot resume update         ← Add skills/exp, recompile PDF

hirehuntpilot telegram test         ← Send test message to linked chat
hirehuntpilot telegram relink       ← Change bot token or chat_id
hirehuntpilot telegram disable      ← Turn off Telegram notifications

hirehuntpilot status                ← (optional v1) quick summary
hirehuntpilot config show           ← (optional v1) print decrypted config
hirehuntpilot sessions refresh      ← (optional v1) re-login all portals

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔐 PHASE 1: CONFIG + ENCRYPTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

File: hirehuntpilot/config.py

- AES-256 encryption via cryptography (Fernet)
- Master key derived from machine ID + user salt
- Config schema sections:
    personal:        name, email, phone, linkedin, github, portfolio
    ai:              provider, api_key, model, base_url (for Ollama)
    resume:          mode (pdf|latex), base_pdf_path, json_path, template_id
    preferences:     role, cities[], skills[], experience_min, experience_max,
                     salary_min, job_type, work_mode, sources[],
                     exclude_keywords[], exclude_companies[]
    portals:         naukri{email,password}, internshala{email,password}
    telegram:        enabled, bot_token, chat_id
    whatsapp:        enabled, account_sid, auth_token, from_number, to_number
    sheets:          spreadsheet_id, service_account_json_path

Methods:
    load() → dict
    save(config: dict)
    update(section: str, data: dict)
    validate() → list[str]   ← returns list of missing/invalid fields

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🧙 PHASE 2: `hirehuntpilot init` WIZARD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Full interactive CLI wizard using Rich prompts. Saves to config on completion.
If config already exists, ask: "Config found. Update existing or start fresh?"

STEP 1 — PERSONAL INFO
  Collect: name, email, phone, LinkedIn, GitHub, portfolio URL

STEP 2 — AI PROVIDER
  Show menu:
    [1] Claude (Anthropic)
    [2] GPT-4o (OpenAI)
    [3] Gemini Pro (Google)
    [4] Groq (free, fast)
    [5] Ollama (local, self-hosted)
    [6] ChatGPT Web (browser login, no API key needed)

  For 1–4: prompt for API key, run a test completion, confirm working
  For 5: prompt for base_url + model name, test via ollama API
  For 6: launch Playwright → open chat.openai.com → user logs in manually
          → save session to ~/.hirehuntpilot/sessions/chatgpt/
          → verify session works

STEP 3 — RESUME SETUP
  Ask: "Upload existing PDF or build from scratch with LaTeX?"

  OPTION A — PDF UPLOAD:
    - User provides path to PDF
    - PyMuPDF extracts full text
    - AI parses into structured JSON:
      { name, email, phone, linkedin, github, summary,
        education[], experience[], projects[],
        skills[], certifications[], achievements[] }
    - Confirm parsed data with user, allow corrections
    - Save JSON to ~/.hirehuntpilot/resume.json
    - Copy PDF to ~/.hirehuntpilot/base_resume.pdf

  OPTION B — LATEX BUILD:
    - Collect all fields interactively:
        personal info, photo path (optional),
        education (institution, degree, year, GPA),
        work experience (company, role, dates, bullet points),
        projects (name, tech stack, description, URL),
        skills (categorized: languages, frameworks, tools, platforms),
        certifications, achievements, hobbies (optional)
    - Show template list (numbered, with one-line description each)
    - User picks template number
    - Jinja2 renders .tex file with user data
    - pdflatex compiles → ~/.hirehuntpilot/base_resume.pdf
    - Print path and confirm

STEP 4 — JOB PREFERENCES
  Collect:
    - Target role/title (e.g. "Python Developer")
    - Target cities (multi, e.g. "Bangalore, Mumbai, Remote")
    - Key skills (comma separated)
    - Experience: min years, max years
    - Minimum salary (INR, 0 for fresher/internship)
    - Job type: job / internship / both
    - Work mode: remote / hybrid / onsite / any
    - Job portals to search: Naukri, Internshala (v1), Shine, Unstop (later)
    - Keywords to exclude
    - Companies to exclude

STEP 5 — PORTAL CREDENTIALS
  For each selected portal:
    - Email + password
    - Stored AES-256 encrypted
    - Playwright logs in, verifies session, saves to sessions/

STEP 6 — TELEGRAM (OPTIONAL)
  Ask: "Enable Telegram notifications and remote control? (Y/n)"
  If yes:
    - Prompt: bot token (get from @BotFather)
    - Instruction: "Open Telegram, start a chat with your bot, send /start"
    - CLI polls for first message → captures chat_id automatically
    - Sends test message: "✅ HireHuntPilot linked successfully!"
    - If user skips: mark disabled, can relink later with `telegram relink`

STEP 7 — WHATSAPP (OPTIONAL)
  Ask: "Enable WhatsApp notifications via Twilio? (Y/n)"
  If yes:
    - Collect: account_sid, auth_token, from_number, to_number
    - Send test message to verify

STEP 8 — GOOGLE SHEETS
  Ask: "Set up Google Sheets for job tracking? (Y/n)"
  If yes:
    - Prompt: path to service account JSON
    - Prompt: Spreadsheet ID (user creates and shares with service account)
    - Test: read/write a dummy row, delete it, confirm access
    - Initialize headers if sheet is empty

  Show final summary of all configured settings.
  Save encrypted config.
  Print: "✅ Setup complete! Run `hirehuntpilot doctor` to verify everything."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🩺 PHASE 3: `hirehuntpilot doctor`
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Print a Rich table of checks with ✅ / ❌ / ⚠️:

✅ Config file exists and decrypts successfully
✅ All required config fields present
✅ AI provider reachable (test completion: "Say OK")
✅ Playwright installed
✅ Chromium available
✅ pdflatex installed (only if LaTeX mode)
✅ Base resume PDF exists
✅ Naukri session valid (open portal, check login state)
✅ Internshala session valid
✅ Google Sheets readable and writable
✅ Telegram bot reachable (send test message)
✅ WhatsApp reachable (send test message)
✅ hirehunt test search returns at least 1 result

Print overall: "X/Y checks passed" and next steps if any failed.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔍 PHASE 4: `hirehuntpilot run`
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Load config
2. Build JobProfile from preferences:
   JobProfile(
     skills=[...],
     experience_years=N,
     preferred_titles=[...],
     preferred_cities=[...],
     min_salary=N,
     fresher=bool
   )
3. Build JobQuery:
   JobQuery(
     role=config.role,
     sources=config.sources,       ← ["naukri","internshala"]
     cities=config.cities,
     skills=config.skills,
     experience_min=config.exp_min,
     salary_min=config.salary_min,
     results_wanted=100,
     profile=profile,
     fetch_descriptions=True,
     country="India"
   )
4. Call SearchEngine.search(query) → ScrapeResult
5. Read existing source_job_ids from Google Sheets
6. Filter: keep only jobs NOT already in Sheets
7. Sort by match_score descending
8. Write new jobs to Sheets with status=DISCOVERED
9. Send Telegram + WhatsApp summary:
   "🔍 Hunt Complete!
    Found: 47 | New: 23 | Already seen: 24
    Top: Senior Python Dev @ TCS | Bangalore | 94% match
    Run `hirehuntpilot apply` to start applying!"

-w N flag: spawn N parallel SearchEngine workers, one per source

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📄 PHASE 5: GOOGLE SHEETS SCHEMA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Columns (initialize on first use):
  source_job_id   ← dedup key, never apply twice to same ID
  title
  company
  source          ← naukri / internshala / shine / unstop
  location
  work_mode
  job_kind        ← job / internship
  experience
  salary
  stipend
  skills
  match_score
  easy_apply      ← True / False
  job_url
  apply_url
  status          ← DISCOVERED / APPLIED / FAILED / MANUAL_REQUIRED / SKIPPED
  discovered_at
  applied_at
  resume_version  ← which tailored PDF was used
  screenshot_path
  notes

Status transitions:
  DISCOVERED → APPLIED (success)
  DISCOVERED → FAILED (error during apply)
  DISCOVERED → MANUAL_REQUIRED (easy_apply=False or unsupported form)
  DISCOVERED → SKIPPED (user manually skipped)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🧠 PHASE 6: AI ADAPTER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

File: hirehuntpilot/ai/adapter.py

class AIAdapter:
  Unified interface regardless of provider.
  Instantiated from config at runtime.

  Supported providers:
    - anthropic   → anthropic SDK
    - openai      → openai SDK
    - gemini      → google-generativeai SDK
    - groq        → groq SDK
    - ollama      → HTTP to local Ollama server
    - chatgpt_web → Playwright session scraper

  Methods:
    tailor_resume(job: Job, resume_text: str) → str
      Prompt: "Given this resume and job description, make MINOR
      keyword-aligned edits only. Reorder skills to front-load
      job keywords. Tweak 2-3 bullet points to mirror job language.
      Update the summary line to mention the role and company.
      Do NOT add false experience. Do NOT hallucinate. Return
      only the modified resume text."

    generate_cover_letter(job: Job, resume_text: str) → str
      Prompt: "Write a short 3-paragraph cover letter for this
      job application. Use the resume for context. Be specific,
      confident, concise. No generic filler."

    answer_question(question: str, job: Job, resume_text: str) → str
      Prompt: "Answer this job application question honestly
      using the resume for context. Be specific, professional,
      under 150 words: {question}"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📝 PHASE 7: RESUME SYSTEM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EXTRACTOR (PDF upload path):
  - PyMuPDF (fitz) reads PDF
  - AI structures text into resume.json
  - Fields: name, email, phone, linkedin, github, summary,
    education[], experience[], projects[], skills[],
    certifications[], achievements[]

BUILDER (LaTeX path):
  - Templates stored as Jinja2-ified .tex files
  - template_01_jake.tex, template_02_awesome.tex, etc.
  - Each has matching preview description
  - Jinja2 renders template with resume.json data
  - subprocess runs: pdflatex -output-directory=... resume.tex
  - Output: ~/.hirehuntpilot/base_resume.pdf

TAILORING (every single application, both paths):
  - AI makes MINOR changes to resume.json content
  - If LaTeX mode: re-render template + recompile → fresh PDF
  - If PDF mode: generate tailored cover letter + answer sheet
  - Save as: ~/.hirehuntpilot/resumes/resume_v{n}_{job_id}.pdf
  - n increments per application for full audit trail
  - Original base_resume.pdf NEVER modified

hirehuntpilot resume update:
  - Show current resume.json summary
  - Ask what to update: skills / experience / projects / education / all
  - Collect new data interactively
  - Update resume.json
  - If LaTeX mode: recompile and show new PDF path

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 PHASE 8: BROWSER SESSIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

File: hirehuntpilot/browser/session.py

- Playwright async with persistent browser context
- One context directory per portal:
    ~/.hirehuntpilot/sessions/naukri/
    ~/.hirehuntpilot/sessions/internshala/
- Login flow per portal:
    load saved context →
    navigate to portal →
    check if already logged in →
    if not: fill credentials, submit, wait for dashboard →
    save context
- Expose: get_page(portal) → Playwright Page (logged in, ready)
- Re-login automatically if session expired

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✍️ PHASE 9: APPLY ENGINE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

File: hirehuntpilot/browser/applier.py

For each DISCOVERED job in Sheets (sorted by match_score desc):

1. TAILOR RESUME
   - Pass job + base resume text to AIAdapter.tailor_resume()
   - Recompile PDF if LaTeX mode
   - Save versioned PDF

2. VISIT JOB PAGE
   - Open job.job_url in Playwright
   - Read full description, requirements, deadline

3. APPLY DECISION
   IF job.easy_apply == True:
     - Navigate to job.apply_url
     - Detect form fields on page
     - Fill each field:
         name, email, phone → from config
         resume upload → tailored PDF
         cover letter field → AIAdapter.generate_cover_letter()
         open text question → AIAdapter.answer_question()
         dropdowns → match from config preferences
     - IF --dry-run:
         print all field values, do NOT submit
     - ELSE:
         submit form
         wait for confirmation
         take screenshot → save to screenshots/

   IF job.easy_apply == False:
     - Mark MANUAL_REQUIRED in Sheets
     - Notify via Telegram:
       "⚠️ Manual apply needed:
        [Title] @ [Company] → [apply_url]"

4. UPDATE SHEETS
   - status: APPLIED / FAILED / MANUAL_REQUIRED
   - applied_at: timestamp
   - resume_version: which PDF was used
   - screenshot_path: path to confirmation

5. NOTIFY
   Success:
   "✅ Applied!
    Role: [title]
    Company: [company]
    Location: [location]
    Match: [score]%
    Salary: [compensation]
    Source: [source]
    URL: [apply_url]"

   Failure:
   "❌ Apply failed
    Role: [title] @ [company]
    Reason: [error]
    Action: Check logs or run `hirehuntpilot doctor`"

Flags:
  -w N         → N parallel Playwright browser instances
  --dry-run    → simulate only, print field values, no submit
  --headed     → visible browser window for debugging

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📬 PHASE 10: NOTIFICATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

TELEGRAM (notifiers/telegram.py):
  - Single user, single chat_id
  - send_message(text) → send to configured chat_id
  - Used for: run summary, apply success/fail, manual alerts, errors
  - Remote trigger: bot listens for commands from that chat_id only:
      /run    → triggers hirehuntpilot run in background
      /apply  → triggers hirehuntpilot apply
      /status → returns quick summary from Sheets
      /pause  → pauses scheduled runs (if APScheduler used)
  - Reject all commands from unknown chat_ids

WHATSAPP (notifiers/whatsapp.py):
  - Twilio client
  - send_message(text) → sends to configured to_number
  - Same notification events as Telegram
  - Optional, gracefully skipped if not configured

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔧 TECH STACK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Core:         hirehunt, Python 3.11+
CLI:          typer, rich
Browser:      playwright (async, Chromium)
AI:           anthropic, openai, google-generativeai, groq, ollama (HTTP)
Resume PDF:   pymupdf (fitz)
LaTeX:        jinja2 + pdflatex (system dependency)
Sheets:       gspread, google-auth
Telegram:     python-telegram-bot
WhatsApp:     twilio
Encryption:   cryptography (AES-256 Fernet)
Config:       pyyaml
Scheduling:   apscheduler (optional, for auto-run)
Packaging:    pyproject.toml (hatchling build backend)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 IMPLEMENTATION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1.  Every file fully implemented — no stubs, no TODOs, no pass
2.  AES-256 encrypt all credentials at rest in config.yaml
3.  Google Sheets is single source of truth for job tracking
4.  Dedup is strict: never apply to same source_job_id twice ever
5.  Resume tailoring: MINOR changes only, never hallucinate
6.  Playwright headless by default, --headed for debug
7.  All errors: catch, log to logs/, notify via Telegram if configured
8.  Rich terminal output everywhere: spinners, tables, colored status
9.  MIT License
10. Works on: macOS, Linux, Windows (WSL)
11. pyproject.toml entrypoint:
    [project.scripts]
    hirehuntpilot = "hirehuntpilot.cli:app"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📦 pyproject.toml DEPENDENCIES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

dependencies = [
  "hirehunt",
  "typer[all]",
  "rich",
  "playwright",
  "anthropic",
  "openai",
  "google-generativeai",
  "groq",
  "pymupdf",
  "gspread",
  "google-auth",
  "python-telegram-bot",
  "twilio",
  "cryptography",
  "pyyaml",
  "jinja2",
  "apscheduler",
  "requests",
]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📖 README MUST COVER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- What it is and what it does
- Install: pip install hirehuntpilot + playwright install chromium
- System deps: pdflatex (optional, for LaTeX resume mode)
- Full init walkthrough (step by step)
- Doctor usage and what each check means
- run and apply usage with flags
- Telegram linking flow + relink + test
- Resume modes: PDF upload vs LaTeX build
- How resume tailoring works (minor edits, no hallucination)
- Google Sheets setup (service account, share sheet)
- Sheets schema table
- Architecture diagram (ASCII)
- Limitations (v1 portal support, easy_apply only for auto)
- Contributing guide
- License: MIT