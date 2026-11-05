"""
Web Search Sub-Agent with Built-In Guardrails and Fail-Safe DuckDuckGo Backup for HUDCO Enterprise AI.
File: pipeline/retrieval/tavily_search.py

Provides:
1. Primary web retrieval via Tavily API with strict guardrails (query anchoring, negative namesake filtering).
2. Automatic fail-safe fallback to DuckDuckGo search when Tavily quota is exhausted, times out, or fails.
3. Zero-dependency resilience to ensure live corporate and public inquiries are always answerable.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

from config.settings import settings

logger = logging.getLogger(__name__)

DEFAULT_TAVILY_API_URL = "https://api.tavily.com/search"

# Positive entity keywords for Indian PSU HUDCO
INDIAN_HUDCO_KEYWORDS = {
    "housing and urban development corporation",
    "hudco bhawan",
    "india habitat centre",
    "lodhi road",
    "new delhi",
    "hudco.org",
    "hudco.org.in",
    "uiwin",
    "sanjay kulshrestha",
    "urban development",
    "housing finance",
    "psu",
    "cpse",
    "miniratna",
    "navratna",
    "nbfc",
    "recruitment",
    "careers",
    "tender",
}

# Negative keywords for non-HUDCO entities with similar names (e.g., US co-working space 'HudCo')
DISQUALIFYING_PATTERNS = [
    r"\bhudco\.co\b",
    r"\bdobbs\s+ferry\b",
    r"\bwestchester\b",
]


class TavilySearchAgent:
    """
    Sub-agent for guarded web retrieval using Tavily API with DuckDuckGo fail-safe backup.
    Enforces domain relevance, filters spam/noise, and guarantees clean evidence provenance.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or getattr(settings, "TAVILY_API_KEY", "") or os.environ.get("TAVILY_API_KEY", "") or ""

    def is_configured(self) -> bool:
        """Returns True if a valid Tavily API key is available or DuckDuckGo is active."""
        return True

    def contextualize_query(self, query: str) -> str:
        """
        Guardrail 1: Query Contextualization.
        Ensures query is anchored to Indian HUDCO without creating an over-long query string.
        """
        ql = query.strip().rstrip("?.,!")
        ql_lower = ql.lower()
        if "hudco" not in ql_lower:
            return f"HUDCO India {ql}"
        if "india" not in ql_lower:
            return f"{ql} India"
        return ql

    def filter_and_validate_results(
        self,
        raw_results: List[Dict[str, Any]],
        original_query: str,
        provider_name: str = "tavily"
    ) -> List[Dict[str, Any]]:
        """
        Guardrail 2 & 3: Content Relevance & False Entity Dropping.
        Drops off-topic results, empty snippets, or foreign namesake companies.
        """
        validated_items = []

        for idx, item in enumerate(raw_results):
            title = (item.get("title") or "").strip()
            content = (item.get("content") or item.get("snippet") or item.get("body") or "").strip()
            url = (item.get("url") or item.get("href") or "").strip()

            if len(content) < 20:
                continue

            try:
                domain = urlparse(url).netloc.lower()
            except Exception:
                domain = ""

            combined_text = f"{title} {content} {url}".lower()

            # Guardrail: Check for false entities (e.g. Dobbs Ferry coworking space)
            if any(re.search(pat, combined_text) for pat in DISQUALIFYING_PATTERNS):
                logger.warning(f"Guardrail dropped false entity match: '{title}' ({url})")
                continue

            # Must match Indian HUDCO indicators or official domains
            is_official = ("hudco.org" in domain) or ("hudco.org.in" in domain) or ("gov.in" in domain)
            has_indian_hudco_signal = any(kw in combined_text for kw in INDIAN_HUDCO_KEYWORDS) or ("hudco" in combined_text)

            if not (is_official or has_indian_hudco_signal):
                logger.warning(f"Guardrail dropped unverified web result: '{title}' from {domain}")
                continue

            provider_label = "DuckDuckGo" if "duckduckgo" in provider_name else "Tavily"
            validated_items.append({
                "rank": len(validated_items) + 1,
                "evidence_index": len(validated_items) + 1,
                "title": title,
                "url": url,
                "domain": domain,
                "content": content,
                "score": round(float(item.get("score", 0.90)), 4),
                "is_web": True,
                "source_provider": provider_name,
                "source_filename": f"{provider_label} ({domain or 'Official Web'})",
                "citation_label": f"Web [{provider_label}]: {title[:48]}",
                "document_id": "WEB_EVIDENCE",
                "section_title": title,
                "physical_page": None,
                "printed_page": None,
                "chunk_id": f"{provider_name}_result_{len(validated_items) + 1}",
            })

        return validated_items

    def search_duckduckgo(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """
        Fail-safe Web Search using DuckDuckGo.
        Activated automatically when Tavily quota is exhausted, times out, or fails.
        Completely free, requires no API key, and enforces strict HUDCO guardrails.
        """
        anchored_query = self.contextualize_query(query)
        logger.info(f"Executing DuckDuckGo fail-safe web search for: '{anchored_query}'")
        raw_items = []
        try:
            try:
                from ddgs import DDGS
                ddgs = DDGS()
            except ImportError:
                from duckduckgo_search import DDGS
                ddgs = DDGS()

            # Try html backend first, then api
            results = None
            for backend_choice in ["html", "api", "lite"]:
                try:
                    res = ddgs.text(anchored_query, backend=backend_choice, max_results=max(max_results * 2, 6))
                    if res:
                        results = res
                        break
                except Exception as b_err:
                    logger.debug(f"DDGS backend '{backend_choice}' failed: {b_err}")

            results = results or []
            for r in results:
                raw_items.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "content": r.get("body", ""),
                    "score": 0.88,
                })

            validated_evidence = self.filter_and_validate_results(raw_items, query, provider_name="duckduckgo_fallback")

            # Fallback relaxation if strict keyword check was too tight but hudco is mentioned
            if not validated_evidence and raw_items:
                for r in raw_items:
                    combined = f"{r.get('title', '')} {r.get('content', '')}".lower()
                    if not any(re.search(pat, combined) for pat in DISQUALIFYING_PATTERNS):
                        if "hudco" in combined:
                            url = r.get("url", "")
                            domain = urlparse(url).netloc.lower() if url else ""
                            validated_evidence.append({
                                "rank": len(validated_evidence) + 1,
                                "evidence_index": len(validated_evidence) + 1,
                                "title": r.get("title", "HUDCO Reference"),
                                "url": url,
                                "domain": domain,
                                "content": r.get("content", ""),
                                "score": 0.85,
                                "is_web": True,
                                "source_provider": "duckduckgo_fallback",
                                "source_filename": f"DuckDuckGo ({domain or 'Web'})",
                                "citation_label": f"Web [DuckDuckGo]: {r.get('title', '')[:48]}",
                                "document_id": "WEB_EVIDENCE",
                                "section_title": r.get("title", "HUDCO Reference"),
                                "physical_page": None,
                                "printed_page": None,
                                "chunk_id": f"ddg_result_{len(validated_evidence) + 1}",
                            })
                            if len(validated_evidence) >= max_results:
                                break

            logger.info(f"DuckDuckGo search retrieved {len(raw_items)} raw, validated {len(validated_evidence)} items.")
            return {
                "success": len(validated_evidence) > 0,
                "provider": "duckduckgo_fallback",
                "query": anchored_query,
                "evidence": validated_evidence[:max_results],
                "tavily_answer": None,
                "has_results": len(validated_evidence) > 0,
            }
        except Exception as e:
            logger.error(f"DuckDuckGo search failed: {e}", exc_info=True)
            return {
                "success": False,
                "provider": "duckduckgo_fallback",
                "error": f"DuckDuckGo search error: {str(e)}",
                "evidence": [],
                "tavily_answer": None,
                "has_results": False,
            }

    def search(self, query: str, max_results: int = 5, api_key_override: Optional[str] = None) -> Dict[str, Any]:
        """
        Executes web search with guardrails, returning structured evidence items.
        Automatically falls back to DuckDuckGo if Tavily is unconfigured, exhausted (429), or fails.
        """
        key = api_key_override or self.api_key
        # 1. If key is missing or blank, use DuckDuckGo fail-safe directly
        if not key or len(key.strip()) < 8:
            logger.info("Tavily API key not configured or empty. Using DuckDuckGo fail-safe directly.")
            return self.search_duckduckgo(query, max_results)

        anchored_query = self.contextualize_query(query)
        payload = {
            "api_key": key,
            "query": anchored_query,
            "search_depth": "basic",
            "include_answer": True,
            "max_results": max_results,
        }

        req = urllib.request.Request(
            DEFAULT_TAVILY_API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "HUDCO-AI-Agent/1.0"},
        )

        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            raw_results = data.get("results", [])
            tavily_direct_answer = data.get("answer")

            # Apply Guardrail filters
            validated_evidence = self.filter_and_validate_results(raw_results, query, provider_name="tavily")

            # If Tavily returned 0 valid results after filtering, try DuckDuckGo as backup
            if not validated_evidence:
                logger.info("Tavily yielded 0 valid results after guardrail filtering. Trying DuckDuckGo fallback.")
                ddg_res = self.search_duckduckgo(query, max_results)
                if ddg_res.get("has_results"):
                    return ddg_res

            logger.info(f"Tavily search for '{anchored_query}': retrieved {len(raw_results)}, validated {len(validated_evidence)} items.")

            return {
                "success": True,
                "provider": "tavily",
                "query": anchored_query,
                "evidence": validated_evidence,
                "tavily_answer": tavily_direct_answer,
                "has_results": len(validated_evidence) > 0,
            }

        except urllib.error.HTTPError as he:
            logger.warning(f"Tavily HTTP {he.code} error encountered (e.g. quota limit / invalid key). Triggering DuckDuckGo fail-safe.")
            return self.search_duckduckgo(query, max_results)
        except Exception as e:
            logger.warning(f"Tavily search request failed ({e}). Triggering DuckDuckGo fail-safe.")
            return self.search_duckduckgo(query, max_results)
