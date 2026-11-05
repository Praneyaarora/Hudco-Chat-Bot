"""
HTML Document Extraction Adapter.
File: pipeline/adapters/html_adapter.py

Parses local HTML files or raw HTML strings without performing network operations.
Preserves heading hierarchy (h1-h6), paragraphs, list items, hyperlinks, and tables.
Conservative chrome filtering: strips only executable or non-text tags (script, style,
noscript, iframe, svg). Content inside header, footer, aside, and article containers
is preserved because substantive content (disclaimers, metadata, reports) often resides there.
Provides dual-mode parsing: uses BeautifulSoup if installed, with a robust
standard-library html.parser.HTMLParser fallback for zero-dependency execution.
"""

import re
import logging
from html.parser import HTMLParser
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Set
from urllib.parse import urljoin, urlparse

from pipeline.core.contracts import (
    DocumentFormat,
    BlockType,
    ContentBlock,
    StructuredTable,
    QualityWarning,
    WarningCategory,
    HTMLSourceLocator,
)
from pipeline.adapters.base import BaseDocumentAdapter, RawPageRecord, RawExtractionPayload
from pipeline.utils.text_normalizer import normalize_whitespace, clean_cell_text, is_empty_or_whitespace
from pipeline.utils.table_formatter import build_structured_table

logger = logging.getLogger("HTMLDocumentAdapter")

# Official HUDCO web domains approved for institutional document discovery
OFFICIAL_HUDCO_HOSTS: Set[str] = {
    "www.hudco.org.in",
    "hudco.org.in",
    "hudco.org",
    "www.hudco.org",
}

# Tags to strip entirely including contents (only non-content / script / binary tags)
IGNORED_TAGS: Set[str] = {"script", "style", "noscript", "iframe", "svg"}

# HTML void tags that do not have closing tags
VOID_TAGS: Set[str] = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr"
}


def classify_link(href: str, source_url: Optional[str] = None) -> Dict[str, Any]:
    """
    Classifies a hyperlink, resolves relative destinations against source_url,
    and identifies downloadable document types without making network calls.
    Preserves original_href alongside resolved_url.
    """
    href_clean = href.strip()
    href_lower = href_clean.lower()

    if href_lower.startswith("mailto:"):
        link_type = "mailto"
    elif href_lower.startswith("javascript:"):
        link_type = "javascript"
    elif href_lower.startswith("#"):
        link_type = "fragment"
    elif any(href_lower.endswith(ext) or f"{ext}?" in href_lower for ext in [".pdf", ".pdf.aspx"]):
        link_type = "pdf"
    elif any(href_lower.endswith(ext) or f"{ext}?" in href_lower for ext in [".docx", ".doc", ".xlsx", ".xls", ".zip", ".csv"]):
        link_type = "downloadable_file"
    elif any(href_lower.endswith(ext) or f"{ext}?" in href_lower for ext in [".html", ".htm", ".xhtml"]):
        link_type = "html_page"
    else:
        link_type = "html_page"

    resolved_url = urljoin(source_url, href_clean) if source_url else href_clean

    parsed = urlparse(resolved_url)
    is_official_host = parsed.netloc.lower() in OFFICIAL_HUDCO_HOSTS if parsed.netloc else False
    is_downloadable = link_type in {"pdf", "downloadable_file"}

    return {
        "text": "",
        "url": resolved_url,
        "original_href": href_clean,
        "resolved_url": resolved_url,
        "link_type": link_type,
        "is_official_host": is_official_host,
        "is_downloadable_document": is_downloadable,
    }


# ============================================================================
# Standard Library HTML Parser Fallback
# ============================================================================

