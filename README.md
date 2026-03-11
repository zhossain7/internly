# Internly

Internly is a local internship and graduate-role tracker with:

- Application tracking (company, role, deadline, status, notes).
- Link extraction from job post URLs.
- Screenshot extraction via OCR (using `tesseract` if installed).
- A browser UI now, with an API-first design for future mobile apps.

## Quick Start

1. Make sure Python 3.10+ is installed.
2. Start the app:

```bash
python app.py
```

3. Open: `http://127.0.0.1:8000`

The SQLite database (`internly.db`) is created automatically in the project root.

## OCR Setup (Optional)

Screenshot extraction requires `tesseract` available in your `PATH`.

- Windows: install Tesseract OCR, then restart terminal.
- If unavailable, use manual entry or link extraction.

## API Endpoints

- `GET /api/health`
- `GET /api/applications`
- `POST /api/applications`
- `GET /api/applications/:id`
- `PATCH /api/applications/:id`
- `DELETE /api/applications/:id`
- `POST /api/extract/link` with `{ "url": "https://..." }`
- `POST /api/extract/screenshot` with `{ "image_base64": "data:image/png;base64,...", "filename": "job.png" }`
- `POST /api/extract/text` with `{ "text": "..." }`

## Mobile App Path

The backend API is already separated from the frontend, so you can build a phone app later without changing data storage:

1. Build a React Native/Expo client.
2. Reuse the same API routes for CRUD + extraction.
3. Add authentication and cloud DB when you want multi-device sync.

## Notes

- Link/screenshot extraction is heuristic-based and should be reviewed before saving.
- Dates are normalized to `YYYY-MM-DD` where possible.
