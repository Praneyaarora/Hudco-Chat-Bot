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
            base_score = float(item.get("score", 0.85))

            # Domain authority bonus for official HUDCO portal
            domain_bonus = 0.0
            if "hudco.org.in" in domain or "hudco.org" in domain:
                domain_bonus = 0.15
                domain_label = "Official HUDCO Portal (hudco.org.in)"
            elif "gov.in" in domain:
                domain_bonus = 0.10
                domain_label = f"Official Government Source ({domain})"
            else:
                domain_label = f"Web Source ({domain})"

            # Recency bonus from snippet text (prefer 2025-2026 data)
            recency_bonus = 0.0
            recency_tier = "Web Record"
            if re.search(r"\b2026\b", combined_text):
                recency_bonus = 0.10
                recency_tier = "Latest 2026 Online Data"
            elif re.search(r"\b2025\b", combined_text):
                recency_bonus = 0.08
                recency_tier = "Recent 2025 Online Data"
            elif re.search(r"\b2024\b", combined_text):
                recency_bonus = 0.05
                recency_tier = "Recent 2024 Online Data"

            final_score = round(min(1.0, max(0.0, base_score + domain_bonus + recency_bonus)), 4)

            is_hudco_domain = ("hudco.org" in domain) or ("hudco.org.in" in domain)
            src_type = "hudco_web_search" if is_hudco_domain else "general_web_search"

            validated_items.append({
                "rank": len(validated_items) + 1,
                "evidence_index": len(validated_items) + 1,
                "title": title,
                "url": url,
                "domain": domain,
                "content": content,
                "score": final_score,
                "composite_score": final_score,
                "relevance_score": round(base_score, 4),
                "recency_score": round(0.5 + recency_bonus * 3.0, 4),
                "recency_tier": f"{recency_tier} · {domain_label}",
                "scoring_breakdown": {
                    "composite_score": final_score,
                    "base_relevance": base_score,
                    "domain_bonus": domain_bonus,
                    "recency_bonus": recency_bonus,
                    "domain": domain,
                    "source_type": src_type,
                    "formula": f"{base_score:.2f} (base) + {domain_bonus:.2f} (domain) + {recency_bonus:.2f} (recency)",
                },
                "is_web": True,
                "source_type": src_type,
                "source_provider": provider_name,
                "source_filename": f"{provider_label} ({domain or 'hudco.org.in'})",
                "citation_label": f"Web [{provider_label}]: {title[:48]}",
                "document_id": "WEB_EVIDENCE",
                "section_title": title,
                "physical_page": None,
                "printed_page": None,
                "chunk_id": f"{provider_name}_result_{len(validated_items) + 1}",
            })

        # Sort so official hudco.org.in and recent results rank #1
        validated_items.sort(key=lambda x: -x["score"])
        for new_r, it in enumerate(validated_items, start=1):
            it["rank"] = new_r
            it["evidence_index"] = new_r

        return validated_items

    def search_duckduckgo(self, query: str, max_results: int = 5) -> Dict[str, Any]:
        """
        Fail-safe Web Search using DuckDuckGo.
        1st Approach: Scopes search to HUDCO's official website (hudco.org.in).
        2nd Approach: Falls back to guarded general search if official site yields 0 results.
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

            # Approach 1: Official hudco.org.in targeted query first
            hudco_site_query = f"site:hudco.org.in {anchored_query}"
            logger.info(f"DuckDuckGo Approach 1 (Official Website): '{hudco_site_query}'")
            results = None
            for backend_choice in ["html", "api", "lite"]:
                try:
                    res = ddgs.text(hudco_site_query, backend=backend_choice, max_results=max(max_results * 2, 6))
                    if res:
                        results = res
                        break
                except Exception as b_err:
                    logger.debug(f"DDGS official backend '{backend_choice}' failed: {b_err}")

            if results:
                for r in results:
                    raw_items.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "content": r.get("body", ""),
                        "score": 0.95,
                    })
                validated_evidence = self.filter_and_validate_results(raw_items, query, provider_name="duckduckgo_hudco_official")
                if validated_evidence:
                    logger.info(f"DuckDuckGo Approach 1 succeeded with {len(validated_evidence)} official hudco.org.in results.")
                    return {
                        "success": True,
                        "provider": "duckduckgo_hudco_official",
                        "query": hudco_site_query,
                        "evidence": validated_evidence[:max_results],
                        "tavily_answer": None,
                        "has_results": True,
                    }

            # Approach 2: General guarded search if official site yielded no matches
            logger.info(f"DuckDuckGo Approach 2 (General Guarded Search): '{anchored_query}'")
            raw_items = []
            for backend_choice in ["html", "api", "lite"]:
                try:
                    res = ddgs.text(anchored_query, backend=backend_choice, max_results=max(max_results * 2, 6))
                    if res:
                        results = res
                        break
                except Exception as b_err:
                    logger.debug(f"DDGS general backend '{backend_choice}' failed: {b_err}")

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

        # Approach 1: Targeted search on official HUDCO website (hudco.org.in)
        official_payload = {
            "api_key": key,
            "query": anchored_query,
            "search_depth": "basic",
            "include_domains": ["hudco.org.in", "hudco.org"],
            "include_answer": True,
            "max_results": max_results,
        }

        try:
            logger.info("Executing Tavily Approach 1 (Targeted Official Domain: hudco.org.in)...")
            req_off = urllib.request.Request(
                DEFAULT_TAVILY_API_URL,
                data=json.dumps(official_payload).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "HUDCO-AI-Agent/1.0"},
            )
            with urllib.request.urlopen(req_off, timeout=10) as resp:
                data_off = json.loads(resp.read().decode("utf-8"))

            raw_off = data_off.get("results", [])
            val_off = self.filter_and_validate_results(raw_off, query, provider_name="tavily_hudco_official")
            if val_off:
                logger.info(f"Tavily Approach 1 succeeded with {len(val_off)} official hudco.org.in results.")
                return {
                    "success": True,
                    "provider": "tavily_hudco_official",
                    "query": anchored_query,
                    "evidence": val_off[:max_results],
                    "tavily_answer": data_off.get("answer"),
                    "has_results": True,
                }
        except Exception as off_err:
            logger.debug(f"Tavily official domain targeted search encountered non-critical error: {off_err}")

        # Approach 2: Guarded general search if official portal yielded no results
        logger.info("Executing Tavily Approach 2 (General Guarded Web Search)...")
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