class StandardLibraryHTMLParser(HTMLParser):
    """
    Zero-dependency HTML parser using Python's standard library html.parser.
    Extracts document title, heading hierarchy, paragraphs, lists, links, and tables.
    Explicitly represents DOM selectors as approximate when full CSS specificity is unavailable.
    """

    def __init__(self, source_url: Optional[str] = None):
        super().__init__(convert_charrefs=True)
        self.source_url = source_url
        self.title: str = ""
        self.headings: List[Dict[str, Any]] = []
        self.blocks: List[ContentBlock] = []
        self.tables: List[StructuredTable] = []
        self.warnings: List[str] = []

        # Tag and hierarchy tracking
        self._tag_stack: List[str] = []
        self._current_tag: Optional[str] = None
        self._ignored_depth = 0
        self._buffer: List[str] = []
        self._current_heading_level: Optional[int] = None
        self._heading_stack: List[str] = []

        # Link tracking
        self._in_link = False
        self._current_link_url: Optional[str] = None
        self._current_link_text: List[str] = []
        self._current_block_links: List[Dict[str, str]] = []

        # Table state
        self._in_table = False
        self._current_table_rows: List[List[str]] = []
        self._current_row: List[str] = []
        self._table_cell_buffer: List[str] = []
        self._table_count = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        tag_lower = tag.lower()
        self._current_tag = tag_lower

        if tag_lower in IGNORED_TAGS:
            self._ignored_depth += 1
            return

        if self._ignored_depth > 0:
            return

        if tag_lower not in VOID_TAGS:
            self._tag_stack.append(tag_lower)

        attr_dict = dict(attrs)

        if tag_lower == "title":
            self._buffer = []
        elif tag_lower in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush_text_buffer()
            self._current_heading_level = int(tag_lower[1])
            self._buffer = []
            self._current_block_links = []
        elif tag_lower in {"p", "li", "dt", "dd"}:
            self._flush_text_buffer()
            self._buffer = []
            self._current_block_links = []
        elif tag_lower == "a":
            href = attr_dict.get("href")
            if href:
                self._in_link = True
                self._current_link_url = href.strip()
                self._current_link_text = []
        elif tag_lower == "table":
            self._flush_text_buffer()
            self._in_table = True
            self._current_table_rows = []
        elif tag_lower == "tr" and self._in_table:
            self._current_row = []
        elif tag_lower in {"th", "td"} and self._in_table:
            self._table_cell_buffer = []

    def handle_endtag(self, tag: str):
        tag_lower = tag.lower()

        if tag_lower in IGNORED_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return

        if self._ignored_depth > 0:
            return

        # Maintain tag stack safely even if HTML is malformed
        if tag_lower in self._tag_stack:
            while self._tag_stack:
                popped = self._tag_stack.pop()
                if popped == tag_lower:
                    break

        if tag_lower == "a" and self._in_link:
            link_text = "".join(self._current_link_text).strip()
            href = self._current_link_url or ""
            link_info = classify_link(href, self.source_url)
            link_info["text"] = link_text

            if link_info["link_type"] not in {"javascript", "fragment"}:
                self._current_block_links.append(link_info)
                dest = link_info["resolved_url"] or href
                link_repr = f"[{link_text}]({dest})" if link_text else f"<{dest}>"
            else:
                link_repr = link_text

            if self._in_table:
                self._table_cell_buffer.append(link_repr)
            else:
                self._buffer.append(link_repr)

            self._in_link = False
            self._current_link_url = None
            self._current_link_text = []
            return

        if tag_lower == "title":
            self.title = normalize_whitespace("".join(self._buffer))
            self._buffer = []
        elif tag_lower in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            heading_text = normalize_whitespace("".join(self._buffer))
            links = list(self._current_block_links)
            if heading_text:
                level = self._current_heading_level or 1
                if level == 1:
                    self._heading_stack = [heading_text]
                elif level <= len(self._heading_stack):
                    self._heading_stack = self._heading_stack[:level - 1] + [heading_text]
                else:
                    self._heading_stack.append(heading_text)

                self.headings.append({
                    "title": heading_text,
                    "level": level,
                    "heading_path": list(self._heading_stack)
                })

                selector = " > ".join(self._tag_stack + [tag_lower])
                locator = HTMLSourceLocator(
                    source_url=self.source_url,
                    css_selector=selector,
                    heading_hierarchy=list(self._heading_stack),
                    is_approximate=True
                )
                self.blocks.append(ContentBlock(
                    block_id=f"html_blk_{len(self.blocks):03d}",
                    block_type=BlockType.HEADING,
                    text_content=heading_text,
                    locator=locator,
                    heading_level=level,
                    table_data=None,
                    is_boilerplate=False,
                    metadata={"links": links} if links else {}
                ))
            self._buffer = []
            self._current_block_links = []
            self._current_heading_level = None
        elif tag_lower in {"p", "li", "dt", "dd"}:
            self._flush_text_buffer(block_type=BlockType.LIST if tag_lower == "li" else BlockType.PARAGRAPH)
        elif tag_lower in {"th", "td"} and self._in_table:
            cell_val = clean_cell_text("".join(self._table_cell_buffer))
            self._current_row.append(cell_val)
            self._table_cell_buffer = []
        elif tag_lower == "tr" and self._in_table:
            if self._current_row and any(len(c) > 0 for c in self._current_row):
                self._current_table_rows.append(self._current_row)
            self._current_row = []
        elif tag_lower == "table" and self._in_table:
            self._in_table = False
            if len(self._current_table_rows) >= 2:
                self._table_count += 1
                table_id = f"html_tbl_{self._table_count:02d}"
                st = build_structured_table(self._current_table_rows, table_id=table_id)
                if st:
                    self.tables.append(st)
                    selector = " > ".join(self._tag_stack + ["table"])
                    locator = HTMLSourceLocator(
                        source_url=self.source_url,
                        css_selector=f"{selector}:nth-of-type({self._table_count})",
                        heading_hierarchy=list(self._heading_stack),
                        is_approximate=True
                    )
                    self.blocks.append(ContentBlock(
                        block_id=f"html_tbl_blk_{len(self.blocks):03d}",
                        block_type=BlockType.TABLE,
                        text_content=st.markdown_representation,
                        locator=locator,
                        table_data=st,
                        is_boilerplate=False
                    ))
            self._current_table_rows = []

    def handle_data(self, data: str):
        if self._ignored_depth > 0:
            return
        if self._in_link:
            self._current_link_text.append(data)
        elif self._in_table:
            self._table_cell_buffer.append(data)
        else:
            self._buffer.append(data)

    def _flush_text_buffer(self, block_type: BlockType = BlockType.PARAGRAPH):
        if not self._buffer:
            return
        raw_text = "".join(self._buffer)
        normalized = normalize_whitespace(raw_text)
        links = list(self._current_block_links)
        self._buffer = []
        self._current_block_links = []

        if normalized and not is_empty_or_whitespace(normalized):
            selector = " > ".join(self._tag_stack) if self._tag_stack else None
            locator = HTMLSourceLocator(
                source_url=self.source_url,
                css_selector=selector,
                heading_hierarchy=list(self._heading_stack),
                is_approximate=True
            )
            self.blocks.append(ContentBlock(
                block_id=f"html_blk_{len(self.blocks):03d}",
                block_type=block_type,
                text_content=normalized,
                locator=locator,
                table_data=None,
                is_boilerplate=False,
                metadata={"links": links} if links else {}
            ))


