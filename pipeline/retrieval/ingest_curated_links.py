"""
Ingestion script for Curated Official HUDCO Links.
Fetches, processes, structures and saves official live HUDCO web pages and documents into
data/curated_links/official_hudco_links.json.
"""

import os
import json
import urllib.request
import ssl
import re
import io
import hashlib
import pypdf
from html.parser import HTMLParser


class CleanHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignore = False
        self.current_tag = ""

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        if tag in ("script", "style", "nav", "footer", "noscript", "header"):
            self.ignore = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "div", "tr", "table"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "noscript", "header"):
            self.ignore = False
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "div", "tr", "table"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignore:
            txt = data.strip()
            if txt:
                self.parts.append(txt + " ")


def extract_html(url: str) -> str:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, context=ctx, timeout=20) as r:
        html = r.read().decode("utf-8", errors="ignore")

    # Isolate <main> content if available to strip header/nav clutter
    main_match = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL | re.IGNORECASE)
    if main_match:
        html = main_match.group(1)
    else:
        # Strip <header> and <nav>
        html = re.sub(r"<header[^>]*>.*?</header>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<nav[^>]*>.*?</nav>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Strip cookie modal and accessibility clutter
    html = re.sub(r"<footer[^>]*>.*?</footer>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<div[^>]*class=[\"'][^\"']*cookie[^\"']*[\"'][^>]*>.*?</div>", "", html, flags=re.DOTALL | re.IGNORECASE)

    p = CleanHTMLParser()
    p.feed(html)
    raw = "".join(p.parts)
    raw = re.sub(r"[ \t]+", " ", raw)
    # Remove cookie / accessibility boilerplate
    raw = re.sub(r"(?:Cookie Policy|Accept All|Optional Cookies|Accessibility Tools|Font Size Increase|Grayscale).*?(?=\n\n|$)", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\n\s*\n+", "\n\n", raw).strip()
    return raw


def extract_pdf(url: str):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        reader = pypdf.PdfReader(io.BytesIO(r.read()))
        pages = []
        for i, page in enumerate(reader.pages):
            txt = page.extract_text() or ""
            txt = re.sub(r"[ \t]+", " ", txt).strip()
            if txt:
                pages.append((i + 1, txt))
        return pages


def run_ingestion():
    targets = [
        {
            "id": "link_board",
            "url": "https://hudco.org.in/Leadership?type=board",
            "title": "HUDCO Board of Directors & Key Leadership (Chairman & MD, Functional Directors, Govt Nominees)",
            "type": "html",
            "tier": "Tier 1A - Official Live Web Page",
            "recency_score": 1.20,
            "category": "leadership_board"
        },
        {
            "id": "link_management",
            "url": "https://hudco.org.in/Leadership?type=management",
            "title": "HUDCO Management Team (Chief Vigilance Officer, Senior Executive Directors, Executive Directors & Company Secretary)",
            "type": "html",
            "tier": "Tier 1A - Official Live Web Page",
            "recency_score": 1.20,
            "category": "leadership_management"
        },
        {
            "id": "link_corporate_office",
            "url": "https://hudco.org.in/corporate-office",
            "title": "HUDCO Corporate & Registered Office (Address, Headquarters, Phone, Fax, Email)",
            "type": "html",
            "tier": "Tier 1A - Official Live Web Page",
            "recency_score": 1.15,
            "category": "corporate_office"
        },
        {
            "id": "link_contact_us",
            "url": "https://hudco.org.in/contact-us",
            "title": "HUDCO Contact Directory & Grievances (Helpline, RTI, Grievance Officer, Regional Offices)",
            "type": "html",
            "tier": "Tier 1A - Official Live Web Page",
            "recency_score": 1.15,
            "category": "contact_directory"
        },
        {
            "id": "link_shareholders",
            "url": "https://hudco.org.in/shareholders-meetings",
            "title": "HUDCO Shareholders & General Meetings (AGM, EGM, Scrutinizer Reports, Voting Results)",
            "type": "html",
            "tier": "Tier 1A - Official Live Web Page",
            "recency_score": 1.15,
            "category": "shareholder_meetings"
        },
        {
            "id": "link_orgchart_pdf",
            "url": "https://hudco.org.in/writereaddata/orgchart.pdf",
            "title": "HUDCO Official Organogram & Organization Structure Chart",
            "type": "pdf",
            "tier": "Tier 1B - Official Organogram PDF",
            "recency_score": 1.05,
            "category": "org_chart"
        },
        {
            "id": "link_webdirectory_pdf",
            "url": "https://hudco.org.in/writereaddata/webdirectory.pdf",
            "title": "HUDCO Internal Telephone & Office Directory (Officers & Extensions)",
            "type": "pdf",
            "tier": "Tier 1C - Internal Directory PDF",
            "recency_score": 1.02,
            "category": "web_directory"
        },
        {
            "id": "link_faq_pdf",
            "url": "https://www.hudco.org.in/writereaddata/FAQ-hudco.pdf",
            "title": "HUDCO Frequently Asked Questions (Official Corporate FAQ)",
            "type": "pdf",
            "tier": "Tier 1C - Official FAQ PDF",
            "recency_score": 1.03,
            "category": "official_faq"
        }
    ]

    chunks = []

    for t in targets:
        print(f"Fetching {t['id']} from {t['url']}...")
        try:
            if t["type"] == "html":
                content = extract_html(t["url"])

                # Add a unified complete chunk for leadership and management so full board is never fragmented
                if t["id"] == "link_board":
                    chunks.append({
                        "chunk_id": "link_board_complete",
                        "title": "HUDCO Board of Directors (Chairman & MD Sanjay Kulshrestha, Functional Directors, Govt Nominee Directors)",
                        "url": t["url"],
                        "priority_tier": t["tier"],
                        "recency_score": 1.30,
                        "recency_tier": "Official Live Website (Latest Active)",
                        "category": t["category"],
                        "source_type": "official_link",
                        "fiscal_year": "2026",
                        "content": content,
                        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()
                    })
                elif t["id"] == "link_management":
                    chunks.append({
                        "chunk_id": "link_management_complete",
                        "title": "HUDCO Management Team (Chief Vigilance Officer, Senior EDs, EDs, Company Secretary)",
                        "url": t["url"],
                        "priority_tier": t["tier"],
                        "recency_score": 1.30,
                        "recency_tier": "Official Live Website (Latest Active)",
                        "category": t["category"],
                        "source_type": "official_link",
                        "fiscal_year": "2026",
                        "content": content,
                        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()
                    })

                paragraphs = content.split("\n\n")
                cur_chunk = []
                cur_len = 0
                part_idx = 1
                for p in paragraphs:
                    cur_chunk.append(p)
                    cur_len += len(p)
                    if cur_len >= 1600:
                        chunk_text = "\n\n".join(cur_chunk).strip()
                        chunks.append({
                            "chunk_id": f"{t['id']}_part_{part_idx:02d}",
                            "title": f"{t['title']} (Part {part_idx})",
                            "url": t["url"],
                            "priority_tier": t["tier"],
                            "recency_score": t["recency_score"],
                            "recency_tier": "Official Live Website (Latest Active)",
                            "category": t["category"],
                            "source_type": "official_link",
                            "fiscal_year": "2026",
                            "content": chunk_text,
                            "content_sha256": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
                        })
                        cur_chunk = []
                        cur_len = 0
                        part_idx += 1
                if cur_chunk:
                    chunk_text = "\n\n".join(cur_chunk).strip()
                    chunks.append({
                        "chunk_id": f"{t['id']}_part_{part_idx:02d}",
                        "title": f"{t['title']} (Part {part_idx})",
                        "url": t["url"],
                        "priority_tier": t["tier"],
                        "recency_score": t["recency_score"],
                        "recency_tier": "Official Live Website (Latest Active)",
                        "category": t["category"],
                        "source_type": "official_link",
                        "fiscal_year": "2026",
                        "content": chunk_text,
                        "content_sha256": hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
                    })
            else:
                pages = extract_pdf(t["url"])
                for page_num, text in pages:
                    chunks.append({
                        "chunk_id": f"{t['id']}_page_{page_num:02d}",
                        "title": f"{t['title']} (Page {page_num})",
                        "url": t["url"],
                        "priority_tier": t["tier"],
                        "recency_score": t["recency_score"],
                        "recency_tier": "Official Document PDF (Latest Active)",
                        "category": t["category"],
                        "source_type": "official_link",
                        "fiscal_year": "2026",
                        "page": page_num,
                        "content": text,
                        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()
                    })
            print(f"  -> Extracted successfully from {t['id']}")
        except Exception as exc:
            print(f"  -> Error fetching {t['id']}: {exc}")

    out_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "curated_links")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "official_hudco_links.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"total_chunks": len(chunks), "chunks": chunks}, f, indent=2, ensure_ascii=False)

    print(f"Finished: Ingested {len(chunks)} chunks into {out_path}")
    return out_path


if __name__ == "__main__":
    run_ingestion()
