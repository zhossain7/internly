
![Internly Dashboard](dashboard.png)

# Internly

I built Internly after struggling to track graduate and internship applications across too many tabs, screenshots, and notes. I kept missing deadlines and losing context between OA stages, interviews, and follow-ups, so I made a product that puts everything in one place and keeps the process clear.

Internly is a focused pipeline for internship and graduate-role tracking with built-in AI extraction for links, PDFs, and screenshots.

## What Internly Does

- Tracks roles by company, position, deadline, optional time, status, notes, and source link.
- Extracts fields from job links, uploaded PDFs, and screenshots using OCR and AI.
- Syncs upcoming deadlines automatically to Google Calendar.
- Sortable table with persistent sort preference, defaulting to nearest deadline.
- Inline deadline editing — click on the dashboard or double-click on the applications page.
- Prompts to update deadline whenever you change an application's status.
- Supports secure sign-in and guest mode.
- Exports data to a structured Excel spreadsheet.

## Product Flow

- Home: product overview and core capabilities.
- Dashboard (`/app`): quick add, extraction, momentum view, and inline deadline editing.
- Applications (`/applications`): full table view, filtering, sorting, export, and inline editing.
- Login (`/login`): account access or guest session.

## Run Locally

1. Install Python 3.10+.
2. Start Internly:

```bash
python app.py
```

3. Open `http://127.0.0.1:8000`.

Internly creates `internly.db` automatically in the project root. You can override the path with the `INTERNLY_DB_PATH` env var.

## Extraction Stack (Recommended)

- `tesseract` for OCR on images.
- `pdftotext` for text-based PDFs.
- `pdftoppm` + `tesseract` for scanned PDFs.

If these tools are not installed, you can still review and enter details manually.

## AI Extraction Modes

- `local`: local parser + OCR/PDF tooling.
- `gemini`: Gemini API for PDF/image extraction.
- `groq`: Groq API extraction (default model: `llama-3.3-70b-versatile`).
- `granite`: local Ollama extraction (configurable model via `OLLAMA_MODEL`).
- `auto`: uses Gemini if configured, then Groq if configured, then local.

Set via env vars in a `.env` file in the project root:

```env
EXTRACTION_MODE=auto
GEMINI_API_KEY=your_key_here
GROQ_API_KEY=your_key_here
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=your_model_here
INTERNLY_DB_PATH=/path/to/internly.db
```

## Google Calendar Sync

Internly can sync application deadlines to a Google Calendar automatically. See `internly-gcal-sync/` for the sync script and setup instructions. Requires a Google Cloud project with Calendar API enabled and a one-time OAuth setup.

## Notes

- Routes for dashboard and applications require a signed-in or guest session.
- Guest mode is temporary and does not persist data to the server database.
- Export is available for signed-in users; guests can still download the blank template.
- Extraction is heuristic-based, so review fields before saving.
