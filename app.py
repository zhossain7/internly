from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import zipfile
from datetime import datetime
from html.parser import HTMLParser
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "internly.db"
WEB_DIR = BASE_DIR / "web"

MAX_BODY_BYTES = 30 * 1024 * 1024
MAX_HTML_BYTES = 1_200_000
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_OCR_IMAGE_BYTES = 12 * 1024 * 1024
MAX_PDF_OCR_PAGES = 5
PASSWORD_HASH_ITERATIONS = 260_000
SESSION_COOKIE_NAME = "internly_session"

ALLOWED_STATUSES = {
    "wishlist",
    "applied",
    "oa",
    "interview",
    "offer",
    "accepted",
    "assessment_centre",
    "rejected",
    "ghosted",
}

APPLICATION_COLUMNS = (
    "id",
    "company",
    "role",
    "location",
    "job_type",
    "deadline",
    "status",
    "source_url",
    "compensation",
    "notes",
    "created_at",
    "updated_at",
)

EXCEL_EXPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("id", "Application #"),
    ("company", "Company"),
    ("role", "Role"),
    ("location", "Location"),
    ("job_type", "Type"),
    ("deadline", "Deadline (YYYY-MM-DD)"),
    ("status", "Status"),
    ("source_url", "Source URL"),
    ("compensation", "Compensation"),
    ("notes", "Notes"),
    ("created_at", "Created At (UTC)"),
    ("updated_at", "Updated At (UTC)"),
)

EXCEL_STATUS_ORDER = (
    "wishlist",
    "applied",
    "oa",
    "interview",
    "accepted",
    "offer",
    "rejected",
    "ghosted",
)

EXCEL_COLUMN_WIDTHS = (9, 24, 30, 18, 16, 20, 16, 46, 18, 58, 24, 24)

SESSION_STORE: dict[str, dict[str, Any]] = {}
SESSION_STORE_LOCK = threading.Lock()


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def clean_text(value: Any, *, max_len: int = 8000) -> str | None:
    if value is None:
        return None
    text = normalize_space(str(value))
    if not text:
        return None
    return text[:max_len]


def hash_password(password: str, *, salt_hex: str | None = None) -> tuple[str, str, int]:
    salt_bytes = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_bytes,
        PASSWORD_HASH_ITERATIONS,
    )
    return (salt_bytes.hex(), derived.hex(), PASSWORD_HASH_ITERATIONS)


def verify_password(password: str, *, salt_hex: str, expected_hash_hex: str, iterations: int) -> bool:
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        iterations,
    )
    return hmac.compare_digest(derived.hex(), expected_hash_hex)


def ensure_status(value: Any) -> str:
    status = clean_text(value, max_len=32)
    if not status:
        return "wishlist"
    lowered = status.lower().replace("-", "_").replace(" ", "_")
    status_aliases = {
        "ac": "accepted",
        "assessmentcentre": "accepted",
        "assessment_center": "accepted",
        "assessment_centre": "accepted",
    }
    lowered = status_aliases.get(lowered, lowered)
    if lowered not in ALLOWED_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Use one of: {', '.join(sorted(ALLOWED_STATUSES))}."
        )
    return lowered


def parse_any_date(value: str) -> str | None:
    text = normalize_space(value).replace(",", "")
    if not text:
        return None

    date_formats = [
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%d %B %Y",
        "%d %b %Y",
        "%B %d %Y",
        "%b %d %Y",
    ]

    for fmt in date_formats:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.date().isoformat()
        except ValueError:
            continue

    return None


def extract_date_from_text(value: str) -> str | None:
    normalized = normalize_space(value)
    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
        r"\b\d{1,2}-\d{1,2}-\d{4}\b",
        r"\b(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\s+\d{1,2},?\s+\d{4}\b",
        r"\b\d{1,2}\s+(?:Jan|January|Feb|February|Mar|March|Apr|April|May|Jun|June|Jul|July|Aug|August|Sep|Sept|September|Oct|October|Nov|November|Dec|December)\s+\d{4}\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if not match:
            continue
        parsed = parse_any_date(match.group(0))
        if parsed:
            return parsed
    return None


def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".xml", ".log", ".yaml", ".yml"}
HTML_EXTENSIONS = {".html", ".htm"}
PDF_EXTENSIONS = {".pdf"}

TEXT_MIME_HINTS = {
    "text/plain",
    "text/csv",
    "application/json",
    "application/xml",
    "application/x-yaml",
}
HTML_MIME_HINTS = {"text/html", "application/xhtml+xml"}
PDF_MIME_HINTS = {"application/pdf"}


def extract_mime_type(value: str | None) -> str | None:
    cleaned = clean_text(value, max_len=160)
    if not cleaned:
        return None
    return cleaned.split(";", 1)[0].strip().lower() or None


def parse_data_url(encoded: str) -> tuple[str | None, str]:
    raw = encoded.strip()
    if not raw.lower().startswith("data:") or "," not in raw:
        return (None, raw)
    header, data = raw.split(",", 1)
    mime_hint = header[5:].split(";", 1)[0].strip().lower() or None
    return (mime_hint, data.strip())


def decode_base64_payload(encoded: str, *, max_size_bytes: int) -> tuple[bytes, str | None]:
    mime_hint, data = parse_data_url(encoded)
    if not data:
        raise ValueError("file_base64 is empty.")
    try:
        file_bytes = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("file_base64 is not valid base64.") from error
    if len(file_bytes) > max_size_bytes:
        raise ValueError(f"File is too large. Limit is {max_size_bytes // (1024 * 1024)} MB.")
    return (file_bytes, mime_hint)