# ============================================================================
# HTML Document Adapter
# ============================================================================

class HTMLDocumentAdapter(BaseDocumentAdapter):
    """
    Extracts structured content from HTML pages.
    Preserves document title, headings, paragraphs, lists, links, and tables.
    Explicitly tracks approximate vs verified DOM element provenance.
    """

    SUPPORTED_MIME_TYPES = {
        "text/html",
        "application/xhtml+xml",
    }

    def can_handle(self, mime_type: str, file_path: Optional[Path] = None) -> bool:
        if mime_type.lower() in self.SUPPORTED_MIME_TYPES:
            return True
        if file_path and file_path.suffix.lower() in {".html", ".htm", ".xhtml"}:
            return True
        return False

    def extract_file(
        self,
        file_path: Path,
        config: Optional[Dict[str, Any]] = None
    ) -> RawExtractionPayload:
        """Extracts content from a local HTML file without making network calls."""
        if not file_path.exists():
            raise FileNotFoundError(f"Source HTML file does not exist: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                html_text = f.read()
        except Exception as e:
            return RawExtractionPayload(
                source_filename=file_path.name,
                document_format=DocumentFormat.HTML,
                total_physical_pages=1,
                errors=[f"Failed reading HTML file '{file_path.name}': {str(e)}"]
            )

        return self._parse_html(html_text, source_filename=file_path.name, config=config)

    def extract_bytes(
        self,
        data: bytes,
        filename: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None
    ) -> RawExtractionPayload:
        """Extracts content directly from in-memory HTML bytes."""
        html_text = data.decode("utf-8", errors="replace")
        return self._parse_html(html_text, source_filename=filename or "document.html", config=config)

    def _parse_html(
        self,
        html_content: str,
        source_filename: str,
        config: Optional[Dict[str, Any]] = None
    ) -> RawExtractionPayload:
        config = config or {}
        source_url = config.get("source_url")

        # Check if BeautifulSoup is available
        try:
            from bs4 import BeautifulSoup
            return self._parse_with_bs4(html_content, source_filename, source_url)
        except ImportError:
            # Fall back to standard library HTML parser
            return self._parse_with_stdlib(html_content, source_filename, source_url)

    def _parse_with_stdlib(
        self,
        html_content: str,
        source_filename: str,
        source_url: Optional[str]
    ) -> RawExtractionPayload:
        """Parses HTML using Python standard library parser."""
        parser = StandardLibraryHTMLParser(source_url=source_url)
        try:
            parser.feed(html_content)
            parser.close()
        except Exception as e:
            return RawExtractionPayload(
                source_filename=source_filename,
                document_format=DocumentFormat.HTML,
                total_physical_pages=1,
                errors=[f"HTML parser error in '{source_filename}': {str(e)}"]
            )

        # Assemble full text
        full_text = "\n\n".join(b.text_content for b in parser.blocks)
        is_empty = is_empty_or_whitespace(full_text)

        warnings: List[QualityWarning] = []
        if is_empty:
            warnings.append(QualityWarning(
                category=WarningCategory.BLANK_PAGE,
                message=f"HTML document '{source_filename}' contains zero extractable text content.",
                physical_page=1
            ))

        page_record = RawPageRecord(
            physical_page=1,
            printed_page=None,
            text=full_text,
            char_count=len(full_text),
            is_empty=is_empty,
            is_suspiciously_short=not is_empty and len(full_text) < 100,
            is_scanned=False,
            tables=parser.tables,
            blocks=parser.blocks,
            warnings=["EMPTY_HTML_CONTENT"] if is_empty else []
        )

        metadata: Dict[str, Any] = {
            "title": parser.title or source_filename,
            "source_url": source_url or "",
            "parser_engine": "python_html_parser_stdlib"
        }

        outline_entries = [
            {"title": h["title"], "level": h["level"], "physical_page": 1}
            for h in parser.headings
        ]

        return RawExtractionPayload(
            source_filename=source_filename,
            document_format=DocumentFormat.HTML,
            total_physical_pages=1,
            metadata=metadata,
            outline_entries=outline_entries,
            pages=[page_record],
            warnings=warnings,
            errors=[]
        )

    def _parse_with_bs4(
        self,
        html_content: str,
        source_filename: str,
        source_url: Optional[str]
    ) -> RawExtractionPayload:
        """Parses HTML using BeautifulSoup with consistent provenance and content preservation."""
        from bs4 import BeautifulSoup, Tag

        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Strip only non-content / script / binary tags
        for element in soup.find_all(list(IGNORED_TAGS)):
            element.decompose()

        # 2. Extract Title
        title = soup.title.get_text().strip() if soup.title else source_filename

        # 3. Extract blocks, headings, and tables
        blocks: List[ContentBlock] = []
        tables: List[StructuredTable] = []
        headings: List[Dict[str, Any]] = []
        heading_stack: List[str] = []
        table_counter = 0

        body = soup.body or soup

        # Helper to compute CSS selector and provenance
        def _get_locator(element: Tag) -> HTMLSourceLocator:
            parts = []
            curr = element
            has_id = False
            while curr and curr.name and curr.name != "[document]":
                elem_id = curr.get("id")
                if elem_id:
                    parts.insert(0, f"#{elem_id}")
                    has_id = True
                    break
                parts.insert(0, curr.name.lower())
                curr = curr.parent
            selector = " > ".join(parts) if parts else None
            return HTMLSourceLocator(
                source_url=source_url,
                css_selector=selector,
                heading_hierarchy=list(heading_stack),
                is_approximate=not has_id
            )

        # Helper to extract links and convert to markdown within an element
        def _extract_links_and_text(element: Tag) -> Tuple[str, List[Dict[str, Any]]]:
            links: List[Dict[str, Any]] = []
            for a in element.find_all("a", href=True):
                href = a["href"].strip()
                a_text = a.get_text().strip()
                link_info = classify_link(href, source_url)
                link_info["text"] = a_text
                if link_info["link_type"] not in {"javascript", "fragment"}:
                    links.append(link_info)
                    dest = link_info["resolved_url"] or href
                    a.replace_with(f"[{a_text}]({dest})" if a_text else f"<{dest}>")
                else:
                    a.replace_with(a_text)
            raw_text = element.get_text()
            return normalize_whitespace(raw_text), links

        for elem in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "table"], recursive=True):
            tag_name = elem.name.lower()

            # Avoid processing nested elements twice
            if tag_name == "p" and elem.find_parent("li"):
                continue
            if tag_name in {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"} and elem.find_parent("table"):
                continue

            if tag_name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                level = int(tag_name[1])
                text, links = _extract_links_and_text(elem)
                if text:
                    if level == 1:
                        heading_stack = [text]
                    elif level <= len(heading_stack):
                        heading_stack = heading_stack[:level - 1] + [text]
                    else:
                        heading_stack.append(text)

                    headings.append({"title": text, "level": level, "physical_page": 1})
                    locator = _get_locator(elem)
                    blocks.append(ContentBlock(
                        block_id=f"html_blk_{len(blocks):03d}",
                        block_type=BlockType.HEADING,
                        text_content=text,
                        locator=locator,
                        heading_level=level,
                        table_data=None,
                        is_boilerplate=False,
                        metadata={"links": links} if links else {}
                    ))

            elif tag_name in {"p", "li"}:
                text, links = _extract_links_and_text(elem)
                if text and not is_empty_or_whitespace(text):
                    locator = _get_locator(elem)
                    blocks.append(ContentBlock(
                        block_id=f"html_blk_{len(blocks):03d}",
                        block_type=BlockType.LIST if tag_name == "li" else BlockType.PARAGRAPH,
                        text_content=text,
                        locator=locator,
                        table_data=None,
                        is_boilerplate=False,
                        metadata={"links": links} if links else {}
                    ))

            elif tag_name == "table":
                table_counter += 1
                rows: List[List[str]] = []
                for tr in elem.find_all("tr"):
                    cells = []
                    for td in tr.find_all(["th", "td"]):
                        cell_text, _ = _extract_links_and_text(td)
                        cells.append(clean_cell_text(cell_text))
                    if any(len(c) > 0 for c in cells):
                        rows.append(cells)

                if len(rows) >= 2:
                    table_id = f"html_tbl_{table_counter:02d}"
                    st = build_structured_table(rows, table_id=table_id)
                    if st:
                        tables.append(st)
                        locator = _get_locator(elem)
                        blocks.append(ContentBlock(
                            block_id=f"html_tbl_blk_{len(blocks):03d}",
                            block_type=BlockType.TABLE,
                            text_content=st.markdown_representation,
                            locator=locator,
                            table_data=st,
                            is_boilerplate=False
                        ))

        full_text = "\n\n".join(b.text_content for b in blocks)
        is_empty = is_empty_or_whitespace(full_text)

        warnings: List[QualityWarning] = []
        if is_empty:
            warnings.append(QualityWarning(
                category=WarningCategory.BLANK_PAGE,
                message=f"HTML document '{source_filename}' contains zero extractable text content.",
                physical_page=1
            ))

        page_record = RawPageRecord(
            physical_page=1,
            printed_page=None,
            text=full_text,
            char_count=len(full_text),
            is_empty=is_empty,
            is_suspiciously_short=not is_empty and len(full_text) < 100,
            is_scanned=False,
            tables=tables,
            blocks=blocks,
            warnings=["EMPTY_HTML_CONTENT"] if is_empty else []
        )

        metadata: Dict[str, Any] = {
            "title": title,
            "source_url": source_url or "",
            "parser_engine": "beautifulsoup4"
        }

        return RawExtractionPayload(
            source_filename=source_filename,
            document_format=DocumentFormat.HTML,
            total_physical_pages=1,
            metadata=metadata,
            outline_entries=headings,
            pages=[page_record],
            warnings=warnings,
            errors=[]
        )

