from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re


@dataclass
class ResumeExtractionResult:
    source_path: Path
    source_type: str
    extraction_method: str
    raw_text: str
    cleaned_text: str
    methods_tried: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ocr_used: bool = False


def _normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _text_quality_score(text: str) -> tuple[int, int, int]:
    stripped = _normalize_text(text)
    if not stripped:
        return (0, 0, 0)
    alpha = sum(1 for ch in stripped if ch.isalpha())
    lines = len([line for line in stripped.splitlines() if line.strip()])
    signal = 0
    if "@" in stripped:
        signal += 50
    if any(word in stripped.lower() for word in ("skills", "experience", "education", "projects", "summary")):
        signal += 50
    return (signal, alpha, lines)


def _extract_pdf_with_pypdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_pdf_with_pdfplumber(path: Path) -> str:
    import pdfplumber

    chunks: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text() or "")
    return "\n\n".join(chunks)


def _extract_pdf_with_fitz(path: Path) -> str:
    import fitz

    chunks: list[str] = []
    document = fitz.open(str(path))
    try:
        for page in document:
            chunks.append(page.get_text("text") or "")
    finally:
        document.close()
    return "\n\n".join(chunks)


def _extract_pdf_with_ocr(path: Path) -> str:
    import fitz
    from PIL import Image
    import pytesseract

    chunks: list[str] = []
    document = fitz.open(str(path))
    try:
        for page in document:
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            chunks.append(pytesseract.image_to_string(image))
    finally:
        document.close()
    return "\n\n".join(chunks)


def _maybe_clean_with_llm(text: str) -> str:
    from hirehuntpilot.llm import get_client

    prompt = """You are cleaning raw resume text extracted from a PDF or OCR.

Return only normalized plain resume text.

Rules:
- Preserve facts exactly.
- Remove extraction artifacts, repeated headers, broken spacing, and page junk.
- Do not add or infer missing content.
- Do not rewrite the candidate's resume.
- Keep section order and bullets intact where possible."""
    return get_client().chat(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text[:16000]},
        ],
        temperature=0.0,
        max_tokens=2500,
    ).strip()


def extract_resume_artifact(path: Path, *, use_llm_cleanup: bool = False) -> ResumeExtractionResult:
    suffix = path.suffix.lower()
    methods_tried: list[str] = []
    warnings: list[str] = []

    if suffix in {".txt", ".md"}:
        raw_text = path.read_text(encoding="utf-8-sig", errors="ignore")
        cleaned = _normalize_text(raw_text)
        if use_llm_cleanup and cleaned:
            try:
                cleaned = _maybe_clean_with_llm(cleaned)
            except Exception as exc:
                warnings.append(f"LLM cleanup skipped: {exc}")
        return ResumeExtractionResult(
            source_path=path,
            source_type="text",
            extraction_method="plain_text",
            raw_text=raw_text,
            cleaned_text=_normalize_text(cleaned),
            methods_tried=["plain_text"],
            warnings=warnings,
        )

    if suffix != ".pdf":
        raise ValueError(f"Unsupported resume format: {suffix}")

    candidates: list[tuple[str, str, bool]] = []
    extractors = [
        ("pypdf", _extract_pdf_with_pypdf, False),
        ("pdfplumber", _extract_pdf_with_pdfplumber, False),
        ("fitz", _extract_pdf_with_fitz, False),
        ("ocr", _extract_pdf_with_ocr, True),
    ]

    for name, extractor, uses_ocr in extractors:
        methods_tried.append(name)
        try:
            text = extractor(path)
        except Exception as exc:
            warnings.append(f"{name} failed: {exc}")
            continue
        if _normalize_text(text):
            candidates.append((name, text, uses_ocr))

    if not candidates:
        raise RuntimeError("Could not extract text from the PDF resume with the available extractors.")

    best_name, best_raw, best_ocr = max(candidates, key=lambda item: _text_quality_score(item[1]))
    cleaned = _normalize_text(best_raw)
    if use_llm_cleanup and cleaned:
        try:
            cleaned = _maybe_clean_with_llm(cleaned)
        except Exception as exc:
            warnings.append(f"LLM cleanup skipped: {exc}")

    return ResumeExtractionResult(
        source_path=path,
        source_type="pdf",
        extraction_method=best_name,
        raw_text=best_raw,
        cleaned_text=_normalize_text(cleaned),
        methods_tried=methods_tried,
        warnings=warnings,
        ocr_used=best_ocr,
    )


def load_resume_text(txt_path: Path, pdf_path: Path | None = None) -> str:
    if txt_path.exists():
        return _normalize_text(txt_path.read_text(encoding="utf-8-sig", errors="ignore"))
    if pdf_path and pdf_path.exists():
        return extract_resume_artifact(pdf_path, use_llm_cleanup=False).cleaned_text
    return ""