def detect_file_kind(
    file_bytes: bytes,
    *,
    filename: str | None = None,
    mime_type: str | None = None,
    content_type: str | None = None,
) -> str:
    normalized_mime = extract_mime_type(mime_type) or extract_mime_type(content_type)
    suffix = Path(filename or "").suffix.lower()

    if file_bytes.startswith(b"%PDF-") or suffix in PDF_EXTENSIONS or normalized_mime in PDF_MIME_HINTS:
        return "pdf"

    if normalized_mime and normalized_mime.startswith("image/"):
        return "image"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if file_bytes[:3] == b"\xff\xd8\xff":
        return "image"
    if file_bytes[:6] in {b"GIF87a", b"GIF89a"}:
        return "image"
    if file_bytes[:4] == b"RIFF" and file_bytes[8:12] == b"WEBP":
        return "image"
    if file_bytes[:2] == b"BM":
        return "image"

    if normalized_mime in HTML_MIME_HINTS or suffix in HTML_EXTENSIONS:
        return "html"
    if normalized_mime in TEXT_MIME_HINTS or (normalized_mime and normalized_mime.startswith("text/")):
        return "text"
    if suffix in TEXT_EXTENSIONS:
        return "text"

    return "binary"


def decode_text_bytes(file_bytes: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "utf-16-le", "utf-16-be", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    return file_bytes.decode("utf-8", errors="ignore")


def resolve_tesseract_command() -> str:
    custom_path = os.environ.get("TESSERACT_PATH")
    if custom_path:
        candidate = Path(custom_path)
        if candidate.exists():
            return str(candidate)
    return "tesseract"


def run_tesseract_on_image_path(image_path: Path, *, timeout_seconds: int = 35) -> str:
    command = [resolve_tesseract_command(), str(image_path), "stdout", "--psm", "6"]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        raise RuntimeError("OCR unavailable: install 'tesseract' and add it to PATH.") from error
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or "OCR failed."
        raise RuntimeError(message) from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("OCR timed out. Try a smaller/cropped image.") from error

    extracted_text = clean_text(result.stdout, max_len=22000) or ""
    if not extracted_text:
        raise RuntimeError("OCR produced no text. Try a clearer file.")
    return extracted_text


def extract_text_from_pdf_file(pdf_path: Path) -> tuple[str, list[str]]:
    methods_used: list[str] = []
    extracted_chunks: list[str] = []

    if shutil.which("pdftotext"):
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", "-nopgbrk", str(pdf_path), "-"],
                check=True,
                capture_output=True,
                text=True,
                timeout=45,
            )
            text_output = clean_text(result.stdout, max_len=28000) or ""
            if text_output:
                extracted_chunks.append(text_output)
                methods_used.append("pdftotext")
        except subprocess.SubprocessError:
            pass

    combined_text = clean_text("\n".join(extracted_chunks), max_len=28000) or ""
    if len(combined_text) >= 160:
        return (combined_text, methods_used)

    if not shutil.which("pdftoppm"):
        if combined_text:
            return (combined_text, methods_used)
        raise RuntimeError(
            "Unable to read PDF text. Install 'pdftotext' or 'pdftoppm' + 'tesseract'."
        )

    tesseract_cmd = resolve_tesseract_command()
    has_tesseract = Path(tesseract_cmd).exists() if tesseract_cmd != "tesseract" else bool(
        shutil.which("tesseract")
    )
    if not has_tesseract:
        if combined_text:
            return (combined_text, methods_used)
        raise RuntimeError(
            "PDF OCR unavailable. Install both 'pdftoppm' and 'tesseract'."
        )

    with tempfile.TemporaryDirectory(prefix="internly-pdf-ocr-") as tmp_dir:
        prefix_path = Path(tmp_dir) / "page"
        try:
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    "1",
                    "-l",
                    str(MAX_PDF_OCR_PAGES),
                    "-png",
                    str(pdf_path),
                    str(prefix_path),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.SubprocessError as error:
            if combined_text:
                return (combined_text, methods_used)
            raise RuntimeError("Failed to rasterize PDF for OCR.") from error

        image_paths = sorted(Path(tmp_dir).glob("page-*.png"))
        if not image_paths:
            if combined_text:
                return (combined_text, methods_used)
            raise RuntimeError("No pages rendered for PDF OCR.")

        ocr_chunks: list[str] = []
        for image_path in image_paths:
            try:
                ocr_chunks.append(run_tesseract_on_image_path(image_path, timeout_seconds=45))
            except RuntimeError:
                continue

    ocr_text = clean_text("\n".join(ocr_chunks), max_len=28000) or ""
    if not ocr_text and not combined_text:
        raise RuntimeError("Could not extract readable text from PDF.")
    if ocr_text:
        methods_used.append("pdf-ocr")
    merged = clean_text("\n".join([combined_text, ocr_text]), max_len=28000) or ""
    return (merged, methods_used)


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                password_iterations INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                location TEXT,
                job_type TEXT,
                deadline TEXT,
                status TEXT NOT NULL DEFAULT 'wishlist',
                source_url TEXT,
                compensation TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        column_rows = conn.execute("PRAGMA table_info(applications)").fetchall()
        column_names = {row[1] for row in column_rows}
        if "user_id" not in column_names:
            conn.execute("ALTER TABLE applications ADD COLUMN user_id INTEGER;")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_updated_at ON applications(updated_at DESC);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_applications_user_updated ON applications(user_id, updated_at DESC);"
        )
        # Keep legacy/new labels consistent with backend canonical value.
        conn.execute(
            "UPDATE applications SET status = 'accepted' WHERE status = 'assessment_centre';"
        )
        conn.commit()
    finally:
        conn.close()


def open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in APPLICATION_COLUMNS}


def excel_col_name(index: int) -> str:
    value = max(1, index)
    parts: list[str] = []
    while value > 0:
        value, remainder = divmod(value - 1, 26)
        parts.append(chr(65 + remainder))
    return "".join(reversed(parts))


def escape_xml_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def sanitize_excel_cell_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    if text and text[0] in {"=", "+", "-", "@"}:
        # Prevent formula injection when opening exported files in spreadsheet tools.
        text = "'" + text
    return text


def build_excel_cell(ref: str, value: Any, *, style_id: int = 0) -> str:
    text = sanitize_excel_cell_value(value)
    if not text:
        return f'<c r="{ref}" s="{style_id}"/>'
    escaped = escape_xml_text(text)
    return (
        f'<c r="{ref}" t="inlineStr" s="{style_id}">'
        f'<is><t xml:space="preserve">{escaped}</t></is>'
        f"</c>"
    )


