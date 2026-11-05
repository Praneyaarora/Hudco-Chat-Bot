"""
Optional Local LLM Answer Generation & Citation Validation Module via Ollama.
Operates strictly on retrieved HUDCO passages, verifies citations, and handles abstention.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Dict, Any, List, Optional, Tuple

from evaluation.config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT_SECONDS
from evaluation.schemas import RetrievalResultItem

logger = logging.getLogger("OllamaGenerator")

# Prompt template enforcing strict evidence-based grounding and citation formatting
STRICT_RAG_PROMPT_TEMPLATE = """You are an accurate enterprise AI assistant for Housing and Urban Development Corporation Limited (HUDCO).
Answer the user's question using ONLY the retrieved HUDCO passages provided below.

CRITICAL INSTRUCTIONS:
1. Ground every statement strictly in the provided passages. Do NOT extrapolate or use outside knowledge.
2. If the passages do not contain sufficient evidence to answer the question, you MUST explicitly state: "INSUFFICIENT_EVIDENCE: The provided HUDCO passages do not contain information to answer this question."
3. Every factual assertion must be followed by an exact citation to the Chunk ID in brackets, e.g. [CHUNK_ID].
4. Do NOT invent chunk IDs, document names, numbers, or page references.

---
RETRIEVED HUDCO EVIDENCE PASSAGES:
{context_passages}
---

USER QUESTION: {question}

ANSWER (grounded strictly in the above evidence with [CHUNK_ID] citations, or state INSUFFICIENT_EVIDENCE):"""


def check_ollama_available(base_url: str = OLLAMA_BASE_URL) -> Tuple[bool, str]:
    """Checks whether the Ollama local inference service is reachable."""
    try:
        req = urllib.request.Request(f"{base_url}/api/tags", headers={"User-Agent": "HUDCO-Evaluation"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in data.get("models", [])]
                return True, f"Ollama is running. Available models: {models}"
    except Exception as e:
        return False, f"Ollama service unreachable at {base_url}: {e}"
    return False, "Ollama service unreachable."


def validate_citations(
    answer: str,
    retrieved_items: List[RetrievalResultItem],
) -> Dict[str, Any]:
    """
    Extracts citations from generated text and validates them against retrieved chunks.
    Marks valid, invalid, and missing citations.
    """
    # Extract chunk-like citations from text e.g. [HUDCO_AR_..._c00]
    cited_ids = re.findall(r"\[(HUDCO_[A-Za-z0-9_\-]+)\]", answer)
    valid_ids = {item.chunk_id for item in retrieved_items}

    verified_citations = []
    hallucinated_citations = []

    for cid in cited_ids:
        if cid in valid_ids:
            verified_citations.append(cid)
        else:
            hallucinated_citations.append(cid)

    # Check for abstention keywords
    is_abstention = bool(
        "INSUFFICIENT_EVIDENCE" in answer
        or "does not contain" in answer.lower()
        or "insufficient evidence" in answer.lower()
    )

    return {
        "cited_chunk_ids": cited_ids,
        "verified_chunk_ids": verified_citations,
        "hallucinated_chunk_ids": hallucinated_citations,
        "citation_precision": (
            len(verified_citations) / len(cited_ids) if cited_ids else 1.0
        ),
        "has_citations": len(cited_ids) > 0,
        "is_abstention": is_abstention,
    }


class OllamaAnswerGenerator:
    """Optional generator module interfacing with local Ollama service."""

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model_name: str = OLLAMA_MODEL,
        timeout: int = OLLAMA_TIMEOUT_SECONDS,
    ):
        self.base_url = base_url
        self.model_name = model_name
        self.timeout = timeout

    def generate_grounded_answer(
        self,
        question: str,
        retrieved_items: List[RetrievalResultItem],
    ) -> Dict[str, Any]:
        """
        Formats retrieved passages into prompt, sends to Ollama, and validates citations.
        """
        is_up, msg = check_ollama_available(self.base_url)
        if not is_up:
            return {
                "status": "OLLAMA_UNAVAILABLE",
                "error": msg,
                "answer": None,
                "citation_validity": None,
            }

        # Build context passages string
        context_blocks = []
        for item in retrieved_items:
            pr_label = f", Printed P.{item.printed_page}" if item.printed_page else ""
            block = (
                f"[{item.chunk_id}] (Section: {item.section_title}, Physical P.{item.physical_page}{pr_label}):\n"
                f"{item.text}\n"
            )
            context_blocks.append(block)

        context_str = "\n".join(context_blocks)
        prompt = STRICT_RAG_PROMPT_TEMPLATE.format(
            context_passages=context_str,
            question=question,
        )

        # Call Ollama API
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "top_p": 0.9},
        }

        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/generate",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                raw_answer = result.get("response", "").strip()

            citation_eval = validate_citations(raw_answer, retrieved_items)

            return {
                "status": "SUCCESS",
                "answer": raw_answer,
                "model": self.model_name,
                "citation_validity": citation_eval,
            }

        except Exception as e:
            logger.error(f"Ollama generation failed: {e}")
            return {
                "status": "GENERATION_ERROR",
                "error": str(e),
                "answer": None,
                "citation_validity": None,
            }
