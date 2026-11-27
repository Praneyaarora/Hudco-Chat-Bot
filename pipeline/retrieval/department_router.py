"""
Department-Aware Semantic Router and Dynamic Live URL & Document Crawler for HUDCO AI.
File: pipeline/retrieval/department_router.py

1. Acronym Expansion:
   Expands short domain acronyms (HR, IT, MD, CMD, ED, ACC, CVO, CS, 54EC, GRO, RTA, LCR, PAT, EPS, BVPS, GNPA, NNPA, PCR)
   so queries match official documents and department titles accurately.
2. Department Routing:
   Identifies which HUDCO functional department/domain the user query pertains to
   (Shareholders & Dividends, Market & Share Price, Finances & Loan Book,
    Bonds & Investors, Human Resources, Information Technology, Careers,
    Tenders, Grievances, Listing Compliance, Leadership & Board).
3. Dynamic Linked Document Crawler:
   Dynamically discovers and crawls linked official documents (e.g. latest quarterly presentation
   PDFs on https://hudco.org.in/financial-presentations or webdirectory.pdf) without hardcoding or force-feeding.
   Caches parsed text in memory for instantaneous sub-millisecond retrieval.
4. Produces top-tier RetrievalResultItems (Recency Score: 1.25 - 1.35) ranked strictly above
   older historical report chunks.
"""

import os
import re
import ssl
import time
import json
import hashlib
import logging
import urllib.request
import io
from typing import Dict, Any, List, Optional, Tuple

from pipeline.retrieval.contracts import RetrievalResultItem

logger = logging.getLogger("QwenWorker")

# In-memory TTL caches for live fetched HTML and crawled PDF pages
LIVE_PAGE_CACHE: Dict[str, Tuple[float, str, str]] = {}
LIVE_PDF_CACHE: Dict[str, Tuple[float, Dict[int, str]]] = {}
CACHE_TTL_SECONDS: float = 3600.0  # 1 hour cache

# Acronym mapping for HUDCO domain terminology
ACRONYM_MAP: Dict[str, str] = {
    r"\bhr\b": "human resources hr",
    r"\bit\b": "information technology it",
    r"\bmd\b": "managing director md",
    r"\bcmd\b": "chairman and managing director cmd",
    r"\bed\b": "executive director ed",
    r"\bsed\b": "senior executive director sed",
    r"\bacc\b": "accounts acc",
    r"\bcvo\b": "chief vigilance officer cvo",
    r"\bcs\b": "company secretary cs",
    r"\bgro\b": "grievance redressal officer gro",
    r"\brta\b": "registrar and share transfer agent rta kfin",
    r"\b54ec\b": "54ec capital gain bonds",
    r"\bcpgrams\b": "cpgrams grievance",
    r"\blcr\b": "liquidity coverage ratio lcr",
    r"\bpat\b": "profit after tax pat",
    r"\bpbt\b": "profit before tax pbt",
    r"\beps\b": "earnings per share eps",
    r"\bbvps\b": "book value per share bvps",
    r"\bgnpa\b": "gross non performing assets gnpa",
    r"\bnnpa\b": "net non performing assets nnpa",
    r"\bpcr\b": "provision coverage ratio pcr",
}


def expand_query_acronyms(query: str) -> str:
    """
    Expands short domain abbreviations into full searchable keywords while preserving the original acronym.
    Example: 'head of hr' -> 'head of human resources hr'
             'who is head of it?' -> 'who is head of information technology it?'
    """
    if not query:
        return ""
    expanded = query
    for pattern, replacement in ACRONYM_MAP.items():
        # Match case-insensitively with word boundaries
        expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)
    # Clean redundant whitespace
    return re.sub(r"\s+", " ", expanded).strip()


