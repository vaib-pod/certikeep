import mimetypes
from pathlib import Path

import fitz
from docx import Document as DocxDocument
from google.genai import types

TEXT_EXTENSIONS = {".txt", ".md"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def _image_to_text(path: Path, client, model: str) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    image_part = types.Part.from_bytes(data=path.read_bytes(), mime_type=mime)
    response = client.models.generate_content(
        model=model,
        contents=[
            "Extract all useful readable text from this document image. Preserve names, organizations, dates, IDs, headings, and labels. Return plain text only.",
            image_part,
        ],
    )
    return (response.text or "").strip()


def extract_segments(path: Path, client=None, vision_model: str = "gemini-3.8-flash") -> list[tuple[str, str]]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        pdf = fitz.open(path)
        segments = []
        for index, page in enumerate(pdf):
            text = page.get_text("text").strip()
            if text:
                segments.append((f"Page {index + 1}", text))
        pdf.close()
        if segments:
            return segments
        raise ValueError("This PDF appears scanned. Convert it to JPG/PNG for this MVP, or add PDF OCR later.")
    if suffix == ".docx":
        doc = DocxDocument(path)
        text = "\n".join(p.text for p in doc.paragraphs).strip()
        return [("Document", text)] if text else []
    if suffix in TEXT_EXTENSIONS:
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        return [("Document", text)] if text else []
    if suffix in IMAGE_EXTENSIONS:
        if not client:
            raise ValueError("GEMINI_API_KEY is required to extract text from images.")
        text = _image_to_text(path, client, vision_model)
        return [("Image", text)] if text else []
    raise ValueError("Unsupported file type. Use PDF, DOCX, TXT, MD, PNG, JPG, JPEG, or WEBP.")


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 180) -> list[str]:
    clean = " ".join(text.split())
    if not clean:
        return []
    chunks = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + chunk_size)
        chunks.append(clean[start:end])
        if end >= len(clean):
            break
        start = max(0, end - overlap)
    return chunks
