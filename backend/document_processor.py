import os
import re
from pathlib import Path
from typing import Dict, Any, List
import PyPDF2


class DocumentProcessor:
    def __init__(self):
        pass

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_as_markdown(self, file_path: str) -> str:
        """Extract document content as structured Markdown for vector storage.

        Preserves headings, lists, and tables so RAG chunks carry semantic
        structure rather than flattened plain text.
        """
        ext = Path(file_path).suffix.lower()
        if ext == '.pdf':
            return self._pdf_to_markdown(file_path)
        elif ext in ('.docx', '.doc'):
            return self._docx_to_markdown(file_path)
        elif ext in ('.txt', '.md'):
            return self._read_text_file(file_path)
        elif ext == '.csv':
            return self._csv_to_markdown(file_path)
        elif ext in ('.xls', '.xlsx'):
            return self._excel_to_markdown(file_path)
        elif ext in ('.jpg', '.jpeg', '.png', '.tiff', '.bmp'):
            return self._ocr_image(file_path)
        return ''

    def extract_text(self, file_path: str) -> str:
        """Extract plain text (no markers). Used for compatibility."""
        return self.extract_text_with_pages(file_path)

    def extract_text_with_pages(self, file_path: str) -> str:
        """Extract text from a document, embedding [PAGE_N] markers for PDFs."""
        ext = Path(file_path).suffix.lower()
        text = ''
        if ext == '.pdf':
            return self._extract_pdf(file_path)
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
        return [p for p in parts if p]

    # ── Markdown extraction ───────────────────────────────────────────────────

    def _pdf_to_markdown(self, file_path: str) -> str:
        """Extract PDF pages as Markdown with [PAGE_N] markers and heading detection."""
        pages = self._pdf_pages_embedded(file_path)
        if all(not t.strip() for t in pages):
            print(f"Embedded text empty, running OCR on {os.path.basename(file_path)}")
            pages = self._pdf_pages_ocr(file_path)
        if not pages:
            return ''
        parts = []
        for i, page_text in enumerate(pages, 1):
            if not page_text.strip():
                continue
            parts.append(f'[PAGE_{i}]\n{self._format_pdf_page_as_markdown(page_text)}')
        return '\n'.join(parts)

    def _format_pdf_page_as_markdown(self, page_text: str) -> str:
        """Apply heuristic markdown formatting to a PDF page's raw text."""
        lines = page_text.splitlines()
        formatted = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                formatted.append('')
                continue
            # Short ALL-CAPS lines or short Title Case lines are likely headings
            words = stripped.split()
            if len(words) <= 10 and len(stripped) < 80:
                if stripped.isupper():
                    formatted.append(f'## {stripped}')
                    continue
                if stripped.istitle() and not stripped.endswith('.'):
                    formatted.append(f'### {stripped}')
                    continue
            formatted.append(stripped)
        return '\n'.join(formatted)

    def _docx_to_markdown(self, file_path: str) -> str:
        """Convert a DOCX file to Markdown preserving headings, lists, and tables."""
        try:
            from docx import Document as DocxDoc
            from docx.table import Table
            from docx.text.paragraph import Paragraph

            doc = DocxDoc(file_path)
            lines = []

            for block in doc.element.body:
                tag = block.tag.split('}')[-1] if '}' in block.tag else block.tag

                if tag == 'p':
                    para = Paragraph(block, doc)
                    style_name = para.style.name if para.style else ''
                    text = para.text.strip()

                    if not text:
                        lines.append('')
                        continue

                    if style_name.startswith('Heading 1'):
                        lines.append(f'# {text}')
                    elif style_name.startswith('Heading 2'):
                        lines.append(f'## {text}')
                    elif style_name.startswith('Heading 3'):
                        lines.append(f'### {text}')
                    elif style_name.startswith('Heading'):
                        lines.append(f'#### {text}')
                    elif 'List Bullet' in style_name:
                        lines.append(f'- {text}')
                    elif 'List Number' in style_name:
                        lines.append(f'1. {text}')
                    else:
                        lines.append(text)

                elif tag == 'tbl':
                    table = Table(block, doc)
                    md_table = self._docx_table_to_markdown(table)
                    if md_table:
                        lines.extend(['', md_table, ''])

            return '\n'.join(lines)
        except Exception as e:
            print(f"DOCX markdown error, falling back to plain text: {e}")
            return self._extract_docx(file_path)

    def _docx_table_to_markdown(self, table) -> str:
        """Convert a python-docx Table object to a Markdown table string."""
        rows = [[cell.text.strip().replace('\n', ' ') for cell in row.cells]
                for row in table.rows]
        if not rows:
            return ''
        # De-duplicate merged cells in each row
        cols = max(len(r) for r in rows)
        header = rows[0]
        sep = ['---'] * cols
        lines = [
            '| ' + ' | '.join(header) + ' |',
            '| ' + ' | '.join(sep) + ' |',
        ]
        for row in rows[1:]:
            padded = (row + [''] * cols)[:cols]
            lines.append('| ' + ' | '.join(padded) + ' |')
        return '\n'.join(lines)

    def _csv_to_markdown(self, file_path: str) -> str:
        """Convert CSV file to a Markdown table."""
        try:
            import pandas as pd
            df = pd.read_csv(file_path)
            return self._dataframe_to_markdown(df)
        except Exception as e:
            print(f"CSV markdown error: {e}")
            return self._extract_csv(file_path)

    def _excel_to_markdown(self, file_path: str) -> str:
        """Convert each sheet of an Excel file to a Markdown table section."""
        try:
            import pandas as pd
            xls = pd.ExcelFile(file_path)
            parts = []
            for sheet_name in xls.sheet_names:
                df = pd.read_excel(xls, sheet_name=sheet_name)
                parts.append(
                    f'## Sheet: {sheet_name}\n\n{self._dataframe_to_markdown(df)}'
                )
            return '\n\n'.join(parts)
        except Exception as e:
            print(f"Excel markdown error: {e}")
            return self._extract_excel(file_path)

    def _dataframe_to_markdown(self, df) -> str:
        """Convert a pandas DataFrame to a Markdown table string."""
        df = df.fillna('')
        cols = [str(c) for c in df.columns]
        lines = [
            '| ' + ' | '.join(cols) + ' |',
            '| ' + ' | '.join(['---'] * len(cols)) + ' |',
        ]
        for _, row in df.iterrows():
            vals = [str(v).replace('\n', ' ').replace('|', '\\|') for v in row]
            lines.append('| ' + ' | '.join(vals) + ' |')
        return '\n'.join(lines)

    # ── PDF extraction ────────────────────────────────────────────────────────

    def _extract_pdf(self, file_path: str) -> str:
        pages = self._pdf_pages_embedded(file_path)
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