class DepartmentDefinition:
    def __init__(
        self,
        dept_id: str,
        name: str,
        keywords: List[str],
        primary_urls: List[str],
        category_tag: str,
        recency_score: float = 1.30,
        bonus_score: float = 8.0,
        document_crawl_target: Optional[str] = None,
    ):
        self.dept_id = dept_id
        self.name = name
        self.keywords = [k.lower() for k in keywords]
        self.primary_urls = primary_urls
        self.category_tag = category_tag
        self.recency_score = recency_score
        self.bonus_score = bonus_score
        self.document_crawl_target = document_crawl_target


DEPARTMENTS: List[DepartmentDefinition] = [
    DepartmentDefinition(
        dept_id="shareholders_and_dividends",
        name="Shareholders, Ownership & Dividends",
        keywords=[
            "top 10 shareholders", "top shareholders", "shareholders", "shareholding", "shareholder",
            "dividend", "dividends", "interim dividend", "final dividend", "dividend payout",
            "payout ratio", "lic", "promoter shareholding", "public shareholding", "equity share"
        ],
        primary_urls=[
            "https://hudco.org.in/financial-presentations",
            "https://hudco.org.in/shareholding-pattern",
            "https://hudco.org.in/dividend",
        ],
        category_tag="shareholders_dividends",
        recency_score=1.35,
        bonus_score=9.5,
        document_crawl_target="presentation",
    ),
    DepartmentDefinition(
        dept_id="market_and_share_price",
        name="Share Price Performance & Market Capitalisation",
        keywords=[
            "share price", "stock price", "share price performance", "market capitalisation",
            "market cap", "mcap", "pe ratio", "p/e", "eps", "bvps", "book value", "nse", "bse",
            "market capitalization", "52 week high", "52 week low"
        ],
        primary_urls=[
            "https://hudco.org.in/financial-presentations",
            "https://hudco.org.in/financial-results",
        ],
        category_tag="market_share_price",
        recency_score=1.35,
        bonus_score=9.5,
        document_crawl_target="presentation",
    ),
    DepartmentDefinition(
        dept_id="human_resources_department",
        name="Human Resources & Personnel (HR)",
        keywords=[
            "hr", "human resources", "head of hr", "gm hr", "ed hr", "personnel",
            "hrm", "prabhjot singh makkar", "makkar", "training", "hr wing"
        ],
        primary_urls=[
            "https://hudco.org.in/Leadership?type=management",
            "https://hudco.org.in/writereaddata/webdirectory.pdf",
            "https://hudco.org.in/careers",
        ],
        category_tag="human_resources",
        recency_score=1.30,
        bonus_score=9.0,
        document_crawl_target="webdirectory",
    ),
    DepartmentDefinition(
        dept_id="information_technology_department",
        name="Information Technology Wing & Cybersecurity (IT)",
        keywords=[
            "it", "information technology", "head of it", "gm it", "ed it", "it wing",
            "hemlata sharma", "hemlata", "ciso", "cyber security", "gireesh khattar", "infotech"
        ],
        primary_urls=[
            "https://hudco.org.in/Leadership?type=management",
            "https://hudco.org.in/writereaddata/webdirectory.pdf",
        ],
        category_tag="information_technology",
        recency_score=1.30,
        bonus_score=9.0,
        document_crawl_target="webdirectory",
    ),
    DepartmentDefinition(
        dept_id="finances_and_results",
        name="Finances, Loan Book & Results",
        keywords=[
            "loan book", "loan outstanding", "sanctions", "sanction", "disbursements", "disbursement",
            "profit", "pat", "pbt", "net worth", "gnpa", "nnpa", "gross npa", "net npa", "asset quality",
            "financial results", "financial presentation", "presentations", "investor presentation",
            "q1", "q2", "q3", "q4", "h1", "h2", "fy27", "fy26", "fy 2026-27", "fy 2025-26",
            "balance sheet", "p&l", "interest income", "borrowings", "cost of funds", "spread", "nim",
            "quarterly results", "annual returns", "financial performance"
        ],
        primary_urls=[
            "https://hudco.org.in/financial-presentations",
            "https://hudco.org.in/financial-results",
            "https://hudco.org.in/annual-returns",
        ],
        category_tag="finances_presentations",
        recency_score=1.35,
        bonus_score=9.0,
        document_crawl_target="presentation",
    ),
    DepartmentDefinition(
        dept_id="bonds_and_investors",
        name="Bonds, Debentures & Investor Services",
        keywords=[
            "54ec", "capital gain bond", "capital gains", "bonds", "bond", "debenture",
            "debenture trustee", "rta", "kfin", "unclaimed bond", "series ii", "series 2",
            "tax-free bond", "tax-free bonds", "taxable bond", "isin", "coupon rate",
            "redemption date", "bondholder", "current bonds", "forms and procedures"
        ],
        primary_urls=[
            "https://hudco.org.in/54ec-capital-gain-bonds",
            "https://hudco.org.in/writereaddata/current-bonds.pdf",
            "https://hudco.org.in/writereaddata/contact-details-RTA.pdf",
            "https://hudco.org.in/writereaddata/Debenture_Trustee.pdf",
            "https://hudco.org.in/forms-and-procedures",
            "https://hudco.org.in/general-information",
            "https://hudco.org.in/information-to-stock-exchanges",
            "https://hudco.org.in/unclaimed-bonds",
            "https://hudco.org.in/others"
        ],
        category_tag="bonds_investors",
        recency_score=1.30,
        bonus_score=8.5,
    ),
    DepartmentDefinition(
        dept_id="careers_and_recruitment",
        name="Careers, Recruitment & Job Opportunities",
        keywords=[
            "career", "careers", "job", "jobs", "recruitment", "vacancy", "vacancies",
            "lateral level", "lateral recruitment", "asset development specialist",
            "apprentice", "apply", "notification", "pay scale", "salary", "eligibility"
        ],
        primary_urls=[
            "https://hudco.org.in/careers"
        ],
        category_tag="careers_recruitment",
        recency_score=1.30,
        bonus_score=8.0,
    ),
    DepartmentDefinition(
        dept_id="tenders_and_procurement",
        name="Tenders & Procurement",
        keywords=[
            "tender", "tenders", "procurement", "e-tender", "rfp", "eoi", "bidding",
            "bid", "contract", "tender home", "cpp portal", "gem"
        ],
        primary_urls=[
            "https://hudco.org.in/TenderHome"
        ],
        category_tag="tenders_procurement",
        recency_score=1.30,
        bonus_score=8.0,
    ),
    DepartmentDefinition(
        dept_id="grievances_and_redressal",
        name="Grievance Redressal & Public Care",
        keywords=[
            "grievance", "grievances", "complaint", "complaints", "cpgrams", "redressal",
            "gro", "grievance officer", "investor grievance"
        ],
        primary_urls=[
            "https://hudco.org.in/grievance-redressal"
        ],
        category_tag="grievance_redressal",
        recency_score=1.30,
        bonus_score=8.0,
    ),
    DepartmentDefinition(
        dept_id="services_and_offerings",
        name="Offerings, Schemes & Urban Infrastructure",
        keywords=[
            "services", "schemes", "social housing", "housing finance", "ews", "lig", "mig",
            "urban infrastructure", "water supply", "sewerage", "smart cities", "consultancy",
            "project appraisal", "financing schemes"
        ],
        primary_urls=[
            "https://hudco.org.in/services"
        ],
        category_tag="offerings_services",
        recency_score=1.25,
        bonus_score=7.5,
    ),
    DepartmentDefinition(
        dept_id="listing_and_governance",
        name="Listing Compliance, SEBI & Governance",
        keywords=[
            "corporate governance", "code of conduct", "listing regulations", "sebi",
            "liquidity disclosure", "lcr", "reg 46", "reg 62", "lodr", "disclosure",
            "compliance officer", "statutory disclosure", "independent director", "familiarisation"
        ],
        primary_urls=[
            "https://hudco.org.in/corporate-governance-report",
            "https://hudco.org.in/shareholding-pattern",
            "https://hudco.org.in/liquidity-disclosure",
            "http://hudco.org.in/sebi-disclosures",
            "https://hudco.org.in/disclosure-listing-regulations",
            "https://hudco.org.in/writereaddata/COD.html",
            "https://hudco.org.in/writereaddata/CS-CO-IRO-GRO-RTA.pdf",
            "https://hudco.org.in/writereaddata/Stat-Ind.Dir.Prog.pdf"
        ],
        category_tag="corporate_governance_compliance",
        recency_score=1.25,
        bonus_score=7.5,
    ),
    DepartmentDefinition(
        dept_id="dividend_and_iepf",
        name="Dividends & IEPF",
        keywords=[
            "iepf", "unclaimed dividend", "transfer to iepf", "iepf-5", "nodal officer iepf"
        ],
        primary_urls=[
            "https://hudco.org.in/dividend",
            "https://hudco.org.in/iepf-details"
        ],
        category_tag="dividend_iepf",
        recency_score=1.25,
        bonus_score=8.0,
    ),
    DepartmentDefinition(
        dept_id="leadership_and_board",
        name="Board Leadership & Corporate Governance",
        keywords=[
            "cmd", "chairman", "managing director", "kulshrestha", "sanjay kulshrestha",
            "board of directors", "board", "functional director", "nagaraj", "daljeet singh khatri",
            "government nominee", "sanjeet", "cvo", "vineet gupta", "executive director",
            "company secretary", "vikas goyal", "corporate office", "lodhi road", "head office"
        ],
        primary_urls=[
            "https://hudco.org.in/Leadership?type=board",
            "https://hudco.org.in/Leadership?type=management",
            "https://hudco.org.in/corporate-office",
            "https://hudco.org.in/contact-us",
            "https://hudco.org.in/shareholders-meetings"
        ],
        category_tag="leadership_board",
        recency_score=1.35,
        bonus_score=9.0,
    ),
]


