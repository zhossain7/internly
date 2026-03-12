
![Internly Dashboard](dashboard.png)

# Internly

Internly is a local internship and graduate-role tracker with:

- Application tracking (company, role, deadline, status, notes).
- Link extraction from job URLs (HTML/PDF/image auto-detected).
- File extraction from PDFs, screenshots, and images.
- A browser UI now, with an API-first design for future mobile apps.

## Quick Start

1. Make sure Python 3.10+ is installed.
2. Start the app:

```bash
python app.py
```

3. Open: `http://127.0.0.1:8000`

Main views:
- Product homepage: `/`
- Login/access page: `/login`
- App dashboard: `/app`
- Full applications workspace: `/applications`

The SQLite database (`internly.db`) is created automatically in the project root.

## Extraction Tooling (Optional but Recommended)

For high-quality extraction from mixed file types:

- `tesseract` for image OCR
- `pdftotext` for text-based PDFs
- `pdftoppm` + `tesseract` for scanned PDFs (OCR fallback)

If tools are unavailable, you can still use manual entry and text extraction.

## API Endpoints

- `GET /api/health`
- `GET /api/session`
- `POST /api/auth/register` with `{ "username": "...", "password": "..." }`
- `POST /api/auth/login` with `{ "username": "...", "password": "..." }`
- `POST /api/auth/guest`
- `POST /api/auth/logout`
- `GET /api/applications`
- `GET /api/applications/template.xlsx` (formatted Excel template with all fields)
- `GET /api/applications/export.xlsx` (export your tracked applications to Excel)
- `POST /api/applications`
- `GET /api/applications/:id`
- `PATCH /api/applications/:id`
- `DELETE /api/applications/:id`
- `POST /api/extract/link` with `{ "url": "https://..." }` (auto-detect HTML/PDF/image)
- `POST /api/extract/file` with `{ "file_base64": "data:...;base64,...", "filename": "job.pdf", "mime_type": "application/pdf" }`
- `POST /api/extract/screenshot` with `{ "image_base64": "data:image/png;base64,...", "filename": "job.png" }`
- `POST /api/extract/text` with `{ "text": "..." }`

## Mobile App Path

The backend API is already separated from the frontend, so you can build a phone app later without changing data storage:

1. Build a React Native/Expo client.
2. Reuse the same API routes for CRUD + extraction.
3. Add authentication and cloud DB when you want multi-device sync.

## Notes

- Dashboard and applications routes require either logged-in or guest session.
- Guest mode is temporary and does not save application data to the server database.
- Excel export is available for signed-in users; guest mode can still download the blank template.
- Link/file extraction is heuristic-based and should be reviewed before saving.
- Dates are normalized to `YYYY-MM-DD` where possible.
