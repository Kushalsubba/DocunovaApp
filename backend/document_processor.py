import os
import re
from pathlib import Path
from typing import Dict, Any, List
import PyPDF2


class DocumentProcessor:
    def __init__(self):
        pass

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_text(self, file_path: str) -> str:
        """Extract plain text (no markers). Used for compatibility."""
        return self.extract_text_with_pages(file_path)

    def extract_text_with_pages(self, file_path: str) -> str:
        """Extract text from a document, embedding [PAGE_N] markers for PDFs.

        For image-based (scanned) PDFs where embedded text is absent, OCR is
        performed automatically using pdf2image + pytesseract.
        """
        ext = Path(file_path).suffix.lower()
        text = ''
        if ext == '.pdf':
            return self._extract_pdf(file_path) # PDF already has pages
        elif ext == '.txt' or ext == '.md':
            text = self._read_text_file(file_path)
        elif ext in ('.docx', '.doc'):
            text = self._extract_docx(file_path)
        elif ext in ('.jpg', '.jpeg', '.png', '.tiff', '.bmp'):
            text = self._ocr_image(file_path)
        elif ext == '.csv':
            text = self._extract_csv(file_path)
        elif ext in ('.xls', '.xlsx'):
            text = self._extract_excel(file_path)
        
        return self._chunk_text(text) if text else ''

    def _chunk_text(self, text: str, words_per_chunk: int = 500) -> str:
        """Split raw text into chunks separated by [PAGE_N] markers for RAG citation."""
        words = text.split()
        if not words:
            return ''
        
        chunks = []
        for i in range(0, len(words), words_per_chunk):
            chunks.append(' '.join(words[i:i + words_per_chunk]))
            
        return '\n'.join(f'[PAGE_{i}]\n{chunk}' for i, chunk in enumerate(chunks, 1))

    def extract_metadata(self, file_path: str) -> Dict[str, Any]:
        """Extract metadata from a document."""
        metadata = {
            'author': None,
            'creation_date': None,
            'language': 'en',
            'page_count': 1,
            'custom_tags': {},
        }
        ext = Path(file_path).suffix.lower()
        if ext == '.pdf':
            metadata.update(self._pdf_metadata(file_path))
        elif ext == '.docx':
            metadata.update(self._docx_metadata(file_path))
        return metadata

    def page_texts_from_content(self, content: str) -> List[str]:
        """Split stored content (with [PAGE_N] markers) into per-page strings."""
        if '[PAGE_' not in content:
            return [content]
        parts = re.split(r'\[PAGE_\d+\]\n?', content)
        return [p for p in parts if p]  # drop empty preamble

    # ── PDF extraction ────────────────────────────────────────────────────────

    def _extract_pdf(self, file_path: str) -> str:
        pages = self._pdf_pages_embedded(file_path)

        # If all pages are empty (scanned / image-based PDF), try OCR
        if all(not t.strip() for t in pages):
            print(f"Embedded text empty, running OCR on {os.path.basename(file_path)}")
            pages = self._pdf_pages_ocr(file_path)

        if not pages:
            return ''
        return '\n'.join(f'[PAGE_{i}]\n{t}' for i, t in enumerate(pages, 1))

    def _pdf_pages_embedded(self, file_path: str) -> List[str]:
        """Extract embedded text from each PDF page."""
        pages = []
        try:
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    pages.append(page.extract_text() or '')
        except Exception as e:
            print(f"PyPDF2 error on {os.path.basename(file_path)}: {e}")
        return pages

    def _pdf_pages_ocr(self, file_path: str) -> List[str]:
        """OCR each page of a scanned PDF."""
        try:
            from pdf2image import convert_from_path
            import pytesseract
            images = convert_from_path(file_path, dpi=200)
            return [pytesseract.image_to_string(img) for img in images]
        except Exception as e:
            print(f"OCR error on {os.path.basename(file_path)}: {e}")
            return []

    # ── Other formats ─────────────────────────────────────────────────────────

    def _read_text_file(self, file_path: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            with open(file_path, 'r', encoding='latin-1') as f:
                return f.read()

    def _extract_docx(self, file_path: str) -> str:
        try:
            from docx import Document as DocxDoc
            doc = DocxDoc(file_path)
            return '\n'.join(p.text for p in doc.paragraphs)
        except Exception as e:
            print(f"DOCX error: {e}")
            return ''

    def _ocr_image(self, file_path: str) -> str:
        try:
            import pytesseract
            from PIL import Image
            return pytesseract.image_to_string(Image.open(file_path))
        except Exception as e:
            print(f"Image OCR error: {e}")
            return ''

    def _extract_csv(self, file_path: str) -> str:
        try:
            import pandas as pd
            df = pd.read_csv(file_path)
            return df.to_string()
        except Exception as e:
            print(f"CSV error: {e}")
            return ''

    def _extract_excel(self, file_path: str) -> str:
        try:
            import pandas as pd
            df = pd.read_excel(file_path)
            return df.to_string()
        except Exception as e:
            print(f"Excel error: {e}")
            return ''

    # ── Metadata ──────────────────────────────────────────────────────────────

    def _pdf_metadata(self, file_path: str) -> Dict[str, Any]:
        meta = {}
        try:
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                info = reader.metadata
                meta['author'] = info.author if info else None
                meta['creation_date'] = info.creation_date if info else None
                meta['page_count'] = len(reader.pages)
        except Exception as e:
            print(f"PDF metadata error: {e}")
        return meta

    def _docx_metadata(self, file_path: str) -> Dict[str, Any]:
        meta = {}
        try:
            from docx import Document as DocxDoc
            doc = DocxDoc(file_path)
            cp = doc.core_properties
            meta['author'] = cp.author
            meta['creation_date'] = cp.created
            meta['page_count'] = len(doc.sections) or 1
        except Exception as e:
            print(f"DOCX metadata error: {e}")
        return meta

    # ── Unused stubs kept for backward compatibility ───────────────────────────

    def detect_language(self, text: str) -> str:
        return 'en'

    def extract_tables(self, file_path: str) -> list:
        return []
