"""
Comprehensive Ingestion script for Official HUDCO Links and Department Portals.
File: pipeline/retrieval/ingest_curated_links.py

Fetches, extracts clean text/tables, structures, and persists verified official HUDCO data
across all major corporate departments (Finances & Loan Book, Bonds & Debentures, Offerings,
Careers, Tenders, Governance, Compliance, Dividend & IEPF, Leadership & Offices)
into data/curated_links/official_hudco_links.json.
"""

import os
import re
import io
import ssl
import json
import hashlib
import urllib.request
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


def extract_html(url: str, timeout: int = 15) -> str:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
        html = r.read().decode("utf-8", errors="ignore")

    # Isolate <main> content if available to strip header/nav clutter
    main_match = re.search(r"<main[^>]*>(.*?)</main>", html, re.DOTALL | re.IGNORECASE)
    if main_match:
        html = main_match.group(1)
    else:
        html = re.sub(r"<header[^>]*>.*?</header>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<nav[^>]*>.*?</nav>", "", html, flags=re.DOTALL | re.IGNORECASE)

    html = re.sub(r"<footer[^>]*>.*?</footer>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<div[^>]*class=[\"'][^\"']*cookie[^\"']*[\"'][^>]*>.*?</div>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Extract tables into readable markdown text
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S | re.I)
    extracted_tables = []
    for r in rows:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S | re.I)
        clean_cells = []
        for c in cells:
            link = re.findall(r'href=[\'"]([^\'"]+)[\'"]', c, flags=re.I)
            c_text = re.sub(r"<[^>]+>", " ", c).strip()
            c_text = re.sub(r"\s+", " ", c_text)
            if link and not link[0].startswith("#"):
                clean_cells.append(f"{c_text} ({link[0]})")
            else:
                clean_cells.append(c_text)
        if clean_cells:
            extracted_tables.append(" | ".join(clean_cells))

    p = CleanHTMLParser()
    p.feed(html)
    raw = "".join(p.parts)
    raw = re.sub(r"[ \t]+", " ", raw)
    raw = re.sub(r"(?:Cookie Policy|Accept All|Optional Cookies|Accessibility Tools|Font Size Increase|Grayscale).*?(?=\n\n|$)", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\n\s*\n+", "\n\n", raw).strip()

    if extracted_tables:
        raw += "\n\n### Official Data Tables:\n" + "\n".join(extracted_tables[:25])

    return raw


def extract_pdf(url: str, max_pages: int = 15, timeout: int = 25):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as r:
        reader = pypdf.PdfReader(io.BytesIO(r.read()))
        pages = []
        for i in range(min(max_pages, len(reader.pages))):
            txt = reader.pages[i].extract_text() or ""
            txt = re.sub(r"[ \t]+", " ", txt).strip()
            if txt:
                pages.append((i + 1, txt))
        return pages


def run_ingestion():
    targets = [
        # --- LEADERSHIP & OFFICES ---
        {
            "id": "link_board",
            "url": "https://hudco.org.in/Leadership?type=board",
            "title": "HUDCO Board of Directors & Key Leadership (Chairman & MD Sanjay Kulshrestha, Functional Directors, Govt Nominees)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.30,
            "category": "leadership_board"
        },
        {
            "id": "link_management",
            "url": "https://hudco.org.in/Leadership?type=management",
            "title": "HUDCO Management Team (Chief Vigilance Officer Vineet Gupta, Senior EDs, EDs & Company Secretary Vikas Goyal)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.30,
            "category": "leadership_management"
        },
        {
            "id": "link_corporate_office",
            "url": "https://hudco.org.in/corporate-office",
            "title": "HUDCO Corporate & Registered Office (Address: HUDCO Bhawan, India Habitat Centre, Lodhi Road, New Delhi 110003, Phone, Fax, Email)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "corporate_office"
        },
        {
            "id": "link_contact_us",
            "url": "https://hudco.org.in/contact-us",
            "title": "HUDCO Contact Directory & Regional Offices (Regional Offices Across India, Phone, Address)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "contact_directory"
        },
        {
            "id": "link_shareholders",
            "url": "https://hudco.org.in/shareholders-meetings",
            "title": "HUDCO Shareholders & General Meetings (AGM, EGM, Scrutinizer Reports, Voting Results)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.20,
            "category": "shareholder_meetings"
        },
        # --- FINANCES, LOAN BOOK & RESULTS ---
        {
            "id": "link_fin_presentations",
            "url": "https://hudco.org.in/financial-presentations",
            "title": "HUDCO Financial & Investor Presentations (Quarterly Investor Presentations: FY 2026-27 Q1, Q2 & H1; FY 2025-26 Q1-Q4)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.35,
            "category": "finances_presentations"
        },
        {
            "id": "link_fin_results",
            "url": "https://hudco.org.in/financial-results",
            "title": "HUDCO Financial Results (Quarterly Financial Statements: 30-09-2026 Q2 & H1, 30-06-2026 Q1, 31-03-2026 FY26 Full Year)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.35,
            "category": "finances_results"
        },
        {
            "id": "link_annual_returns",
            "url": "https://hudco.org.in/annual-returns",
            "title": "HUDCO Annual Returns (Form MGT-7 Statutory Filing)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.20,
            "category": "annual_returns"
        },
        # --- BONDS, CAPITAL GAINS & INVESTOR INTEREST ---
        {
            "id": "link_54ec_bonds",
            "url": "https://hudco.org.in/54ec-capital-gain-bonds",
            "title": "HUDCO 54EC Capital Gain Tax Exemption Bonds (Series II, 5.25% Annual Coupon, AAA Rated, Apply Online & Offline)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.30,
            "category": "bonds_54ec"
        },
        {
            "id": "link_current_bonds_pdf",
            "url": "https://hudco.org.in/writereaddata/current-bonds.pdf",
            "title": "HUDCO Details of Current Bonds as on 01/04/2026 (Tax-Free & Taxable Bonds, ISIN, Coupon Rates, Allotment & Redemption Dates)",
            "type": "pdf",
            "tier": "Tier 1B - Official Current Bonds PDF",
            "recency_score": 1.30,
            "category": "bonds_current"
        },
        {
            "id": "link_contact_rta_pdf",
            "url": "https://hudco.org.in/writereaddata/contact-details-RTA.pdf",
            "title": "HUDCO Registrar & Transfer Agent (RTA) Contact Details (KFin Technologies Limited, Hyderabad & New Delhi, Email, Phone)",
            "type": "pdf",
            "tier": "Tier 1B - Official RTA PDF",
            "recency_score": 1.25,
            "category": "bonds_rta"
        },
        {
            "id": "link_debenture_trustee_pdf",
            "url": "https://hudco.org.in/writereaddata/Debenture_Trustee.pdf",
            "title": "HUDCO Debenture Trustees for Bonds (SBICAP Trustee Company, Beacon Trusteeship Limited, Contact Information)",
            "type": "pdf",
            "tier": "Tier 1B - Official Debenture Trustee PDF",
            "recency_score": 1.25,
            "category": "bonds_trustee"
        },
        {
            "id": "link_forms_procedures",
            "url": "https://hudco.org.in/forms-and-procedures",
            "title": "HUDCO Bondholder Forms and Procedures (Change of Address, Transmission, Mandate Form, ECS/NEFT)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "bonds_forms"
        },
        {
            "id": "link_general_info",
            "url": "https://hudco.org.in/general-information",
            "title": "HUDCO General Information for Bondholders (Interest Payment, TDS, Form 15G/15H, Demat Credit)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "bonds_general"
        },
        {
            "id": "link_stock_exchanges",
            "url": "https://hudco.org.in/information-to-stock-exchanges",
            "title": "HUDCO Information to Stock Exchanges (BSE & NSE Intimations on Record Dates, Interest Payments, Redemptions)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "stock_exchange_info"
        },
        {
            "id": "link_unclaimed_bonds",
            "url": "https://hudco.org.in/unclaimed-bonds",
            "title": "HUDCO Unclaimed Principal and Interest on Bonds (Search & Claim Procedure)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "unclaimed_bonds"
        },
        {
            "id": "link_others",
            "url": "https://hudco.org.in/others",
            "title": "HUDCO Other Investor Notices and Policies",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.20,
            "category": "investor_others"
        },
        # --- OFFERINGS, CAREERS, TENDERS & GRIEVANCE ---
        {
            "id": "link_services",
            "url": "https://hudco.org.in/services",
            "title": "HUDCO Schemes & Services (Social Housing Finance, EWS/LIG Housing, Urban Infrastructure Financing, Consultancy & Project Appraisal)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "offerings_services"
        },
        {
            "id": "link_careers",
            "url": "https://hudco.org.in/careers",
            "title": "HUDCO Careers & Recruitment (Regular Lateral Recruitment, Chief Information Security Officer CISO, Asset Development Specialist ADS, Application Notifications)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.30,
            "category": "careers_recruitment"
        },
        {
            "id": "link_tenders",
            "url": "https://hudco.org.in/TenderHome",
            "title": "HUDCO E-Tenders & Procurement Portal (Active Tenders, Notices, Bidding Instructions, CPPP & GeM Integration)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.30,
            "category": "tenders_procurement"
        },
        {
            "id": "link_grievance",
            "url": "https://hudco.org.in/grievance-redressal",
            "title": "HUDCO Grievance Redressal Mechanism (CPGRAMS, Internal Grievance Machinery, Designated Grievance Redressal Officer)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.30,
            "category": "grievance_redressal"
        },
        # --- LISTING COMPLIANCE & STATUTORY DISCLOSURES ---
        {
            "id": "link_cgr",
            "url": "https://hudco.org.in/corporate-governance-report",
            "title": "HUDCO Quarterly Corporate Governance Reports (SEBI LODR Regulation 27(2) Compliance)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "corporate_governance_report"
        },
        {
            "id": "link_cod",
            "url": "https://hudco.org.in/writereaddata/COD.html",
            "title": "HUDCO Code of Conduct for Board Members and Senior Management",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.20,
            "category": "code_of_conduct"
        },
        {
            "id": "link_cs_iro_pdf",
            "url": "https://hudco.org.in/writereaddata/CS-CO-IRO-GRO-RTA.pdf",
            "title": "HUDCO Details of Company Secretary & Compliance Officer (Shri Vikas Goyal), Investor Relations Officer, Grievance Officer & RTA",
            "type": "pdf",
            "tier": "Tier 1B - Official Compliance Officers PDF",
            "recency_score": 1.30,
            "category": "compliance_officers"
        },
        {
            "id": "link_disclosure_listing",
            "url": "https://hudco.org.in/disclosure-listing-regulations",
            "title": "HUDCO Disclosures under Listing Regulations (SEBI LODR Regulation 30 & 51 Material Event Disclosures)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "listing_disclosures"
        },
        {
            "id": "link_shareholding",
            "url": "https://hudco.org.in/shareholding-pattern",
            "title": "HUDCO Shareholding Pattern (Promoter Government of India Holding ~75%, Public, Financial Institutions, FPI Holdings)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.30,
            "category": "shareholding_pattern"
        },
        {
            "id": "link_liquidity",
            "url": "https://hudco.org.in/liquidity-disclosure",
            "title": "HUDCO Liquidity Disclosures (Liquidity Coverage Ratio LCR and Asset-Liability Disclosures under RBI Regulations)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "liquidity_disclosure"
        },
        {
            "id": "link_sebi_disclosures",
            "url": "http://hudco.org.in/sebi-disclosures",
            "title": "HUDCO Disclosures under Regulations 46 and 62 of SEBI LODR Regulations",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "sebi_disclosures"
        },
        {
            "id": "link_dividend",
            "url": "https://hudco.org.in/dividend",
            "title": "HUDCO Dividend Announcements and History (Interim and Final Dividend Records, Dividend Distribution Policy)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "dividend"
        },
        {
            "id": "link_stat_ind_dir_pdf",
            "url": "https://hudco.org.in/writereaddata/Stat-Ind.Dir.Prog.pdf",
            "title": "HUDCO Familiarisation Programmes for Independent Directors (Statutory Statement)",
            "type": "pdf",
            "tier": "Tier 1B - Official Independent Director Statement PDF",
            "recency_score": 1.20,
            "category": "stat_ind_dir"
        },
        {
            "id": "link_iepf",
            "url": "https://hudco.org.in/iepf-details",
            "title": "HUDCO IEPF Details (Investor Education and Protection Fund: Transfer of Unpaid Dividend & Shares, Nodal Officer IEPF Shri Vikas Goyal)",
            "type": "html",
            "tier": "Tier 1A - Official Live Portal",
            "recency_score": 1.25,
            "category": "iepf_details"
        },
        # --- CORE REFERENCE DOCUMENTS ---
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

    # Ingest key latest financial presentation data explicitly for loan book and asset quality
    fin_presentation_summary = """
HUDCO Latest Financial Performance & Loan Book (Investor Presentation Q2 & H1 FY 2026-27 - As of September 30, 2026):
1. Loan Outstanding / Total Loan Book:
   - As of September 30, 2026 (H1 FY27): ₹1,86,111 crore (Growth of 29% YoY vs ₹1,44,554 crore in H1 FY26).
   - As of March 31, 2026 (FY26 Full Year / 56th Annual Report): ₹1,60,724 crore.
   - As of March 31, 2025 (FY25): ₹1,24,828 crore.
   - As of March 31, 2024 (FY24): ₹92,654 crore.
   - Quality: 99.25% of total loan book is to Government and its agencies.

2. Loan Sanctions:
   - H1 FY 2026-27 (April - Sept 2026): ₹1,04,592 crore (Growth of 12% vs ₹92,985 crore in H1 FY26).
   - FY 2025-26 Full Year: ₹1,64,758 crore.
   - FY 2024-25 Full Year: ₹1,27,952 crore.

3. Loan Disbursements:
   - H1 FY 2026-27 (April - Sept 2026): ₹35,372 crore (Growth of 37% vs ₹25,838 crore in H1 FY26).
   - FY 2025-26 Full Year: ₹51,194 crore.
   - FY 2024-25 Full Year: ₹40,038 crore.

4. Asset Quality (Pristine NPA Profile):
   - Gross NPA: 0.71% as of September 30, 2026 (H1 FY27) vs 1.04% in FY26, 1.67% in FY25, 2.71% in FY24.
   - Net NPA: 0.044% as of September 30, 2026 (H1 FY27) vs 0.053% in FY26, 0.245% in FY25, 0.356% in FY24.
   - Provision Coverage Ratio (PCR): 93.76% as of September 30, 2026 (H1 FY27).

5. Earnings & Interest Income:
   - Interest Income: ₹7,733 crore in H1 FY27 (vs ₹6,122 crore in H1 FY26, 26% growth). Full FY26: ₹13,096 crore.
   - Source: Official HUDCO Investor Presentation (MPQ2FY27.pdf) & Financial Statements (hudco.org.in/financial-presentations).
"""
    chunks.append({
        "chunk_id": "link_fin_latest_h1fy27_presentation",
        "title": "HUDCO Latest Loan Book, Sanctions, Disbursements & Asset Quality (Q2 & H1 FY 2026-27 / As of September 30, 2026)",
        "url": "https://hudco.org.in/financial-presentations",
        "priority_tier": "Tier 1A - Official Live Financial Presentation",
        "recency_score": 1.35,
        "recency_tier": "Latest Financial Update (H1 FY 2026-27 / Sept 30, 2026)",
        "category": "finances_presentations",
        "source_type": "official_link",
        "fiscal_year": "2027",
        "content": fin_presentation_summary.strip(),
        "content_sha256": hashlib.sha256(fin_presentation_summary.encode("utf-8")).hexdigest()
    })

    for t in targets:
        print(f"Fetching {t['id']} from {t['url']}...")
        try:
            if t["type"] == "html":
                content = extract_html(t["url"])

                # Add a unified complete chunk for leadership and management
                if t["id"] == "link_board":
                    chunks.append({
                        "chunk_id": "link_board_complete",
                        "title": "HUDCO Board of Directors (Chairman & MD Sanjay Kulshrestha, Functional Directors M Nagaraj & Daljeet Singh Khatri, Govt Nominee Sanjeet IRAS)",
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
                        "title": "HUDCO Management Team (Chief Vigilance Officer Vineet Gupta, Senior EDs, EDs, Company Secretary Vikas Goyal)",
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
