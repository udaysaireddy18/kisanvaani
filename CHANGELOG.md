# Changelog

## 2026-11-25

- Added **Review & edit extracted details** to the web demo.
  - Crop, damage type, village, and incident date are shown in editable inputs after a message is processed.
  - **Save Details** writes corrections back to the claim, normalizes the date, recalculates missing fields/confidence/status, and resets the follow-up count.
  - Added `PUT /api/claims/<id>/details` and localized confirmation replies in all six languages.
- Configured this repository to use the GitHub noreply email so new commits are attributed to the account and counted in the contribution graph.

## 2026-11-24

- Verified the full local flow after server restarts: health check, web UI, language selection, follow-up replies, and PDF generation all work at `http://127.0.0.1:5000`.
- Added this changelog to record the project history. No application code changed today.

## 2026-11-23

- `3a735b5` — Understand short follow-up replies and flexible dates.
  - Bare village replies such as `रामपुर` / `Rampur` are now saved correctly.
  - Date replies accept `12/11/2026`, `12-11-26`, `12.11.2026`, `12 11 2026`, `12/11` (current year), `आज`, `कल`, `today`, and `yesterday`.

## 2026-11-22

- `4e201cd` — Hindi bot replies now use Devanagari script, and extraction understands Hindi-script words.
- `428e65b` — Added voice input and language selection (Hindi, English, Telugu, Tamil, Bengali, Marathi) to the web demo.
- `ff13cd4` — Fixed the claim state so it becomes READY after a photo, and made startup database initialization work on cloud hosts.
- `8a5e195` — Pushed the full KisanVaani application source to GitHub.
