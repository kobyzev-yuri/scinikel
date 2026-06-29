"""
PDF-парсер — адаптация tiered-подхода из 3dtoday/document_parser.py.
PyPDF2 для текста, PyMuPDF (fitz) для изображений.
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import tempfile
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class PDFParser:
    """Синхронный парсер PDF для ingest-пайплайна scinikel."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self.headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ScinikelBot/1.0)",
        }

    def parse(self, source: str | Path, max_pages: int | None = None) -> dict[str, Any] | None:
        source_str = str(source)
        try:
            pdf_content = self._read_pdf_bytes(source_str)
            if not pdf_content:
                return None
            return self._parse_bytes(pdf_content, source_str, max_pages=max_pages)
        except Exception as exc:
            logger.error("PDF parse error: %s", exc, exc_info=True)
            return None

    def _read_pdf_bytes(self, source: str) -> bytes | None:
        if source.startswith("http"):
            with httpx.Client(timeout=self.timeout, headers=self.headers) as client:
                response = client.get(source)
                response.raise_for_status()
                return response.content
        path = Path(source)
        if path.exists():
            return path.read_bytes()
        return None

    def _parse_bytes(
        self,
        pdf_content: bytes,
        source: str,
        max_pages: int | None = None,
    ) -> dict[str, Any] | None:
        try:
            import PyPDF2
        except ImportError as exc:
            raise ImportError("Install PyPDF2: pip install PyPDF2") from exc

        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_content))
        total_pages = len(pdf_reader.pages)
        pages_to_parse = total_pages
        if max_pages is not None and max_pages > 0:
            pages_to_parse = min(max_pages, total_pages)

        content_parts: list[str] = []
        images: list[dict[str, Any]] = []

        # PyMuPDF — надёжнее для изображений (как в 3dtoday)
        try:
            import fitz

            stream = pdf_content if source.startswith("http") else None
            file_arg = None if source.startswith("http") else source
            pdf_doc = fitz.open(file_arg, stream=stream, filetype="pdf")
            for page_num in range(min(pages_to_parse, len(pdf_doc))):
                page = pdf_doc[page_num]
                for img_index, img in enumerate(page.get_images()):
                    try:
                        xref = img[0]
                        base_image = pdf_doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]
                        image_hash = hashlib.md5(image_bytes).hexdigest()[:8]
                        temp_dir = Path(tempfile.gettempdir()) / "scinikel_pdf_images"
                        temp_dir.mkdir(exist_ok=True)
                        temp_path = temp_dir / f"p{page_num + 1}_i{img_index + 1}_{image_hash}.{image_ext}"
                        temp_path.write_bytes(image_bytes)
                        images.append(
                            {
                                "url": str(temp_path),
                                "alt": f"Страница {page_num + 1}, рис. {img_index + 1}",
                                "page": page_num + 1,
                                "data": base64.b64encode(image_bytes).decode("utf-8"),
                                "mime_type": f"image/{image_ext}",
                                "temp_path": str(temp_path),
                            }
                        )
                    except Exception as img_exc:
                        logger.warning("Image extract failed p%s: %s", page_num + 1, img_exc)
            pdf_doc.close()
        except ImportError:
            logger.info("PyMuPDF not installed — images skipped")

        for page_num in range(pages_to_parse):
            text = pdf_reader.pages[page_num].extract_text() or ""
            if text.strip():
                content_parts.append(f"[стр. {page_num + 1}]\n{text.strip()}")

        content = "\n\n".join(content_parts)
        if not content:
            logger.warning("No text extracted from PDF: %s", source)
            return None

        title = Path(source).stem if not source.startswith("http") else source.rsplit("/", 1)[-1]
        if pages_to_parse < total_pages:
            content += f"\n\n[Обработано {pages_to_parse} из {total_pages} страниц]"

        return {
            "title": title,
            "content": content,
            "images": images,
            "source": source,
            "source_type": "pdf",
            "pages_total": total_pages,
            "pages_parsed": pages_to_parse,
        }


def parse_pdf(source: str | Path, max_pages: int | None = None) -> dict[str, Any] | None:
    return PDFParser().parse(source, max_pages=max_pages)
