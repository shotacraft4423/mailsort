"""添付解析: extracts text from PDF/Excel/Word attachments and classifies
what kind of document they are (skill sheet / project brief / invoice /
contract / other) so the UI can show a dedicated icon and the classification
service can feed the extracted text into its prompt context.

Image OCR (名刺OCR含む) needs a `pytesseract` + Tesseract binary install
that isn't guaranteed to be present on every machine; `extract_text` degrades
gracefully (returns "") when the OCR stack is missing rather than raising,
so attachment ingestion never blocks on it. Zip attachments are unpacked
in-memory and each member re-runs through this same extraction/classification
logic (one level deep — a zip inside a zip is left as opaque bytes, both to
bound the work done per attachment and because SES mail practically never
nests archives).
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass

AttachmentKind = str  # skill_sheet | project_brief | invoice | contract | resume | business_card | other

_KIND_KEYWORDS: dict[str, list[str]] = {
    "skill_sheet": ["スキルシート", "skill sheet", "経歴書", "職務経歴"],
    "invoice": ["請求書", "invoice", "御請求", "お振込み先"],
    "contract": ["契約書", "基本契約", "発注書", "個別契約", "contract"],
    "project_brief": ["案件票", "案件概要", "募集要項"],
    "resume": ["履歴書", "resume", "cv"],
}

# Business cards have no reliable filename/keyword signal (they're a photo
# or scan) — the only usable signal is "this is an image, and OCR found
# something that looks like contact info" (an email address or a phone
# number). Loose on purpose: false positives just mean an unnecessary
# "名刺として登録" button offer in the UI, not a data-corrupting action.
_EMAIL_HINT_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_HINT_RE = re.compile(r"0\d{1,4}[-‐]\d{1,4}[-‐]\d{3,4}")


@dataclass
class AttachmentAnalysis:
    kind: AttachmentKind
    extracted_text: str


def _extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:  # noqa: BLE001 - a malformed/encrypted PDF must not break ingestion
        return ""


def _extract_docx(data: bytes) -> str:
    try:
        import docx
    except ImportError:
        return ""
    try:
        document = docx.Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs)
    except Exception:  # noqa: BLE001
        return ""


def _extract_xlsx(data: bytes) -> str:
    try:
        import openpyxl
    except ImportError:
        return ""
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        lines = []
        for sheet in workbook.worksheets:
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None]
                if cells:
                    lines.append("\t".join(cells))
        return "\n".join(lines)
    except Exception:  # noqa: BLE001
        return ""


def _extract_image_ocr(data: bytes) -> str:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""
    try:
        return pytesseract.image_to_string(Image.open(io.BytesIO(data)), lang="jpn+eng")
    except Exception:  # noqa: BLE001 - missing tesseract binary, corrupt image, etc.
        return ""


# Zip-bomb / pathological-archive guards: a malicious or just very large zip
# must not blow up memory or ingestion time. Members beyond these limits are
# silently skipped rather than raising, consistent with every other
# extractor here degrading instead of failing ingestion.
_MAX_ZIP_MEMBERS = 20
_MAX_ZIP_MEMBER_BYTES = 10 * 1024 * 1024
_MAX_ZIP_TOTAL_OUTPUT_CHARS = 50_000


def _extract_zip(data: bytes) -> str:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return ""

    sections: list[str] = []
    total_chars = 0
    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()][:_MAX_ZIP_MEMBERS]
        for info in members:
            if info.file_size > _MAX_ZIP_MEMBER_BYTES or total_chars >= _MAX_ZIP_TOTAL_OUTPUT_CHARS:
                continue
            try:
                member_data = archive.read(info)
            except (zipfile.BadZipFile, RuntimeError):  # RuntimeError: e.g. password-protected member
                continue
            member_text = extract_text(file_name=info.filename, content_type="", data=member_data)
            if not member_text:
                continue
            section = f"=== {info.filename} ===\n{member_text}"
            sections.append(section)
            total_chars += len(section)

    return "\n\n".join(sections)


_EXTRACTORS = {
    "application/pdf": _extract_pdf,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": _extract_docx,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": _extract_xlsx,
    "image/png": _extract_image_ocr,
    "image/jpeg": _extract_image_ocr,
    "application/zip": _extract_zip,
    "application/x-zip-compressed": _extract_zip,  # common alternate MIME type from Windows senders
}

_EXTENSION_CONTENT_TYPE = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".zip": "application/zip",
    ".txt": "text/plain",
    ".csv": "text/plain",
}


def _resolve_content_type(file_name: str, content_type: str) -> str:
    if content_type in _EXTRACTORS:
        return content_type
    for ext, mapped in _EXTENSION_CONTENT_TYPE.items():
        if file_name.lower().endswith(ext):
            return mapped
    return content_type


def extract_text(*, file_name: str, content_type: str, data: bytes) -> str:
    resolved = _resolve_content_type(file_name, content_type)
    extractor = _EXTRACTORS.get(resolved)
    if extractor is None:
        if resolved.startswith("text/"):
            return data.decode("utf-8", errors="replace")
        return ""
    return extractor(data).strip()


def classify_kind(*, file_name: str, extracted_text: str, content_type: str = "") -> AttachmentKind:
    haystack = f"{file_name}\n{extracted_text[:2000]}".lower()
    for kind, keywords in _KIND_KEYWORDS.items():
        if any(re.search(re.escape(kw.lower()), haystack) for kw in keywords):
            return kind

    resolved = _resolve_content_type(file_name, content_type)
    if resolved.startswith("image/") and (_EMAIL_HINT_RE.search(extracted_text) or _PHONE_HINT_RE.search(extracted_text)):
        return "business_card"

    return "other"


def analyze(*, file_name: str, content_type: str, data: bytes) -> AttachmentAnalysis:
    text = extract_text(file_name=file_name, content_type=content_type, data=data)
    kind = classify_kind(file_name=file_name, extracted_text=text, content_type=content_type)
    return AttachmentAnalysis(kind=kind, extracted_text=text)
