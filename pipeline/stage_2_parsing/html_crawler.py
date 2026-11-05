"""
HTML Crawler and Article Scraper for HUDCO Web Pages and FAQs.
Uses Trafilatura and BeautifulSoup4 for clean, boilerplate-free web content.
"""

import logging
from typing import Dict, Any, Optional
import requests
from bs4 import BeautifulSoup
import trafilatura

logger = logging.getLogger(__name__)

class HTMLCrawler:
    """Scrapes official HUDCO web pages and FAQs into clean markdown."""

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "HUDCO-Enterprise-AI-Pipeline/1.0"
        })

    def crawl_page(self, url: str) -> Dict[str, Any]:
        """
        Fetch webpage, extract core article content and metadata.
        """
        logger.info(f"Crawling HUDCO page: {url}")
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()

        html_content = resp.text

        # 1. Trafilatura main content extraction
        extracted_text = trafilatura.extract(
            html_content,
            include_links=True,
            include_tables=True,
            output_format="txt"
        )

        # 2. BeautifulSoup metadata parsing
        soup = BeautifulSoup(html_content, "html.parser")
        title = soup.title.string.strip() if soup.title else "HUDCO Official Page"

        # Extract FAQs if available in accordion structures
        faqs = []
        for q_elem in soup.select(".accordion-header, .faq-question, dt"):
            ans_elem = q_elem.find_next_sibling()
            if ans_elem:
                faqs.append({
                    "question": q_elem.get_text(strip=True),
                    "answer": ans_elem.get_text(strip=True)
                })

        return {
            "url": url,
            "title": title,
            "content": extracted_text or "",
            "faqs": faqs,
            "has_faqs": len(faqs) > 0
        }