def build_excel_sheet_xml(
    rows: list[list[Any]],
    *,
    include_status_validation: bool,
) -> str:
    last_row = max(1, len(rows))
    last_col = excel_col_name(len(EXCEL_EXPORT_COLUMNS))
    dimension_ref = f"A1:{last_col}{last_row}"
    status_col = excel_col_name(7)

    cols_xml = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(EXCEL_COLUMN_WIDTHS, start=1)
    )

    row_xml_parts: list[str] = []
    for row_number, values in enumerate(rows, start=1):
        cells: list[str] = []
        for col_number, value in enumerate(values, start=1):
            ref = f"{excel_col_name(col_number)}{row_number}"
            style_id = 1 if row_number == 1 else 0
            if row_number > 1 and col_number == 10:
                style_id = 2
            cells.append(build_excel_cell(ref, value, style_id=style_id))
        if row_number == 1:
            row_xml_parts.append(
                f'<row r="{row_number}" ht="22" customHeight="1">{"".join(cells)}</row>'
            )
        else:
            row_xml_parts.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    data_validation_xml = ""
    if include_status_validation:
        allowed = ",".join(EXCEL_STATUS_ORDER)
        data_validation_xml = (
            '<dataValidations count="1">'
            f'<dataValidation type="list" allowBlank="1" sqref="{status_col}2:{status_col}1048576">'
            f'<formula1>"{allowed}"</formula1>'
            "</dataValidation>"
            "</dataValidations>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<dimension ref=\"{dimension_ref}\"/>"
        "<sheetViews>"
        '<sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView>"
        "</sheetViews>"
        '<sheetFormatPr defaultRowHeight="15"/>'
        f"<cols>{cols_xml}</cols>"
        f"<sheetData>{''.join(row_xml_parts)}</sheetData>"
        f'<autoFilter ref="A1:{last_col}1"/>'
        f"{data_validation_xml}"
        "</worksheet>"
    )


def build_excel_workbook_bytes(
    rows: list[list[Any]],
    *,
    include_status_validation: bool,
) -> bytes:
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )
    package_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<sheets>"
        '<sheet name="Applications" sheetId="1" r:id="rId1"/>'
        "</sheets>"
        "</workbook>"
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
        "</Relationships>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/><color rgb="FFFFFFFF"/></font>'
        "</fonts>"
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF111827"/><bgColor indexed="64"/></patternFill></fill>'
        "</fills>"
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1">'
        '<alignment vertical="top" wrapText="1"/>'
        "</xf>"
        "</cellXfs>"
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )

    sheet_xml = build_excel_sheet_xml(
        rows, include_status_validation=include_status_validation
    )

    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml)
        archive.writestr("_rels/.rels", package_rels_xml)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/styles.xml", styles_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return output.getvalue()


def application_to_excel_row(item: dict[str, Any], *, export_index: int) -> list[Any]:
    row: list[Any] = []
    for key, _label in EXCEL_EXPORT_COLUMNS:
        if key == "id":
            value = export_index
        else:
            value = item.get(key)
        if key == "status":
            value = "accepted" if value == "assessment_centre" else value
        row.append(value or "")
    return row


def build_template_excel_bytes() -> bytes:
    header_row = [label for _key, label in EXCEL_EXPORT_COLUMNS]
    example_row = [
        "",
        "Example Corp",
        "Software Engineer Intern",
        "Sydney",
        "Internship",
        "2026-08-31",
        "wishlist",
        "https://example.com/jobs/software-engineer-intern",
        "$45/hour",
        "Keep this format. You can add one application per row.",
        "",
        "",
    ]
    return build_excel_workbook_bytes(
        [header_row, example_row], include_status_validation=True
    )


def build_export_excel_bytes(items: list[dict[str, Any]]) -> bytes:
    rows = [[label for _key, label in EXCEL_EXPORT_COLUMNS]]
    for index, item in enumerate(items, start=1):
        rows.append(application_to_excel_row(item, export_index=index))
    return build_excel_workbook_bytes(rows, include_status_validation=False)


class JobPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.ld_json_blobs: list[str] = []
        self._inside_title = False
        self._inside_ld_json = False
        self._active_script_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        lower_tag = tag.lower()
        if lower_tag == "title":
            self._inside_title = True
        elif lower_tag == "meta":
            name = (attr_map.get("name") or attr_map.get("property") or "").strip().lower()
            content = attr_map.get("content", "").strip()
            if name and content:
                self.meta[name] = content
        elif lower_tag == "script":
            script_type = attr_map.get("type", "").strip().lower()
            if script_type == "application/ld+json":
                self._inside_ld_json = True
                self._active_script_parts = []

    def handle_endtag(self, tag: str) -> None:
        lower_tag = tag.lower()
        if lower_tag == "title":
            self._inside_title = False
        elif lower_tag == "script" and self._inside_ld_json:
            self._inside_ld_json = False
            blob = normalize_space("".join(self._active_script_parts))
            if blob:
                self.ld_json_blobs.append(blob)
            self._active_script_parts = []

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self.title_parts.append(data)
        if self._inside_ld_json:
            self._active_script_parts.append(data)


def try_json_loads(value: str) -> Any | None:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def iter_dicts(node: Any) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for child in node.values():
            yield from iter_dicts(child)
    elif isinstance(node, list):
        for item in node:
            yield from iter_dicts(item)


def extract_job_posting_from_ld_json(blobs: list[str]) -> dict[str, Any]:
    for blob in blobs:
        parsed = try_json_loads(blob)
        if parsed is None:
            continue
        for obj in iter_dicts(parsed):
            raw_type = obj.get("@type")
            type_list: list[str]
            if isinstance(raw_type, list):
                type_list = [str(item).lower() for item in raw_type]
            elif isinstance(raw_type, str):
                type_list = [raw_type.lower()]
            else:
                type_list = []

            if "jobposting" not in type_list:
                continue

            title = clean_text(obj.get("title") or obj.get("name"), max_len=200)
            company_name = None
            hiring_org = obj.get("hiringOrganization")
            if isinstance(hiring_org, dict):
                company_name = clean_text(hiring_org.get("name"), max_len=200)

            location = None
            job_location = obj.get("jobLocation")
            if isinstance(job_location, list):
                job_location = job_location[0] if job_location else None
            if isinstance(job_location, dict):
                address = job_location.get("address")
                if isinstance(address, dict):
                    parts = [
                        clean_text(address.get("addressLocality"), max_len=120),
                        clean_text(address.get("addressRegion"), max_len=120),
                        clean_text(address.get("addressCountry"), max_len=120),
                    ]
                    location = clean_text(", ".join([p for p in parts if p]), max_len=200)

            raw_deadline = clean_text(
                obj.get("validThrough") or obj.get("applicationDeadline"),
                max_len=60,
            )
            deadline = None
            if raw_deadline:
                deadline = parse_any_date(raw_deadline.split("T")[0]) or extract_date_from_text(
                    raw_deadline
                )

            return {
                "role": title,
                "company": company_name,
                "location": location,
                "deadline": deadline,
            }
    return {}


