# KisanVaani

KisanVaani is a voice-first assistant that helps Indian farmers report crop damage in their local language and generates a structured, insurer-ready crop-loss claim packet (JSON + PDF).

It now has **two interfaces over the same backend**:
- **Web demo (live on internet now):** public form/chat-style UI for reporting damage, uploading photos, tracking claim state, and generating PDF.
- **WhatsApp bot (next phase):** existing `/webhook` + WhatsApp Cloud API integration can be enabled later by adding Meta credentials.

## What it does

1. Farmer reports damage (text now; WhatsApp voice later).
2. Backend extracts claim fields: crop, damage, village, date.
3. Bot asks 1-2 follow-up questions if required fields are missing.
4. Farmer uploads/sends 1-3 damage photos.
5. Claim becomes READY; operator generates a one-page insurer-ready PDF.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11 + Flask |
| Web UI | Flask templates + vanilla JS/CSS |
| WhatsApp (future) | WhatsApp Cloud API webhook (`/webhook`) |
| Speech-to-text (WhatsApp phase) | OpenAI Whisper API |
| Database | SQLite via SQLAlchemy |
| Dashboard (legacy/local) | Streamlit |
| PDF | ReportLab |
| Deployment | Gunicorn + Render/any Python host |

## Project structure

```text
kisanvaani/
  app.py                  # Flask app: web UI, web API, WhatsApp webhook
  config.py
  requirements.txt
  Procfile
  render.yaml
  .env.example
  README.md
  templates/index.html
  static/css/style.css
  static/js/app.js
  db/
    models.py init_db.py session.py
  services/
    whatsapp.py stt.py extractor.py claim_flow.py web_api.py pdf_generator.py
  dashboard/streamlit_app.py
  scripts/seed_demo.py
  samples/ docs/
```

## Run locally (web demo)

```powershell
cd kisanvaani
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m db.init_db
python app.py
```

Open: `http://localhost:5000`

Optional seed data:
```powershell
python -m scripts.seed_demo
```

## Deploy to internet (Render - recommended for MVP)

This repo includes `render.yaml` and `Procfile`.

1. Push `kisanvaani` to a GitHub repo.
2. In Render, create **New > Blueprint** and select the repo.
3. Render will provision a web service + persistent disk (`/var/data`) for SQLite/media/PDFs.
4. Set/confirm env vars:
   - `DASHBOARD_PASSWORD` (for local Streamlit if used)
   - `WHATSAPP_VERIFY_TOKEN` (random secret; needed later for WhatsApp)
   - `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `OPENAI_API_KEY` (only when enabling WhatsApp/voice)
5. Deploy. Your public URL will serve the web demo at `/`.

**Important:** SQLite on cloud hosts needs a persistent disk. Without disk, data may be lost on redeploy/restart.

## Enable WhatsApp bot later (same backend)

The WhatsApp flow is already implemented; you only need to connect Meta:

1. Set in deployed environment:
   - `WHATSAPP_VERIFY_TOKEN`
   - `WHATSAPP_ACCESS_TOKEN`
   - `WHATSAPP_PHONE_NUMBER_ID`
   - `OPENAI_API_KEY` (for voice notes)
2. In Meta Developer Dashboard > WhatsApp > Configuration:
   - Callback URL: `https://<your-domain>/webhook`
   - Verify token: same as `WHATSAPP_VERIFY_TOKEN`
   - Subscribe to `messages`
3. Send a WhatsApp message/voice note/photo. The existing `claim_flow` handles it.

No redesign needed: web and WhatsApp both use the same extraction, state machine, DB, and PDF generation.

## Web API endpoints (demo)

- `GET /` - web UI
- `GET /health` - health check
- `GET /api/claims` - list claims
- `GET /api/claims/<id>` - claim detail
- `POST /api/web/messages` - `{phone, message, claim_id?}`
- `POST /api/web/photos` - multipart form: `phone`, `claim_id?`, `photo`
- `POST /api/claims/<id>/pdf` - generate PDF
- `GET /api/claims/<id>/pdf` - download PDF
- `GET /webhook`, `POST /webhook` - WhatsApp Cloud API

## Demo script

1. Open the web app.
2. Enter message: "Meri ganne ki fasal barish se kharab ho gayi, village Rampur."
3. Bot asks for date. Reply: "12/11/2026".
4. Bot asks for photos. Upload 1-2 photos.
5. Claim becomes READY; click Generate PDF / Download PDF.
6. See claim in Recent Claims table.

## Scope boundaries

**In scope:** Web demo, WhatsApp webhook-ready backend, voice-to-text service, rule-based extraction, follow-up questions, photo capture, claim state machine, SQLite, PDF generation, seed/demo data.

**Out of scope:** Insurer/PMFBY API integration, claim approval/fraud scoring, custom speech model, full auth system.
"# kisanvaani" 
