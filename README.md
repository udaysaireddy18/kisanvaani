# KisanVaani

KisanVaani is a voice-first assistant that helps Indian farmers report crop damage in their local language and generates a structured, insurer-ready crop-loss claim packet (JSON + PDF).

It now has **two interfaces over the same backend**:
- **Web demo (ready to deploy):** public form/chat-style UI for reporting damage, uploading photos, tracking claim state, and generating PDF.
- **WhatsApp bot (next phase):** existing `/webhook` + WhatsApp Cloud API integration can be enabled later by adding Meta credentials.

## What it does

1. Farmer reports damage by typing or speaking in the browser, with a chosen language (Hindi, English, Telugu, Tamil, Bengali, Marathi).
2. Backend extracts claim fields: crop, damage, village, date.
3. The web UI shows the extracted values in an editable review card; correct them and click **Save Details** before continuing.
4. Bot asks 1-2 follow-up questions if required fields are missing.
5. Farmer previews and uploads/sends 1-3 damage photos; type, size, dimensions, and sharpness are checked.
6. Claim becomes READY; operator generates a one-page insurer-ready PDF.
7. A status timeline shows Claim created → Details received → Photos uploaded → Claim ready → PDF generated with timestamps.

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

## Deploy to internet (Render free tier)

This repo includes `render.yaml` and `Procfile`, so Render can build and run the app automatically.

1. Push the code to GitHub (done: `main` contains the full app).
2. Sign up at [render.com](https://render.com) and connect your GitHub account.
3. Click **New > Blueprint** and select `udaysaireddy18/kisanvaani`.
4. Give the blueprint a name and click **Create Blueprint**. Render reads `render.yaml` and starts the web service with Gunicorn.
5. When the service shows **Live**, open the `onrender.com` URL from the dashboard. The web demo is at `/` and `/health` should return `{"status":"ok"}`.

Free-tier notes:

- Free web services sleep after inactivity; the first request after sleep can take 30-60 seconds.
- The filesystem is ephemeral: claims, photos, and PDFs are stored under `/tmp/kisanvaani` and reset whenever the service restarts or redeploys. This is fine for a public demo. For permanent data, upgrade the service to a paid plan and attach a persistent disk (or use a hosted database/storage).
- Custom domains are available on paid Render plans. On free, use the provided `onrender.com` URL.

WhatsApp/voice credentials (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `OPENAI_API_KEY`) are only needed when you enable the WhatsApp bot; they are not required for the web demo.

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

## Voice input and languages

- Choose a language in the web demo dropdown, click **🎙 Speak**, allow microphone access, speak the report, review the transcript in the box, then click **Send Message**.
- Voice recognition uses the browser's Web Speech API, so **Chrome or Edge** are recommended. No API key is needed for voice in the web demo.
- Bot replies follow the selected language. Crop/damage/village/date extraction supports keywords in all six supported languages.

## Photo preview and quality check

- Select or drag up to 3 photos in the web demo. Thumbnails, file names, dimensions, and file sizes appear before upload.
- The browser blocks non-images, files over 10 MB, and images smaller than 480x360.
- The backend also verifies the image is a valid JPG/PNG/WEBP and estimates sharpness. A likely-blurry photo returns a warning with an **Upload Anyway** option.
- Successful uploads return quality metrics in the JSON response.

## Web API endpoints (demo)

- `GET /` - web UI
- `GET /health` - health check
- `GET /api/claims` - list claims
- `GET /api/claims/<id>` - claim detail (includes a `timeline` array with timestamps)
- `PUT /api/claims/<id>/details` - `{crop, damage_type, village, incident_date, language?}` (review card save)
- `POST /api/web/messages` - `{phone, message, language?, claim_id?}`
- `POST /api/web/photos` - multipart form: `phone`, `photo`, `language?`, `claim_id?`, `force?` (accept blurry photo)
- `POST /api/claims/<id>/pdf` - generate PDF
- `GET /api/claims/<id>/pdf` - download PDF
- `GET /webhook`, `POST /webhook` - WhatsApp Cloud API

## Demo script

1. Open the web app.
2. Enter message: "Meri ganne ki fasal barish se kharab ho gayi, village Rampur."
3. Bot asks for date. Reply: "12/11/2026".
4. In **Review extracted details**, correct any field and click **Save Details**.
5. Bot asks for photos. Upload 1-2 photos.
6. Claim becomes READY; click Generate PDF / Download PDF.
7. See the status timeline and the claim in Recent Claims table.

## Scope boundaries

**In scope:** Web demo, WhatsApp webhook-ready backend, voice-to-text service, rule-based extraction, follow-up questions, photo capture, claim state machine, SQLite, PDF generation, seed/demo data.

**Out of scope:** Insurer/PMFBY API integration, claim approval/fraud scoring, custom speech model, full auth system.
"# kisanvaani" 
