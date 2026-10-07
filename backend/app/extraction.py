import base64
import mimetypes
from pathlib import Path

import fitz
from docx import Document as DocxDocument

TEXT_EXTENSIONS = {".txt", ".md"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

OCR_PROMPT = (
    "Extract all useful readable text from this document image. "
    "Preserve names, organizations, dates, certificate/course names, IDs, headings, "
    "labels, marks, and other important values. Keep the reading order as natural as "
    "possible. Do not guess text that is not visible. Return plain text only."
)


def _image_bytes_to_text(image_bytes: bytes, mime_type: str, client, model: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{encoded}"

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": OCR_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            }
        ],
        temperature=0.1,
        max_completion_tokens=3000,
    )

    return (response.choices[0].message.content or "").strip()


def _image_to_text(path: Path, client, model: str) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return _image_bytes_to_text(path.read_bytes(), mime_type, client, model)


def _pdf_segments(path: Path, vision_client=None, vision_model: str = "qwen/qwen3.8-27b") -> list[tuple[str, str]]:
    """Extract native PDF text and OCR only pages that have little/no text."""
    pdf = fitz.open(path)
    segments: list[tuple[str, str]] = []

    try:
        for index, page in enumerate(pdf):
            source_label = f"Page {index + 1}"
            text = page.get_text("text").strip()

            # Native text extraction is faster, cheaper, and usually more accurate.
            if len(text) >= 30:
                segments.append((source_label, text))
                continue

            # Scanned/image-only page: render just this page and send it to Groq Vision.
            if vision_client:
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
                page_png = pixmap.tobytes("png")
                ocr_text = _image_bytes_to_text(
                    page_png,
                    "image/png",
                    vision_client,
                    vision_model,
                )
                if ocr_text:
                    segments.append((source_label, ocr_text))
                    continue

            # Keep any small amount of native text rather than discarding it.
            if text:
                segments.append((source_label, text))
    finally:
        pdf.close()

    return segments


def extract_segments(
    path: Path,
    vision_client=None,
    vision_model: str = "qwen/qwen3.8-27b",
) -> list[tuple[str, str]]:
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        segments = _pdf_segments(path, vision_client=vision_client, vision_model=vision_model)
        if segments:
            return segments
        if not vision_client:
            raise ValueError(
                "This PDF appears scanned and GROQ_API_KEY is not configured for OCR."
            )
        raise ValueError("No readable text could be extracted from this PDF.")

    if suffix == ".docx":
        doc = DocxDocument(path)
        text = "\n".join(paragraph.text for paragraph in doc.paragraphs).strip()
        return [("Document", text)] if text else []

    if suffix in TEXT_EXTENSIONS:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        return [("Document", text)] if text else []

    if suffix in IMAGE_EXTENSIONS:
        if not vision_client:
            raise ValueError("GROQ_API_KEY is required to extract text from images.")
        text = _image_to_text(path, vision_client, vision_model)
        return [("Image", text)] if text else []

    raise ValueError(
        "Unsupported file type. Use PDF, DOCX, TXT, MD, PNG, JPG, JPEG, or WEBP."
    )


def chunk_text(text: str, chunk_size: int = 1800, overlap: int = 220) -> list[str]:
    """Create moderately sized overlapping chunks while avoiding excessive vector rows."""
    clean = " ".join(text.split())
    if not clean:
        return []

    chunks: list[str] = []
    start = 0

    while start < len(clean):
        end = min(len(clean), start + chunk_size)

        # Prefer ending near a sentence/word boundary when possible.
        if end < len(clean):
            boundary = max(
                clean.rfind(". ", start + chunk_size // 2, end),
                clean.rfind(" ", start + chunk_size // 2, end),
            )
            if boundary > start:
                end = boundary + 1

        chunk = clean[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(clean):
            break

        start = max(0, end - overlap)

    return chunks