ROLE_HINT_WORDS = {
    "intern",
    "internship",
    "graduate",
    "grad",
    "software",
    "engineer",
    "developer",
    "analyst",
    "data",
    "program",
    "programmer",
}


def looks_like_role(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in ROLE_HINT_WORDS)


def infer_role_company_from_title(title: str) -> tuple[str | None, str | None]:
    value = clean_text(title, max_len=260)
    if not value:
        return (None, None)

    lowered = value.lower()
    if " at " in lowered:
        parts = re.split(r"\bat\b", value, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2:
            left = clean_text(parts[0], max_len=200)
            right = clean_text(parts[1], max_len=200)
            if left and right:
                return (left, right)

    pieces = [
        clean_text(piece, max_len=200)
        for piece in re.split(r"\s(?:\||-)\s", value)
    ]
    pieces = [piece for piece in pieces if piece]
    if len(pieces) >= 2:
        first, second = pieces[0], pieces[1]
        if first and second:
            if looks_like_role(first):
                return (first, second)
            if looks_like_role(second):
                return (second, first)
    return (None, None)


def guess_job_type(text: str) -> str | None:
    lowered = text.lower()
    has_intern = "intern" in lowered or "internship" in lowered
    has_grad = "graduate" in lowered or re.search(r"\bgrad\b", lowered) is not None
    if has_intern and has_grad:
        return "Intern/Graduate"
    if has_intern:
        return "Internship"
    if has_grad:
        return "Graduate"
    return None


def extract_labeled_field(lines: list[str], patterns: list[str]) -> str | None:
    for line in lines:
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                value = clean_text(match.group(1), max_len=250)
                if value:
                    return value
    return None


def extract_from_job_text(text: str, *, source_url: str | None = None) -> dict[str, Any]:
    normalized = normalize_space(text)
    lines = [clean_text(line, max_len=300) for line in text.splitlines()]
    lines = [line for line in lines if line]

    role = extract_labeled_field(
        lines,
        [
            r"(?:role|position|job title)\s*[:\-]\s*(.+)",
            r"(?:title)\s*[:\-]\s*(.+)",
        ],
    )
    company = extract_labeled_field(
        lines,
        [
            r"(?:company|employer|organisation|organization)\s*[:\-]\s*(.+)",
            r"(?:at)\s+([A-Z][A-Za-z0-9&,\-\. ]{2,})$",
        ],
    )
    location = extract_labeled_field(
        lines,
        [
            r"(?:location|based in)\s*[:\-]\s*(.+)",
            r"(?:remote|hybrid|onsite|on-site)\b.*",
        ],
    )
    raw_deadline = extract_labeled_field(
        lines,
        [
            r"(?:deadline|apply by|applications close|closing date)\s*[:\-]\s*(.+)",
        ],
    )
    deadline = extract_date_from_text(raw_deadline or normalized) if (raw_deadline or normalized) else None

    if not role or not company:
        fallback_title_line = next((line for line in lines[:8] if len(line) > 12), "")
        inferred_role, inferred_company = infer_role_company_from_title(fallback_title_line)
        role = role or inferred_role
        company = company or inferred_company

    if source_url and not company:
        domain = urlparse(source_url).netloc
        if domain:
            company = domain.replace("www.", "").split(".")[0].capitalize()

    job_type = guess_job_type(normalized)

    return {
        "company": company,
        "role": role,
        "location": location,
        "job_type": job_type,
        "deadline": deadline,
        "status": "wishlist",
        "source_url": source_url,
        "notes": clean_text(normalized[:450], max_len=450),
    }


def extension_from_mime(mime_type: str | None) -> str:
    if not mime_type:
        return ""
    normalized = extract_mime_type(mime_type)
    if normalized == "application/pdf":
        return ".pdf"
    if normalized == "image/png":
        return ".png"
    if normalized in {"image/jpeg", "image/jpg"}:
        return ".jpg"
    if normalized == "image/webp":
        return ".webp"
    if normalized == "image/gif":
        return ".gif"
    if normalized == "text/html":
        return ".html"
    if normalized and normalized.startswith("text/"):
        return ".txt"
    return ""


def extract_from_html_document(
    html: str,
    *,
    source_url: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    parser = JobPageParser()
    parser.feed(html)

    page_title = clean_text(" ".join(parser.title_parts), max_len=260)
    meta_description = clean_text(
        parser.meta.get("description")
        or parser.meta.get("og:description")
        or parser.meta.get("twitter:description"),
        max_len=500,
    )
    site_name = clean_text(parser.meta.get("og:site_name"), max_len=200)

    stripped_html = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    plain_text = normalize_space(re.sub(r"(?s)<[^>]+>", " ", stripped_html))
    plain_text = plain_text[:12000]

    seed_text = "\n".join(part for part in [page_title, meta_description, plain_text] if part)
    extracted = extract_from_job_text(seed_text, source_url=source_url)

    ld_json_extracted = extract_job_posting_from_ld_json(parser.ld_json_blobs)
    for key, value in ld_json_extracted.items():
        if value and not extracted.get(key):
            extracted[key] = value

    inferred_role, inferred_company = infer_role_company_from_title(page_title or "")
    if inferred_role and not extracted.get("role"):
        extracted["role"] = inferred_role
    if inferred_company and not extracted.get("company"):
        extracted["company"] = inferred_company
    if site_name and not extracted.get("company"):
        extracted["company"] = site_name

    extracted["raw"] = {
        "content_type": content_type,
        "source_type": "html",
        "title": page_title,
        "meta_description": meta_description,
    }
    return extracted


def extract_from_file_bytes(
    file_bytes: bytes,
    *,
    filename: str | None = None,
    mime_type: str | None = None,
    source_url: str | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    file_kind = detect_file_kind(
        file_bytes,
        filename=filename,
        mime_type=mime_type,
        content_type=content_type,
    )
    normalized_mime = extract_mime_type(mime_type) or extract_mime_type(content_type)

    if file_kind == "html":
        html = decode_text_bytes(file_bytes)
        return extract_from_html_document(html, source_url=source_url, content_type=normalized_mime)

    if file_kind == "text":
        raw_text = decode_text_bytes(file_bytes)
        extracted = extract_from_job_text(raw_text, source_url=source_url)
        extracted["raw"] = {
            "source_type": "text",
            "content_type": normalized_mime,
            "text_preview": clean_text(raw_text, max_len=900) or "",
        }
        return extracted

    if file_kind == "image":
        if len(file_bytes) > MAX_OCR_IMAGE_BYTES:
            raise ValueError(
                f"Image is too large. Keep it below {MAX_OCR_IMAGE_BYTES // (1024 * 1024)} MB."
            )
        suffix = Path(filename or "").suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            suffix = extension_from_mime(normalized_mime) or ".png"

        with tempfile.TemporaryDirectory(prefix="internly-image-ocr-") as temp_dir:
            image_path = Path(temp_dir) / f"upload{suffix}"
            image_path.write_bytes(file_bytes)
            extracted_text = run_tesseract_on_image_path(image_path)

        extracted = extract_from_job_text(extracted_text, source_url=source_url)
        extracted["raw"] = {
            "source_type": "image",
            "content_type": normalized_mime,
            "ocr_text_preview": extracted_text[:900],
        }
        return extracted

    if file_kind == "pdf":
        with tempfile.TemporaryDirectory(prefix="internly-pdf-") as temp_dir:
            pdf_name = filename or "document.pdf"
            if not pdf_name.lower().endswith(".pdf"):
                pdf_name = f"{pdf_name}.pdf"
            pdf_path = Path(temp_dir) / Path(pdf_name).name
            pdf_path.write_bytes(file_bytes)
            extracted_text, methods_used = extract_text_from_pdf_file(pdf_path)

        extracted = extract_from_job_text(extracted_text, source_url=source_url)
        extracted["raw"] = {
            "source_type": "pdf",
            "content_type": normalized_mime or "application/pdf",
            "methods": methods_used,
            "text_preview": extracted_text[:900],
        }
        return extracted

    fallback_text = decode_text_bytes(file_bytes)
    if len(normalize_space(fallback_text)) < 30:
        raise RuntimeError(
            "Unsupported file format. Use PDF, image, text, or a URL to the job posting."
        )
    extracted = extract_from_job_text(fallback_text, source_url=source_url)
    extracted["raw"] = {
        "source_type": "binary-fallback",
        "content_type": normalized_mime,
        "text_preview": clean_text(fallback_text, max_len=900) or "",
    }
    return extracted


def extract_from_file_b64(
    file_b64: str,
    *,
    filename: str | None = None,
    mime_type: str | None = None,
    source_url: str | None = None,
    require_image: bool = False,
) -> dict[str, Any]:
    file_bytes, data_url_mime = decode_base64_payload(file_b64, max_size_bytes=MAX_UPLOAD_BYTES)
    merged_mime = extract_mime_type(mime_type) or data_url_mime

    if require_image:
        file_kind = detect_file_kind(file_bytes, filename=filename, mime_type=merged_mime)
        if file_kind != "image":
            raise ValueError("image_base64 must contain an image file.")

    return extract_from_file_bytes(
        file_bytes,
        filename=filename,
        mime_type=merged_mime,
        source_url=source_url,
    )


def fetch_and_extract_from_link(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (InternlyBot/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/pdf,image/*,*/*;q=0.7",
        },
    )

    with urlopen(request, timeout=16) as response:
        content_type = response.headers.get("Content-Type", "")
        declared_mime = extract_mime_type(content_type)
        max_read_bytes = MAX_HTML_BYTES if declared_mime in HTML_MIME_HINTS else MAX_UPLOAD_BYTES
        body = response.read(max_read_bytes + 1)

    if len(body) > max_read_bytes:
        raise ValueError(
            f"Linked file is too large. Limit is {max_read_bytes // (1024 * 1024)} MB for this type."
        )

    inferred_filename = Path(urlparse(url).path).name or None
    return extract_from_file_bytes(
        body,
        filename=inferred_filename,
        mime_type=declared_mime,
        source_url=url,
        content_type=content_type,
    )


def extract_from_screenshot_b64(image_b64: str, filename: str | None = None) -> dict[str, Any]:
    try:
        return extract_from_file_b64(image_b64, filename=filename, require_image=True)
    except ValueError as error:
        message = str(error).replace("file_base64", "image_base64")
        raise ValueError(message) from error


class InternlyHandler(BaseHTTPRequestHandler):
    server_version = "InternlyHTTP/0.2.0"

    def log_message(self, format: str, *args: Any) -> None:
        # Keep logging concise for local development.
        print(f"[{self.log_date_time_string()}] {self.address_string()} - {format % args}")

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        if extra_headers:
            for key, value in extra_headers:
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, target: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", target)
        self.end_headers()

    def _build_session_cookie(self, token: str) -> str:
        return f"{SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Lax"

    def _build_clear_session_cookie(self) -> str:
        return f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"

    def _read_session_token(self) -> str | None:
        raw_cookie = self.headers.get("Cookie")
        if not raw_cookie:
            return None
        cookie = SimpleCookie()
        try:
            cookie.load(raw_cookie)
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE_NAME)
        if morsel is None:
            return None
        token = morsel.value.strip()
        return token or None

    def _session_payload(self) -> dict[str, Any]:
        token = self._read_session_token()
        if not token:
            return {}
        with SESSION_STORE_LOCK:
            payload = SESSION_STORE.get(token)
            return dict(payload) if payload else {}

    def _set_session_payload(self, payload: dict[str, Any]) -> str:
        token = secrets.token_urlsafe(32)
        with SESSION_STORE_LOCK:
            SESSION_STORE[token] = payload
        return token

    def _clear_session(self) -> None:
        token = self._read_session_token()
        if not token:
            return
        with SESSION_STORE_LOCK:
            SESSION_STORE.pop(token, None)

    def _require_session(self) -> dict[str, Any] | None:
        session = self._session_payload()
        if not session:
            return None
        return session

    def _require_user_session(self) -> tuple[dict[str, Any] | None, str | None]:
        session = self._require_session()
        if not session:
            return (None, "Please log in or continue as guest.")
        if session.get("is_guest"):
            return (None, "Guest mode cannot save data.")
        if not session.get("user_id"):
            return (None, "Invalid session. Please log in again.")
        return (session, None)

    def _send_file(self, path: Path) -> None:
        content = path.read_bytes()
        suffix = path.suffix.lower()
        content_types = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".svg": "image/svg+xml",
        }
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_types.get(suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_binary(
        self,
        status: int,
        content: bytes,
        content_type: str,
        *,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for key, value in extra_headers:
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def _parse_json_body(self) -> dict[str, Any]:
        length_raw = self.headers.get("Content-Length")
        try:
            length = int(length_raw or "0")
        except ValueError as error:
            raise ValueError("Invalid Content-Length header.") from error

        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError("Request body is too large.")

        body = self.rfile.read(length)
        try:
            parsed = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("Body must be valid JSON.") from error
        if not isinstance(parsed, dict):
            raise ValueError("Body JSON must be an object.")
        return parsed

    def _parse_application_id(self) -> int | None:
        path = urlparse(self.path).path
        match = re.fullmatch(r"/api/applications/(\d+)", path)
        if not match:
            return None
        return int(match.group(1))

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {"ok": True, "time": utc_now_iso()})
            return

        if path == "/api/session":
            session = self._session_payload()
            if not session:
                self._send_json(
                    HTTPStatus.OK,
                    {"ok": True, "authenticated": False, "is_guest": False, "username": None},
                )
                return
            username = None
            if session.get("user_id"):
                conn = open_db()
                try:
                    row = conn.execute(
                        "SELECT username FROM users WHERE id = ?",
                        (session["user_id"],),
                    ).fetchone()
                finally:
                    conn.close()
                if row:
                    username = row["username"]
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "authenticated": True,
                    "is_guest": bool(session.get("is_guest")),
                    "username": username,
                },
            )
            return

        if path in {"/login", "/login/"}:
            if self._require_session():
                self._redirect("/app")
                return
            self._serve_static("/login.html")
            return

        if path == "/api/applications/template.xlsx":
            if not self._require_session():
                self._send_json(
                    HTTPStatus.UNAUTHORIZED,
                    {"ok": False, "error": "Please log in or continue as guest."},
                )
                return
            workbook = build_template_excel_bytes()
            self._send_binary(
                HTTPStatus.OK,
                workbook,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                extra_headers=[
                    (
                        "Content-Disposition",
                        'attachment; filename="internly-applications-template.xlsx"',
                    )
                ],
            )
            return

        if path == "/api/applications/export.xlsx":
            session, error = self._require_user_session()
            if error:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": error})
                return
            params = parse_qs(parsed.query)
            status_filter = params.get("status", [None])[0]
            try:
                data = self._list_applications(session["user_id"], status_filter)
            except ValueError as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
                return
            timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
            workbook = build_export_excel_bytes(data)
            self._send_binary(
                HTTPStatus.OK,
                workbook,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                extra_headers=[
                    (
                        "Content-Disposition",
                        f'attachment; filename="internly-applications-{timestamp}.xlsx"',
                    )
                ],
            )
            return

        if path == "/api/applications":
            session, error = self._require_user_session()
            if error:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": error})
                return
            params = parse_qs(parsed.query)
            status_filter = params.get("status", [None])[0]
            try:
                data = self._list_applications(session["user_id"], status_filter)
            except ValueError as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "items": data})
            return

        app_id = self._parse_application_id()
        if app_id is not None:
            session, error = self._require_user_session()
            if error:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": error})
                return
            item = self._get_application(app_id, session["user_id"])
            if not item:
                self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Application not found."})
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "item": item})
            return

        if path in {"/app", "/app/"}:
            if not self._require_session():
                self._redirect("/login")
                return
            self._serve_static("/app.html")
            return

        if path in {"/applications", "/applications/"}:
            if not self._require_session():
                self._redirect("/login")
                return
            self._serve_static("/applications.html")
            return

        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path

        try:
            payload = self._parse_json_body()
        except ValueError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
            return

        if path == "/api/auth/register":
            username = clean_text(payload.get("username"), max_len=80)
            password_raw = payload.get("password")
            if not username or len(username) < 3:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "Username must be at least 3 characters."},
                )
                return
            if not isinstance(password_raw, str) or len(password_raw) < 8:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "Password must be at least 8 characters."},
                )
                return
            try:
                user = self._register_user(username.lower(), password_raw)
            except ValueError as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
                return
            session_token = self._set_session_payload(
                {"user_id": user["id"], "is_guest": False, "created_at": utc_now_iso()}
            )
            self._send_json(
                HTTPStatus.CREATED,
                {
                    "ok": True,
                    "authenticated": True,
                    "is_guest": False,
                    "username": user["username"],
                },
                extra_headers=[("Set-Cookie", self._build_session_cookie(session_token))],
            )
            return

        if path == "/api/auth/login":
            username = clean_text(payload.get("username"), max_len=80)
            password_raw = payload.get("password")
            if not username or not isinstance(password_raw, str):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "Provide `username` and `password`."},
                )
                return
            user = self._authenticate_user(username.lower(), password_raw)
            if not user:
                self._send_json(
                    HTTPStatus.UNAUTHORIZED,
                    {"ok": False, "error": "Invalid username or password."},
                )
                return
            session_token = self._set_session_payload(
                {"user_id": user["id"], "is_guest": False, "created_at": utc_now_iso()}
            )
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "authenticated": True,
                    "is_guest": False,
                    "username": user["username"],
                },
                extra_headers=[("Set-Cookie", self._build_session_cookie(session_token))],
            )
            return

        if path == "/api/auth/guest":
            session_token = self._set_session_payload(
                {"user_id": None, "is_guest": True, "created_at": utc_now_iso()}
            )
            self._send_json(
                HTTPStatus.OK,
                {"ok": True, "authenticated": True, "is_guest": True, "username": None},
                extra_headers=[("Set-Cookie", self._build_session_cookie(session_token))],
            )
            return

        if path == "/api/auth/logout":
            self._clear_session()
            self._send_json(
                HTTPStatus.OK,
                {"ok": True, "authenticated": False, "is_guest": False, "username": None},
                extra_headers=[("Set-Cookie", self._build_clear_session_cookie())],
            )
            return

        if path == "/api/applications":
            session, error = self._require_user_session()
            if error:
                self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": error})
                return
            try:
                created = self._create_application(payload, session["user_id"])
            except ValueError as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
                return
            self._send_json(HTTPStatus.CREATED, {"ok": True, "item": created})
            return

        if path == "/api/extract/link":
            if not self._require_session():
                self._send_json(
                    HTTPStatus.UNAUTHORIZED,
                    {"ok": False, "error": "Please log in or continue as guest."},
                )
                return
            url = clean_text(payload.get("url"), max_len=800)
            if not url or not is_valid_url(url):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "Provide a valid http(s) URL in `url`."},
                )
                return
            try:
                extracted = fetch_and_extract_from_link(url)
            except ValueError as error:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": str(error)},
                )
                return
            except Exception as error:
                self._send_json(
                    HTTPStatus.BAD_GATEWAY,
                    {"ok": False, "error": f"Failed to extract from link: {error}"},
                )
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "extracted": extracted})
            return

        if path == "/api/extract/file":
            if not self._require_session():
                self._send_json(
                    HTTPStatus.UNAUTHORIZED,
                    {"ok": False, "error": "Please log in or continue as guest."},
                )
                return
            file_base64 = payload.get("file_base64")
            filename = clean_text(payload.get("filename"), max_len=200)
            mime_type = clean_text(payload.get("mime_type"), max_len=160)
            source_url = clean_text(payload.get("source_url"), max_len=800)
            if source_url and not is_valid_url(source_url):
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "`source_url` must be a valid http(s) URL."},
                )
                return
            if not isinstance(file_base64, str) or not file_base64.strip():
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "Provide `file_base64` in the request body."},
                )
                return
            if len(file_base64) > 28_000_000:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "file_base64 payload is too large."},
                )
                return
            try:
                extracted = extract_from_file_b64(
                    file_base64,
                    filename=filename,
                    mime_type=mime_type,
                    source_url=source_url,
                )
            except (ValueError, RuntimeError) as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "extracted": extracted})
            return

        if path == "/api/extract/screenshot":
            if not self._require_session():
                self._send_json(
                    HTTPStatus.UNAUTHORIZED,
                    {"ok": False, "error": "Please log in or continue as guest."},
                )
                return
            image_b64 = payload.get("image_base64")
            filename = clean_text(payload.get("filename"), max_len=120)
            if not isinstance(image_b64, str) or not image_b64.strip():
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "Provide `image_base64` in the request body."},
                )
                return
            if len(image_b64) > 18_000_000:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"ok": False, "error": "image_base64 payload is too large."},
                )
                return
            try:
                extracted = extract_from_screenshot_b64(image_b64, filename=filename)
            except (ValueError, RuntimeError) as error:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
                return
            self._send_json(HTTPStatus.OK, {"ok": True, "extracted": extracted})
            return

        if path == "/api/extract/text":
            if not self._require_session():
                self._send_json(
                    HTTPStatus.UNAUTHORIZED,
                    {"ok": False, "error": "Please log in or continue as guest."},
                )
                return
            raw_text = clean_text(payload.get("text"), max_len=9000)
            source_url = clean_text(payload.get("source_url"), max_len=800)
            if not raw_text:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": "Provide `text`."})
                return
            extracted = extract_from_job_text(raw_text, source_url=source_url)
            self._send_json(HTTPStatus.OK, {"ok": True, "extracted": extracted})
            return

        self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Endpoint not found."})

    def do_PATCH(self) -> None:  # noqa: N802
        app_id = self._parse_application_id()
        if app_id is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Endpoint not found."})
            return

        session, error = self._require_user_session()
        if error:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": error})
            return

        try:
            payload = self._parse_json_body()
            updated = self._update_application(app_id, payload, session["user_id"])
        except ValueError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(error)})
            return

        if not updated:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Application not found."})
            return
        self._send_json(HTTPStatus.OK, {"ok": True, "item": updated})

    def do_DELETE(self) -> None:  # noqa: N802
        app_id = self._parse_application_id()
        if app_id is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Endpoint not found."})
            return

        session, error = self._require_user_session()
        if error:
            self._send_json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": error})
            return

        deleted = self._delete_application(app_id, session["user_id"])
        if not deleted:
            self._send_json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "Application not found."})
            return
        self._send_json(HTTPStatus.OK, {"ok": True, "deleted_id": app_id})

    def _serve_static(self, path: str) -> None:
        relative = path.lstrip("/") or "index.html"
        if relative in {"app.html", "applications.html"} and not self._require_session():
            self._redirect("/login")
            return
        file_path = (WEB_DIR / relative).resolve()
        try:
            file_path.relative_to(WEB_DIR.resolve())
        except ValueError:
            self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": "Forbidden"})
            return

        if file_path.is_dir():
            file_path = file_path / "index.html"
        if not file_path.exists() or not file_path.is_file():
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            self.wfile.write(b"Not found")
            return

        self._send_file(file_path)

    def _register_user(self, username: str, password: str) -> dict[str, Any]:
        salt_hex, hash_hex, iterations = hash_password(password)
        now = utc_now_iso()
        conn = open_db()
        try:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO users (username, password_salt, password_hash, password_iterations, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (username, salt_hex, hash_hex, iterations, now),
                )
            except sqlite3.IntegrityError as error:
                raise ValueError("Username already exists.") from error
            user_count_row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
            user_count = int(user_count_row["count"]) if user_count_row else 0
            if user_count == 1:
                # Migrate any pre-auth legacy rows to the first registered account.
                conn.execute(
                    "UPDATE applications SET user_id = ? WHERE user_id IS NULL",
                    (cursor.lastrowid,),
                )
            conn.commit()
            row = conn.execute(
                "SELECT id, username FROM users WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise ValueError("Failed to create user.")
        return {"id": row["id"], "username": row["username"]}

    def _authenticate_user(self, username: str, password: str) -> dict[str, Any] | None:
        conn = open_db()
        try:
            row = conn.execute(
                """
                SELECT id, username, password_salt, password_hash, password_iterations
                FROM users
                WHERE username = ?
                """,
                (username,),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        if not verify_password(
            password,
            salt_hex=row["password_salt"],
            expected_hash_hex=row["password_hash"],
            iterations=int(row["password_iterations"]),
        ):
            return None
        return {"id": row["id"], "username": row["username"]}

    def _list_applications(self, user_id: int, status_filter: str | None) -> list[dict[str, Any]]:
        query = f"SELECT {', '.join(APPLICATION_COLUMNS)} FROM applications WHERE user_id = ?"
        params: list[Any] = [user_id]
        if status_filter:
            normalized = ensure_status(status_filter)
            query += " AND status = ?"
            params.append(normalized)
        query += " ORDER BY updated_at DESC, id DESC"

        conn = open_db()
        try:
            rows = conn.execute(query, params).fetchall()
        finally:
            conn.close()
        return [row_to_dict(row) for row in rows]

    def _get_application(self, app_id: int, user_id: int) -> dict[str, Any] | None:
        conn = open_db()
        try:
            row = conn.execute(
                f"SELECT {', '.join(APPLICATION_COLUMNS)} FROM applications WHERE id = ? AND user_id = ?",
                (app_id, user_id),
            ).fetchone()
        finally:
            conn.close()
        return row_to_dict(row) if row else None

    def _create_application(self, payload: dict[str, Any], user_id: int) -> dict[str, Any]:
        company = clean_text(payload.get("company"), max_len=200)
        role = clean_text(payload.get("role"), max_len=200)
        if not company or not role:
            raise ValueError("`company` and `role` are required.")

        source_url = clean_text(payload.get("source_url"), max_len=800)
        if source_url and not is_valid_url(source_url):
            raise ValueError("`source_url` must be a valid http(s) URL.")

        deadline_raw = clean_text(payload.get("deadline"), max_len=64)
        deadline = parse_any_date(deadline_raw) if deadline_raw else None
        if deadline_raw and not deadline:
            deadline = extract_date_from_text(deadline_raw)
        if deadline_raw and not deadline:
            raise ValueError("`deadline` must be a valid date (e.g. 2026-04-15).")

        status = ensure_status(payload.get("status"))
        now = utc_now_iso()

        values = (
            company,
            role,
            clean_text(payload.get("location"), max_len=200),
            clean_text(payload.get("job_type"), max_len=80),
            deadline,
            status,
            source_url,
            clean_text(payload.get("compensation"), max_len=120),
            clean_text(payload.get("notes"), max_len=4000),
            now,
            now,
            user_id,
        )

        conn = open_db()
        try:
            cursor = conn.execute(
                """
                INSERT INTO applications (
                    company, role, location, job_type, deadline, status,
                    source_url, compensation, notes, created_at, updated_at, user_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            conn.commit()
            new_id = cursor.lastrowid
            row = conn.execute(
                f"SELECT {', '.join(APPLICATION_COLUMNS)} FROM applications WHERE id = ? AND user_id = ?",
                (new_id, user_id),
            ).fetchone()
        finally:
            conn.close()
        return row_to_dict(row)

    def _update_application(
        self, app_id: int, payload: dict[str, Any], user_id: int
    ) -> dict[str, Any] | None:
        allowed_fields = {
            "company": lambda value: clean_text(value, max_len=200),
            "role": lambda value: clean_text(value, max_len=200),
            "location": lambda value: clean_text(value, max_len=200),
            "job_type": lambda value: clean_text(value, max_len=80),
            "source_url": lambda value: clean_text(value, max_len=800),
            "compensation": lambda value: clean_text(value, max_len=120),
            "notes": lambda value: clean_text(value, max_len=4000),
            "status": ensure_status,
            "deadline": lambda value: parse_any_date(str(value))
            if clean_text(value, max_len=64)
            else None,
        }

        updates: dict[str, Any] = {}
        for key, parser in allowed_fields.items():
            if key in payload:
                parsed_value = parser(payload.get(key))
                if key == "source_url" and parsed_value and not is_valid_url(parsed_value):
                    raise ValueError("`source_url` must be a valid http(s) URL.")
                if key in {"company", "role"} and parsed_value is None:
                    raise ValueError(f"`{key}` cannot be empty.")
                updates[key] = parsed_value

        if "deadline" in payload and payload.get("deadline"):
            if updates.get("deadline") is None:
                fallback = extract_date_from_text(str(payload.get("deadline")))
                if fallback:
                    updates["deadline"] = fallback
                else:
                    raise ValueError("`deadline` must be a valid date.")

        if not updates:
            raise ValueError("No supported fields provided for update.")

        updates["updated_at"] = utc_now_iso()
        set_clause = ", ".join([f"{column} = ?" for column in updates.keys()])
        params = list(updates.values()) + [app_id]

        conn = open_db()
        try:
            cursor = conn.execute(
                f"UPDATE applications SET {set_clause} WHERE id = ? AND user_id = ?",
                params + [user_id],
            )
            conn.commit()
            if cursor.rowcount == 0:
                return None
            row = conn.execute(
                f"SELECT {', '.join(APPLICATION_COLUMNS)} FROM applications WHERE id = ? AND user_id = ?",
                (app_id, user_id),
            ).fetchone()
        finally:
            conn.close()
        return row_to_dict(row) if row else None

    def _delete_application(self, app_id: int, user_id: int) -> bool:
        conn = open_db()
        try:
            cursor = conn.execute(
                "DELETE FROM applications WHERE id = ? AND user_id = ?",
                (app_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    init_db()
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), InternlyHandler)
    print(f"Internly running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Server stopped.")


if __name__ == "__main__":
    run()
