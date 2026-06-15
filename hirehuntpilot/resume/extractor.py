from __future__ import annotations

from pathlib import Path


def extract_pdf_text(path: str | Path) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return ""
    try:
        import fitz
    except ImportError:
        return file_path.read_text(encoding="utf-8", errors="ignore") if file_path.suffix.lower() == ".txt" else ""
    document = fitz.open(file_path)
    try:
        return "\n".join(page.get_text() for page in document)
    finally:
        document.close()