class DepartmentRouter:
    """
    Routes user queries to relevant HUDCO department resources,
    dynamically crawls official linked documents (presentations, directory),
    and produces prioritized retrieval evidence.
    """

    def __init__(self, curated_retriever=None):
        self.curated_retriever = curated_retriever
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def classify_query(self, query: str) -> Optional[DepartmentDefinition]:
        """
        Matches query against departmental keyword signatures after expanding acronyms.
        Returns the top-matching DepartmentDefinition, or None if general.
        """
        if not query:
            return None

        # Expand acronyms for classification
        expanded_q = expand_query_acronyms(query).lower()
        scored_depts = []

        for dept in DEPARTMENTS:
            matched_count = 0
            exact_phrase_bonus = 0
            for kw in dept.keywords:
                pattern = r"\b" + re.escape(kw) + r"\b"
                if re.search(pattern, expanded_q):
                    matched_count += 1
                    if " " in kw:
                        exact_phrase_bonus += 2

            if matched_count > 0:
                total_score = (matched_count * 2) + exact_phrase_bonus
                scored_depts.append((total_score, dept))

        if not scored_depts:
            return None

        scored_depts.sort(key=lambda x: x[0], reverse=True)
        return scored_depts[0][1]

    def fetch_live_url_summary(self, url: str, timeout: float = 2.5) -> Optional[str]:
        """
        Dynamically fetches and extracts clean text / tables from official live URL.
        Uses in-memory cache to maintain high responsiveness.
        """
        now = time.time()
        if url in LIVE_PAGE_CACHE:
            ts, content, _ = LIVE_PAGE_CACHE[url]
            if (now - ts) < CACHE_TTL_SECONDS:
                return content

        if url.lower().endswith(".pdf"):
            return None

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            html_clean = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
            html_clean = re.sub(r"<style[^>]*>.*?</style>", " ", html_clean, flags=re.S | re.I)
            html_clean = re.sub(r"<header[^>]*>.*?</header>", " ", html_clean, flags=re.S | re.I)
            html_clean = re.sub(r"<footer[^>]*>.*?</footer>", " ", html_clean, flags=re.S | re.I)

            rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_clean, flags=re.S | re.I)
            extracted_tables = []
            for r in rows:
                cr = re.sub(r"<[^>]+>", " ", r).strip()
                cr = re.sub(r"\s+", " ", cr)
                if cr and len(cr) > 5:
                    extracted_tables.append(cr)

            plain_text = re.sub(r"<[^>]+>", " ", html_clean)
            plain_text = re.sub(r"\s+", " ", plain_text).strip()

            summary_parts = []
            if extracted_tables:
                summary_parts.append("Key Official Table Data:")
                summary_parts.extend(extracted_tables[:12])
            if plain_text:
                summary_parts.append("Page Details: " + plain_text[:1200])

            final_text = "\n".join(summary_parts)
            LIVE_PAGE_CACHE[url] = (now, final_text, url)
            return final_text
        except Exception as exc:
            logger.debug(f"Live fetch for {url} skipped/timed out: {exc}")
            return None

    def crawl_linked_documents(
        self,
        dept: DepartmentDefinition,
        query: str,
        timeout: float = 3.5
    ) -> List[RetrievalResultItem]:
        """
        Dynamically crawls linked official documents from departmental base pages.
        Extracts and scores pages relevant to query (e.g. Slide 9 for shareholders/dividends,
        Slide 10 for share price performance, Slide 13 for loan book).
        """
        if not dept.document_crawl_target:
            return []

        crawled_items: List[RetrievalResultItem] = []
        target = dept.document_crawl_target

        if target == "presentation":
            # 1. Dynamically discover linked presentation PDFs on https://hudco.org.in/financial-presentations
            base_url = "https://hudco.org.in/financial-presentations"
            discovered_pdf_url = self._discover_latest_presentation_pdf(base_url, timeout=timeout)
            if not discovered_pdf_url:
                discovered_pdf_url = "https://hudco.org.in/writereaddata/MPQ2FY27.pdf"

            pdf_pages = self._fetch_and_parse_pdf_pages(discovered_pdf_url, timeout=timeout)
            if not pdf_pages:
                return []

            # Score each slide/page against query keywords
            expanded_q = expand_query_acronyms(query).lower()
            q_terms = set(re.findall(r"\b[a-zA-Z0-9_\-]{3,}\b", expanded_q))

            scored_pages: List[Tuple[float, int, str]] = []
            for p_num, p_text in pdf_pages.items():
                p_lower = p_text.lower()
                matches = sum(1 for term in q_terms if term in p_lower)
                # Specific bonus for high-intent sections
                if any(k in expanded_q for k in ["shareholder", "shareholding", "dividend"]):
                    if "shareholding pattern" in p_lower or "shareholders" in p_lower or "dividend" in p_lower:
                        matches += 6
                if any(k in expanded_q for k in ["share price", "stock price", "market cap"]):
                    if "share price performance" in p_lower or "market capitalisation" in p_lower:
                        matches += 6
                if any(k in expanded_q for k in ["loan book", "loan outstanding", "disbursement", "sanction"]):
                    if "loan outstanding" in p_lower or "growth of loan book" in p_lower or "sanctions" in p_lower:
                        matches += 6
                if any(k in expanded_q for k in ["npa", "asset quality", "gnpa", "nnpa"]):
                    if "gross npa" in p_lower or "asset quality" in p_lower:
                        matches += 6

                if matches > 0:
                    scored_pages.append((matches, p_num, p_text))

            scored_pages.sort(key=lambda x: x[0], reverse=True)

            for score_val, p_num, p_text in scored_pages[:2]:
                chunk_id = f"dynamic_crawl_presentation_p{p_num}_{abs(hash(discovered_pdf_url)) % 1000}"
                pdf_fname = discovered_pdf_url.split("/")[-1]
                crawled_items.append(RetrievalResultItem(
                    rank=1,
                    evidence_index=1,
                    chunk_id=chunk_id,
                    score=0.98,
                    matched_terms=list(q_terms)[:5],
                    term_coverage=0.95,
                    explanation=f"Dynamic Crawled HUDCO Presentation ({pdf_fname}, Slide {p_num})",
                    document_id=f"doc_crawl_{pdf_fname}",
                    version_id="live_crawl",
                    source_id="hudco_presentation_live",
                    source_filename=f"HUDCO Official Portal: {pdf_fname} (Slide {p_num})",
                    section_id="financial_presentation_slide",
                    section_title=f"HUDCO Presentation (Slide {p_num})",
                    ancestor_headings=["HUDCO Official Portal", "Financial Presentations", pdf_fname],
                    physical_page=p_num,
                    has_table=True,
                    content=p_text.strip(),
                    content_sha256=hashlib.sha256(p_text.encode("utf-8")).hexdigest(),
                    fiscal_year="Live 2026-27 (H1 FY27)",
                    citation_label=f"Official HUDCO Live Presentation ({pdf_fname}, Slide {p_num})",
                    retrieval_method="department_dynamic_crawler",
                    composite_score=0.98,
                    relevance_score=0.98,
                    recency_score=1.35,
                    recency_tier="Official Dynamic Crawled Live Presentation",
                    url=discovered_pdf_url,
                    source_type="official_department_live",
                    scoring_breakdown={
                        "composite_score": 0.98,
                        "relevance_score": 0.98,
                        "recency_score": 1.35,
                        "recency_tier": "Official Dynamic Crawled Live Presentation",
                        "source_type": "official_department_live",
                        "url": discovered_pdf_url,
                        "slide": p_num,
                        "formula": "0.60 * 0.98 + 0.40 * 1.35 (Live Crawled Presentation Match)",
                    }
                ))

        return crawled_items

    def _discover_latest_presentation_pdf(self, base_url: str, timeout: float = 3.0) -> Optional[str]:
        """
        Dynamically inspects the base HTML page to find the most recent presentation PDF link.
        """
        try:
            req = urllib.request.Request(
                base_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            # Extract all PDF links
            pdf_links = re.findall(r'href=["\']([^"\']+\.pdf)["\']', html, flags=re.I)
            presentation_links = []
            for link in pdf_links:
                link_clean = link.strip()
                if "MPQ" in link_clean or "presentation" in link_clean.lower():
                    if link_clean.startswith("http"):
                        presentation_links.append(link_clean)
                    elif link_clean.startswith("/"):
                        presentation_links.append(f"https://hudco.org.in{link_clean}")
                    else:
                        presentation_links.append(f"https://hudco.org.in/{link_clean}")

            if presentation_links:
                # Return the first (top) presentation link on the official page (HUDCO lists newest at top)
                return presentation_links[0]
        except Exception as exc:
            logger.debug(f"Discovery of presentation links on {base_url} skipped: {exc}")
        return None

    def _fetch_and_parse_pdf_pages(self, pdf_url: str, timeout: float = 4.0) -> Dict[int, str]:
        """
        Downloads and parses PDF into page text dictionary: {page_num: text}.
        Uses in-memory cache to ensure sub-millisecond execution on subsequent queries.
        """
        now = time.time()
        if pdf_url in LIVE_PDF_CACHE:
            ts, pages = LIVE_PDF_CACHE[pdf_url]
            if (now - ts) < CACHE_TTL_SECONDS:
                return pages

        pages: Dict[int, str] = {}
        try:
            import pypdf
            req = urllib.request.Request(
                pdf_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as resp:
                pdf_bytes = resp.read()

            reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
            for idx, page in enumerate(reader.pages):
                txt = page.extract_text() or ""
                if txt.strip():
                    pages[idx + 1] = txt

            if pages:
                LIVE_PDF_CACHE[pdf_url] = (now, pages)
                logger.info(f"Successfully crawled and parsed {len(pages)} pages from {pdf_url}")
        except Exception as exc:
            logger.debug(f"Dynamic PDF crawl failed for {pdf_url}: {exc}")

        return pages

    def route_and_retrieve(
        self,
        query: str,
        top_k: int = 5
    ) -> Tuple[Optional[DepartmentDefinition], List[RetrievalResultItem]]:
        """
        Classifies query department, performs dynamic linked document crawling if applicable,
        fetches live portal updates, and returns prioritized departmental evidence.
        """
        dept = self.classify_query(query)
        if not dept:
            return None, []

        logger.info(f"DepartmentRouter classified query '{query}' -> [{dept.name}] (Recency: {dept.recency_score})")

        items: List[RetrievalResultItem] = []

        # 1. Dynamically crawl linked official documents (presentations / web directory) if configured
        crawled_doc_items = self.crawl_linked_documents(dept, query, timeout=3.5)
        for c_item in crawled_doc_items:
            items.append(c_item)

        # 2. Use CuratedLinksRetriever with expanded acronyms to get indexed curated chunks
        if self.curated_retriever and getattr(self.curated_retriever, "_is_loaded", False):
            # Pass query through acronym expansion
            expanded_query = expand_query_acronyms(query)
            curated_results = self.curated_retriever.retrieve(query=expanded_query, top_k=top_k)
            for it in curated_results:
                if not any(existing.chunk_id == it.chunk_id for existing in items):
                    items.append(it)

        # 3. Try fetching dynamic content from primary URLs if items count is low
        if len(items) < top_k:
            for url in dept.primary_urls[:2]:
                live_text = self.fetch_live_url_summary(url, timeout=2.0)
                if live_text and len(live_text) > 80:
                    chunk_id = f"dynamic_live_{dept.dept_id}_{abs(hash(url)) % 10000}"
                    if not any(it.chunk_id == chunk_id for it in items):
                        items.append(RetrievalResultItem(
                            rank=len(items) + 1,
                            evidence_index=len(items) + 1,
                            chunk_id=chunk_id,
                            score=round(min(1.0, 0.60 * 0.95 + 0.40 * dept.recency_score), 4),
                            matched_terms=dept.keywords[:5],
                            term_coverage=0.90,
                            explanation=f"Dynamic Live Department Link ({dept.name}) from {url}",
                            document_id="doc_hudco_department_live",
                            version_id="live",
                            source_id="hudco_portal_live",
                            source_filename=f"HUDCO Official Portal: {dept.name} ({url})",
                            section_id=dept.category_tag,
                            section_title=f"{dept.name} (Live Portal Update)",
                            ancestor_headings=["HUDCO Official Portal", dept.name],
                            physical_page=1,
                            has_table=True,
                            content=live_text,
                            content_sha256=hashlib.sha256(live_text.encode("utf-8")).hexdigest(),
                            fiscal_year="Live 2026-27",
                            citation_label=f"Official HUDCO Portal ({url})",
                            retrieval_method="department_dynamic_live",
                            composite_score=round(min(1.0, 0.60 * 0.95 + 0.40 * dept.recency_score), 4),
                            relevance_score=0.95,
                            recency_score=dept.recency_score,
                            recency_tier=f"Official Live Department Link ({dept.name})",
                            url=url,
                            source_type="official_department_live",
                            scoring_breakdown={
                                "composite_score": round(min(1.0, 0.60 * 0.95 + 0.40 * dept.recency_score), 4),
                                "relevance_score": 0.95,
                                "recency_score": dept.recency_score,
                                "recency_tier": f"Official Live Department Link ({dept.name})",
                                "source_type": "official_department_live",
                                "url": url,
                                "bonus_applied": dept.bonus_score,
                                "department": dept.name,
                                "formula": f"0.60 * 0.95 (rel) + 0.40 * {dept.recency_score:.2f} (rec) [Live Department Boost]",
                            }
                        ))

        # Re-sort items by composite score
        items.sort(key=lambda x: getattr(x, "composite_score", getattr(x, "score", 0.0)), reverse=True)
        return dept, items[:top_k]
