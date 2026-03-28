
![Internly Dashboard](dashboard.png)

# Internly

I built Internly after struggling to track graduate and internship applications across too many tabs, screenshots, and notes. I kept missing deadlines and losing context between OA stages, interviews, and follow-ups, so I made a product that puts everything in one place and keeps the process clear.

Internly is a focused pipeline for internship and graduate-role tracking with built-in extraction for links, PDFs, and screenshots.

## What Internly Does

- Tracks roles by company, position, deadline, optional time, status, notes, and source link.
- Captures deadline time in Quick Add when applicable (`HH:MM`).
- Extracts useful fields from job links (HTML, PDF, and image links auto-detected).
- Extracts from uploaded PDFs and screenshots using OCR fallback where needed.
- Supports secure sign-in and guest mode.
- Exports your data to a structured Excel spreadsheet, including deadline date/time columns.

## Product Flow

- Home: product overview and core capabilities.
- Dashboard (`/app`): quick add, extraction, and momentum view.
- Applications (`/applications`): full table view, filtering, sorting, and export.
- Login (`/login`): account access or guest session.

## Run Locally

1. Install Python 3.10+.
2. Start Internly:

```bash
python app.py
```

3. Open `http://127.0.0.1:8000`.

Internly creates `internly.db` automatically in the project root.

## Extraction Stack (Recommended)

- `tesseract` for OCR on images.
- `pdftotext` for text-based PDFs.
- `pdftoppm` + `tesseract` for scanned PDFs.

If these tools are not installed, you can still review and enter details manually.

## Optional AI Extraction Modes

Internly now supports extraction modes:

- `local`: current local parser + OCR/PDF tooling.
- `gemini`: force Gemini API for PDF/image extraction.
- `groq`: force Groq API extraction from extracted document text.
- `granite`: force local Ollama extraction (default model: `granite3.2-vision`).
- `auto`: use Gemini for PDF/image when configured, otherwise Groq when configured, otherwise local.

Server env vars:

- `EXTRACTION_MODE` (`local`, `gemini`, `groq`, `granite`, `auto`; default `local`)
- `GEMINI_API_KEY` (required for `gemini`)
- `GROQ_API_KEY` (required for `groq`)
- `GROQ_MODEL` (optional, defaults to `llama-3.3-70b-versatile`)
- `OLLAMA_BASE_URL` (optional, defaults to `http://127.0.0.1:11434`)
- `OLLAMA_MODEL` (optional, defaults to `granite3.2-vision`)
- `OLLAMA_TIMEOUT_SECONDS` (optional, defaults to `60`)

Gemini model is pinned to `gemini-2.5-flash` (free-tier friendly).

You can set these in a local `.env` file in the project root:

```env
GEMINI_API_KEY=your_key_here
GROQ_API_KEY=your_key_here
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=granite3.2-vision
EXTRACTION_MODE=auto
```

You can also choose extraction mode per request in the dashboard import forms.

## Notes

- Routes for dashboard and applications require a signed-in or guest session.
- Guest mode is temporary and does not persist data to the server database.
- Export is available for signed-in users; guests can still download the blank template.
- Extraction is heuristic-based, so review fields before saving.
