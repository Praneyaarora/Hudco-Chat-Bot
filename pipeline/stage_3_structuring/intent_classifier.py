"""
Intent Classifier and Knowledge Structurer.
Uses LLMs (Gemini / Groq) or heuristic rules to produce validated UnifiedChunk objects.
"""

import hashlib
import logging
from typing import Dict, Any, List
from datetime import datetime

from config.settings import settings
from .schemas import (
    UnifiedChunk,
    SourceMetadata,
    ClassificationMetadata,
    ContentPayload,
    ChunkMetadata,
    TableItem
)

logger = logging.getLogger(__name__)

# Standard Intent Taxonomies
TAXONOMY_INTENTS = [
    "RETAIL_HOUSING_LOAN",
    "PMAY_SCHEMES",
    "STAFF_HOUSING",
    "INFRA_PROJECT_FINANCING",
    "CONSULTANCY_SERVICES",
    "FINANCIAL_RESULTS",
    "BONDS_AND_BORROWINGS",
    "ANNUAL_REPORTS",
    "LOCATE_OFFICE",
    "DOWNLOAD_FORMS",
    "FAQ_LOOKUP",
    "VIGILANCE_POLICY",
    "BOARD_MEMBERS"
]

class IntentClassifier:
    """Classifies document chunks into the HUDCO domain taxonomy and creates validated chunks."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.GEMINI_API_KEY

    def classify_rule_based(self, title: str, text: str) -> str:
        """Fast fallback intent tagging based on keyword presence."""
        text_lower = (title + " " + text).lower()

        if any(k in text_lower for k in ["pmay", "pradhan mantri awas", "clss", "interest subsidy"]):
            return "PMAY_SCHEMES"
        elif any(k in text_lower for k in ["home loan", "housing loan", "individual borrower", "margin money"]):
            return "RETAIL_HOUSING_LOAN"
        elif any(k in text_lower for k in ["profit after tax", "pat", "npa", "balance sheet", "net worth", "disbursement"]):
            return "FINANCIAL_RESULTS"
        elif any(k in text_lower for k in ["tax-free bond", "54ec", "capital gains bond", "borrowings", "debenture"]):
            return "BONDS_AND_BORROWINGS"
        elif any(k in text_lower for k in ["regional office", "branch office", "head office", "telephone", "email", "address"]):
            return "LOCATE_OFFICE"
        elif any(k in text_lower for k in ["water supply", "sewerage", "smart city", "infrastructure financing", "urban transport"]):
            return "INFRA_PROJECT_FINANCING"
        elif any(k in text_lower for k in ["board of directors", "director", "kmp", "management team"]):
            return "BOARD_MEMBERS"
        elif any(k in text_lower for k in ["vigilance", "whistle blower", "complaint portal"]):
            return "VIGILANCE_POLICY"
        elif any(k in text_lower for k in ["form", "download", "kyc format", "application format"]):
            return "DOWNLOAD_FORMS"
        else:
            return "ANNUAL_REPORTS"

    def create_unified_chunk(
        self,
        chunk_id: str,
        doc_id: str,
        source_info: Dict[str, Any],
        section_title: str,
        department: str,
        summary: str,
        text_content: str,
        tables: List[Dict[str, Any]] = None,
        entities: List[str] = None
    ) -> UnifiedChunk:
        """
        Builds and validates an atomic UnifiedChunk adhering to the Pydantic schema.
        """
        primary_intent = self.classify_rule_based(section_title, text_content)

        # Hash for deduplication
        raw_repr = f"{doc_id}_{section_title}_{text_content[:200]}"
        sha256_hash = hashlib.sha256(raw_repr.encode("utf-8")).hexdigest()

        table_items = []
        if tables:
            for t in tables:
                table_items.append(TableItem(
                    table_id=t.get("table_id", "T01"),
                    title=t.get("title", "Extracted Table"),
                    markdown=t.get("markdown", "")
                ))

        chunk = UnifiedChunk(
            chunk_id=chunk_id,
            document_id=doc_id,
            source=SourceMetadata(
                title=source_info.get("title", "HUDCO Publication"),
                document_type=source_info.get("document_type", "annual_report"),
                url=source_info.get("url"),
                fiscal_year=source_info.get("fiscal_year", "2024-25"),
                page_start=source_info.get("page_start", 1),
                page_end=source_info.get("page_end", 1),
                authority_tier=source_info.get("authority_tier", 1),
                is_latest=source_info.get("is_latest", True)
            ),
            classification=ClassificationMetadata(
                department=department,
                section_title=section_title,
                primary_intent=primary_intent,
                secondary_intents=[],
                entities_covered=entities or []
            ),
            content=ContentPayload(
                summary=summary,
                text_content=text_content,
                tables=table_items
            ),
            metadata=ChunkMetadata(
                char_count=len(text_content),
                token_estimate=len(text_content) // 4,
                sha256=sha256_hash,
                created_at=datetime.utcnow(),
                version=1
            )
        )

        return chunk
