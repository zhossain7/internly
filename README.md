
![Internly Dashboard](dashboard.png)

# Internly

I built Internly after struggling to track graduate and internship applications across too many tabs, screenshots, and notes. I kept missing deadlines and losing context between OA stages, interviews, and follow-ups, so I made a product that puts everything in one place and keeps the process clear.

Internly is a focused pipeline for internship and graduate-role tracking with built-in extraction for links, PDFs, and screenshots.

## What Internly Does

- Tracks roles by company, position, deadline, status, notes, and source link.
- Extracts useful fields from job links (HTML, PDF, and image links auto-detected).
- Extracts from uploaded PDFs and screenshots using OCR fallback where needed.
- Supports secure sign-in and guest mode.
- Exports your data to a structured Excel spreadsheet.

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

## Notes

- Routes for dashboard and applications require a signed-in or guest session.
- Guest mode is temporary and does not persist data to the server database.
- Export is available for signed-in users; guests can still download the blank template.
- Extraction is heuristic-based, so review fields before saving.
