"""
Department-Aware Semantic Router and Dynamic Live URL Fetcher for HUDCO AI.
File: pipeline/retrieval/department_router.py

1. Identifies which HUDCO functional department/domain the user query pertains to
   (Finances & Loan Book, Bonds & Investor Interest, Careers & Recruitment,
    Tenders & Procurement, Grievances, Listing Compliance, Dividends & IEPF, Leadership).
2. Dynamically associates the verified official live HUDCO links for that department.
3. Attempts dynamic live fetch of the latest page content/tables with an in-memory TTL cache,
   falling back seamlessly to verified indexed snapshots if offline.
4. Produces top-tier RetrievalResultItems (Recency Score: 1.25 - 1.35) ranked strictly above
   standard Annual Report RAG chunks.
"""

import os
import re
import ssl
import time
import json
import hashlib
import logging
import urllib.request
from typing import Dict, Any, List, Optional, Tuple

from pipeline.retrieval.contracts import RetrievalResultItem

logger = logging.getLogger("QwenWorker")

# In-memory TTL cache for live fetched department content: {url: (timestamp, content, title)}
LIVE_PAGE_CACHE: Dict[str, Tuple[float, str, str]] = {}
CACHE_TTL_SECONDS: float = 3600.0  # 1 hour cache to avoid unnecessary network load


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
    ):
        self.dept_id = dept_id
        self.name = name
        self.keywords = [k.lower() for k in keywords]
        self.primary_urls = primary_urls
        self.category_tag = category_tag
        self.recency_score = recency_score
        self.bonus_score = bonus_score


DEPARTMENTS: List[DepartmentDefinition] = [
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
        name="Careers, Recruitment & HR",
        keywords=[
            "career", "careers", "job", "jobs", "recruitment", "vacancy", "vacancies",
            "lateral level", "lateral recruitment", "ciso", "asset development specialist",
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
            "shareholding pattern", "promoter", "liquidity disclosure", "lcr", "reg 46",
            "reg 62", "lodr", "disclosure", "compliance officer", "statutory disclosure",
            "independent director", "familiarisation"
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
            "dividend", "interim dividend", "final dividend", "dividend payout", "record date",
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
    Routes user queries to the relevant HUDCO department resources,
    fetches dynamic live updates, and produces prioritized retrieval evidence.
    """

    def __init__(self, curated_retriever=None):
        self.curated_retriever = curated_retriever
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE

    def classify_query(self, query: str) -> Optional[DepartmentDefinition]:
        """
        Matches query against departmental keyword signatures.
        Returns the top-matching DepartmentDefinition, or None if general.
        """
        if not query:
            return None

        q = query.lower()
        scored_depts = []

        for dept in DEPARTMENTS:
            matched_count = sum(1 for kw in dept.keywords if kw in q)
            if matched_count > 0:
                # Extra weight for exact match of multi-word key phrases
                exact_phrase_bonus = sum(2 for kw in dept.keywords if " " in kw and kw in q)
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

        # Check if URL is HTML or PDF
        if url.lower().endswith(".pdf"):
            return None  # PDFs are pre-indexed; avoid heavy on-the-fly downloads

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="ignore")

            # Extract main content / table text
            html_clean = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S | re.I)
            html_clean = re.sub(r"<style[^>]*>.*?</style>", " ", html_clean, flags=re.S | re.I)
            html_clean = re.sub(r"<header[^>]*>.*?</header>", " ", html_clean, flags=re.S | re.I)
            html_clean = re.sub(r"<footer[^>]*>.*?</footer>", " ", html_clean, flags=re.S | re.I)

            # Extract table rows if any
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

    def route_and_retrieve(
        self,
        query: str,
        top_k: int = 5
    ) -> Tuple[Optional[DepartmentDefinition], List[RetrievalResultItem]]:
        """
        Classifies query department, fetches live portal updates if possible,
        and returns prioritized departmental evidence.
        """
        dept = self.classify_query(query)
        if not dept:
            return None, []

        logger.info(f"DepartmentRouter classified query '{query}' -> [{dept.name}] (Recency: {dept.recency_score})")

        items: List[RetrievalResultItem] = []

        # 1. Use CuratedLinksRetriever with department bonus to get indexed chunks
        if self.curated_retriever and self.curated_retriever._is_loaded:
            curated_results = self.curated_retriever.retrieve(query=query, top_k=top_k)
            for it in curated_results:
                items.append(it)

        # 2. Try fetching dynamic content from primary URLs if items count is low or needs freshness
        for url in dept.primary_urls[:2]:
            live_text = self.fetch_live_url_summary(url, timeout=2.0)
            if live_text and len(live_text) > 80:
                # Add dynamic live item
                chunk_id = f"dynamic_live_{dept.dept_id}_{abs(hash(url)) % 10000}"
                # Check if already present
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
