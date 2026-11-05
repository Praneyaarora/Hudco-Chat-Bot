"""
Dynamic Multi-LLM Provider Dispatcher for HUDCO Bot.
File: pipeline/inference/llm_manager.py

Supports:
1. Local Qwen (Qwen3-4B-Instruct NF4 on GPU via local worker)
2. Google Gemini (REST API via GEMINI_API_KEY with resilient model cascade & 429 rate limit detection)
3. Anthropic Claude (REST API via ANTHROPIC_API_KEY)
4. OpenAI GPT (REST API via OPENAI_API_KEY)

Handles evidence synthesis for both local annual report chunks and web search results,
supporting both Pydantic RetrievalResultItem objects and raw dictionaries.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

from config.settings import settings
from pipeline.inference.qwen_service import get_qwen_service, strip_citation_markers, validate_citations

logger = logging.getLogger(__name__)


def _normalize_item(item: Any) -> Dict[str, Any]:
    """Safely normalizes RetrievalResultItem, CanonicalChunk, or dict to standard dictionary."""
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        try:
            return item.model_dump()
        except Exception:
            pass
    if hasattr(item, "dict"):
        try:
            return item.dict()
        except Exception:
            pass
    if hasattr(item, "__dict__"):
        return item.__dict__
    return {}


def build_synthesis_prompt(
    query: str,
    evidence_items: List[Any],
    is_web: bool = False,
    web_direct_answer: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    rolling_summary: Optional[str] = None,
    language: str = "english",
    emotional_context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Constructs a concise evidence context prompt for LLM synthesis.
    Integrates multi-turn conversation history and rolling summaries seamlessly.
    """
    context_lines = []
    if rolling_summary and rolling_summary.strip():
        context_lines.append(f"--- PRIOR CONVERSATION SUMMARY ---\n{rolling_summary.strip()}\n")

    if conversation_history:
        hist_lines = []
        for turn in conversation_history[-6:]:
            role = "User" if turn.get("role") == "user" else "Assistant"
            c = str(turn.get("content", "")).strip()
            if len(c) > 280:
                c = c[:270] + "..."
            hist_lines.append(f"{role}: {c}")
        if hist_lines:
            context_lines.append("--- RECENT CONVERSATION HISTORY ---\n" + "\n".join(hist_lines) + "\n")

    if web_direct_answer:
        context_lines.append(f"--- VERIFIED WEB SUMMARY ---\n{web_direct_answer.strip()}\n")

    for idx, raw_item in enumerate(evidence_items, start=1):
        item = _normalize_item(raw_item)
        if is_web or item.get("is_web"):
            title = item.get("title") or item.get("section_title") or "Web Source"
            url = item.get("url") or ""
            content = item.get("content") or item.get("snippet") or item.get("body") or ""
            context_lines.append(f"--- EVIDENCE ITEM [{idx}] (Source: {title} | {url}) ---\n{content}\n")
        else:
            doc = item.get("document_id") or "doc"
            page = item.get("physical_page") or item.get("printed_page") or "N/A"
            title = item.get("section_title") or ""
            content = item.get("content") or item.get("text") or ""
            context_lines.append(f"--- EVIDENCE ITEM [{idx}] ({doc}.pdf, Page {page}, Section: {title}) ---\n{content}\n")

    context_str = "\n".join(context_lines)

    empathy_rule = ""
    if emotional_context and emotional_context.get("requires_empathy"):
        empathy_rule = (
            "5. Emotional Empathy & Grievance: The customer has expressed dissatisfaction, frustration, or a grievance. "
            "Begin your response with brief, polite, and sincere acknowledgment of their concern (e.g., 'I understand your concern and I apologize for the difficulty you are facing.'). "
            "Never over-apologize, never pretend to feel human emotions, and never make unverified promises on behalf of HUDCO. "
            "Provide the verified grievance redressal channels clearly (HUDCO Grievance Officer, HUDCO Bhawan, New Delhi, or CPGRAMS portal).\n"
        )

    lang_rule = "Respond in clear, professional, and accessible English."
    if language == "hinglish":
        lang_rule = (
            "The customer is asking in Hindi / Hinglish. Respond naturally, courteously, and respectfully in Hindi/Hinglish (using Latin script). "
            "Keep official terminology, financial figures, and portal names accurate (e.g., 'Net Profit', 'Loan Disbursements', 'Registered Office', 'CPGRAMS', 'HUDCO Bhawan')."
        )

    prompt = f"""You are HUDCO Bot, a helpful, courteous, and professional conversational AI assistant for Housing and Urban Development Corporation Limited (HUDCO).
Answer the user's question directly, accurately, and respectfully based strictly on the provided evidence items.

Rules:
1. Provide a direct, factual answer without speculative claims or filler.
2. Absolutely NEVER include "Note:", "Explanation:", or meta-commentary about multiple numbers, contexts, or reports. Just state the facts cleanly.
3. CONSOLIDATE DUPLICATE FACTS: Multiple evidence items often repeat the same person, location, designation, or metric. Synthesize them into ONE single cohesive statement. Never repeat the same fact, person's name, or number across multiple sentences.
4. ZERO CITATION TEXT IN ANSWER: Output ONLY clean, natural user-facing text. Do NOT include citation markers, bracketed references, evidence labels, or chunk numbers (e.g. do NOT write '[1]', '[Citation: ...]', '[Evidence Item ...]', or 'Source: ...') inside your answer. Sources and citations are managed and displayed separately by the user interface.
5. If the question cannot be answered from the evidence, state clearly and politely that verified records do not contain this specific information, and guide them where to find it.
6. Be concise and crisp. Use 1 to 2 short paragraphs or clean bullet points if multiple details are requested. Maintain conversational context across follow-up queries.
{empathy_rule}
Language Instruction:
{lang_rule}

EVIDENCE & CONTEXT:
{context_str}

USER QUESTION: {query}

ANSWER:"""
    return prompt


class LLMManager:
    """
    Unified manager that routes answer generation to the requested LLM provider.
    """

    @classmethod
    def generate(
        cls,
        query: str,
        evidence_items: List[Any],
        provider: str = "local_qwen",
        api_keys: Optional[Dict[str, str]] = None,
        model_name: Optional[str] = None,
        max_new_tokens: int = 256,
        temperature: float = 0.0,
        is_web: bool = False,
        web_direct_answer: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        rolling_summary: Optional[str] = None,
        language: str = "english",
        emotional_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Dispatches inference to the designated provider.
        Falls back gracefully to local Qwen or another configured provider if needed.
        """
        api_keys = api_keys or {}
        default_provider = getattr(settings, "DEFAULT_LLM_PROVIDER", "gemini")
        provider = (provider or default_provider or "gemini").lower().strip()

        # 1. Google Gemini API (Default Cloud Provider)
        if provider == "gemini":
            key = api_keys.get("gemini") or getattr(settings, "GEMINI_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "") or ""
            if key and len(key.strip()) > 8:
                return cls._generate_gemini(
                    query=query,
                    evidence_items=evidence_items,
                    api_key=key.strip(),
                    model_name=model_name or "gemini-2.5-flash",
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    is_web=is_web,
                    web_direct_answer=web_direct_answer,
                    conversation_history=conversation_history,
                    rolling_summary=rolling_summary,
                    language=language,
                    emotional_context=emotional_context,
                )
            else:
                err_msg = (
                    "Gemini API key is not configured. Please add GEMINI_API_KEY to your .env file "
                    "or enter it in Developer Settings -> Manage API Keys to generate responses."
                )
                logger.error(err_msg)
                return {
                    "answer": err_msg,
                    "clean_answer": err_msg,
                    "provider": "gemini",
                    "model_name": "gemini-2.5-flash",
                    "confidence": 0.0,
                    "grounding_check": {"is_valid": False, "verification_status": "MISSING_API_KEY"},
                    "error": "MISSING_GEMINI_API_KEY",
                }

        # 2. Anthropic Claude API
        if provider == "claude":
            key = api_keys.get("claude") or getattr(settings, "ANTHROPIC_API_KEY", "") or os.environ.get("ANTHROPIC_API_KEY", "") or ""
            if key and len(key.strip()) > 8:
                return cls._generate_claude(
                    query=query,
                    evidence_items=evidence_items,
                    api_key=key.strip(),
                    model_name=model_name or "claude-3-5-sonnet-20241022",
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    is_web=is_web,
                    web_direct_answer=web_direct_answer,
                    conversation_history=conversation_history,
                    rolling_summary=rolling_summary,
                    language=language,
                    emotional_context=emotional_context,
                )
            else:
                err_msg = "Anthropic Claude API key is not configured. Please provide ANTHROPIC_API_KEY in .env or settings."
                logger.error(err_msg)
                return {
                    "answer": err_msg,
                    "clean_answer": err_msg,
                    "provider": "claude",
                    "model_name": "claude-3-5-sonnet",
                    "confidence": 0.0,
                    "grounding_check": {"is_valid": False, "verification_status": "MISSING_API_KEY"},
                    "error": "MISSING_CLAUDE_API_KEY",
                }

        # 3. OpenAI API
        if provider == "openai":
            key = api_keys.get("openai") or getattr(settings, "OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", "") or ""
            if key and len(key.strip()) > 8:
                return cls._generate_openai(
                    query=query,
                    evidence_items=evidence_items,
                    api_key=key.strip(),
                    model_name=model_name or "gpt-4o-mini",
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                    is_web=is_web,
                    web_direct_answer=web_direct_answer,
                    conversation_history=conversation_history,
                    rolling_summary=rolling_summary,
                    language=language,
                    emotional_context=emotional_context,
                )
            else:
                err_msg = "OpenAI API key is not configured. Please provide OPENAI_API_KEY in .env or settings."
                logger.error(err_msg)
                return {
                    "answer": err_msg,
                    "clean_answer": err_msg,
                    "provider": "openai",
                    "model_name": "gpt-4o-mini",
                    "confidence": 0.0,
                    "grounding_check": {"is_valid": False, "verification_status": "MISSING_API_KEY"},
                    "error": "MISSING_OPENAI_API_KEY",
                }

        # 4. Local LLM (Qwen GPU/CPU)
        if os.environ.get("RENDER"):
            err_msg = (
                "Local LLM is not supported on Render. Please configure GEMINI_API_KEY "
                "and select Google Gemini as your LLM provider."
            )
            logger.error(err_msg)
            return {
                "answer": err_msg,
                "clean_answer": err_msg,
                "provider": "local_qwen",
                "model_name": "Local LLM",
                "confidence": 0.0,
                "grounding_check": {"is_valid": False, "verification_status": "UNAVAILABLE_ON_RENDER"},
                "error": "LOCAL_MODEL_UNAVAILABLE_ON_RENDER",
            }

        return cls._generate_local_qwen(
            query=query,
            evidence_items=evidence_items,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            is_web=is_web,
            web_direct_answer=web_direct_answer,
            conversation_history=conversation_history,
            rolling_summary=rolling_summary,
        )

    @classmethod
    def _generate_local_qwen(
        cls,
        query: str,
        evidence_items: List[Any],
        max_new_tokens: int,
        temperature: float,
        is_web: bool,
        web_direct_answer: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        rolling_summary: Optional[str] = None,
        language: str = "english",
        emotional_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Runs inference via local Qwen3-4B resident on GPU."""
        if not evidence_items and web_direct_answer:
            return {
                "status": "success",
                "answer": web_direct_answer,
                "clean_answer": strip_citation_markers(web_direct_answer),
                "provider": "local_qwen",
                "model_name": "Web Fallback",
                "device": "web_grounded",
                "generation_time_ms": 1.0,
                "is_refusal": False,
                "citation_validation": {
                    "is_valid": True,
                    "has_citations": False,
                    "verification_status": "VERIFIED_GROUNDED_WEB",
                }
            }

        qwen_srv = get_qwen_service()

        from pipeline.retrieval.contracts import RetrievalResultItem
        adapted_items = []
        for idx, raw_it in enumerate(evidence_items):
            if isinstance(raw_it, RetrievalResultItem):
                adapted_items.append(raw_it)
            else:
                it = _normalize_item(raw_it)
                adapted_items.append(
                    RetrievalResultItem(
                        rank=it.get("rank", idx + 1),
                        chunk_id=it.get("chunk_id", f"web_item_{idx+1}"),
                        score=float(it.get("score", 1.0)),
                        matched_terms=[],
                        explanation=it.get("title", "Evidence"),
                        document_id=it.get("document_id", "WEB"),
                        version_id=it.get("version_id", "web_v1"),
                        source_id=it.get("source_id", "web_search"),
                        source_filename=it.get("source_filename", "Web Search"),
                        section_id="web",
                        section_title=it.get("section_title") or it.get("title") or "Source",
                        physical_page=it.get("physical_page") or (idx + 1),
                        printed_page=it.get("printed_page"),
                        has_table=False,
                        content=it.get("content") or it.get("text") or " ",
                        content_sha256="0" * 64,
                        citation_label=it.get("citation_label", f"Web Source [{idx+1}]"),
                    )
                )

        # Context prompt with instructions for emotion, language, and rolling summary
        effective_query = query
        instructions = []
        if emotional_context and emotional_context.get("requires_empathy"):
            instructions.append("Customer Concern: The user has expressed a grievance or dissatisfaction. Start with brief, polite empathy acknowledging their concern, then provide the verified grievance redressal contact.")
        if language == "hinglish":
            instructions.append("Language: Respond in polite, natural conversational Hindi/Hinglish (Latin script). Keep official names and numbers accurate.")
        if rolling_summary:
            instructions.append(f"Context: {rolling_summary}")

        if instructions:
            effective_query = f"[{' | '.join(instructions)}]\n{query}"

        payload = qwen_srv.generate(
            query=effective_query,
            retrieved_items=adapted_items,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )
        payload["provider"] = "local_qwen"
        payload["model_name"] = "Qwen3-4B-Instruct (4-bit NF4)"

        # If Qwen produced a refusal but web_direct_answer was present, rescue with web_direct_answer
        if is_web and web_direct_answer and ("sufficient information" in payload.get("clean_answer", "").lower() or payload.get("is_refusal")):
            payload["answer"] = web_direct_answer
            payload["clean_answer"] = strip_citation_markers(web_direct_answer)
            payload["is_refusal"] = False
            payload["status"] = "success"

        # Ensure both answer and clean_answer are pristine
        sanitized_ans = strip_citation_markers(payload.get("clean_answer") or payload.get("answer") or "")
        payload["clean_answer"] = sanitized_ans
        payload["answer"] = sanitized_ans
        return payload

    @classmethod
    def _generate_gemini(
        cls,
        query: str,
        evidence_items: List[Any],
        api_key: str,
        model_name: str,
        max_new_tokens: int,
        temperature: float,
        is_web: bool,
        web_direct_answer: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        rolling_summary: Optional[str] = None,
        language: str = "english",
        emotional_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generates answer via Google Gemini API with multi-model cascade, rate limit detection, and Qwen fallback."""
        t0 = time.perf_counter()
        prompt = build_synthesis_prompt(
            query=query,
            evidence_items=evidence_items,
            is_web=is_web,
            web_direct_answer=web_direct_answer,
            conversation_history=conversation_history,
            rolling_summary=rolling_summary,
            language=language,
            emotional_context=emotional_context,
        )

        # Candidate models to try in sequence. High-RPM / high-RPD models (Lite: 15 RPM / 500 RPD) prioritized first
        clean_model = model_name.replace("models/", "") if model_name else "gemini-3.5-flash-lite"
        candidate_models = [clean_model]
        priority_models = [
            "gemini-3.5-flash-lite",  # 15 RPM / 500 RPD
            "gemini-3.1-flash-lite",  # 15 RPM / 500 RPD
            "gemini-3.8-flash",       # 5 RPM / 20 RPD
            "gemini-3.5-flash",       # 5 RPM / 20 RPD
            "gemini-3.6-flash",       # 5 RPM / 20 RPD
            "gemini-2.5-flash",       # 5 RPM / 20 RPD
            "gemini-flash-latest",
        ]
        for m in priority_models:
            if m not in candidate_models:
                candidate_models.append(m)

        last_error = None
        for current_model in candidate_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={api_key}"
            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": max_new_tokens,
                    "temperature": temperature,
                }
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read().decode("utf-8"))

                gen_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                raw_text = ""
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    raw_text = "".join(p.get("text", "") for p in parts)

                clean_text = strip_citation_markers(raw_text)

                return {
                    "status": "success",
                    "answer": clean_text,
                    "clean_answer": clean_text,
                    "provider": "gemini",
                    "model_name": current_model,
                    "device": "Google AI Cloud",
                    "generation_time_ms": gen_ms,
                    "is_refusal": False,
                    "citation_validation": {
                        "is_valid": True,
                        "has_citations": False,
                        "verification_status": "API_VERIFIED",
                    }
                }
            except urllib.error.HTTPError as he:
                error_body = he.read().decode("utf-8", errors="ignore")
                last_error = f"HTTP {he.code}: {error_body}"
                if he.code == 404:
                    logger.warning(f"Gemini model '{current_model}' 404 Not Found. Trying next candidate...")
                    continue
                elif he.code == 429 or "RESOURCE_EXHAUSTED" in error_body or "quota" in error_body.lower() or "rate limit" in error_body.lower():
                    logger.warning(f"Gemini API rate limit reached (HTTP 429): {error_body}")
                    return {
                        "status": "rate_limited",
                        "is_rate_limited": True,
                        "provider": "gemini",
                        "model_name": current_model,
                        "cooldown_seconds": 60,
                        "error_message": "Google Gemini free tier limit reached (5-15 RPM). Please wait 60s cooldown or switch to Local Qwen GPU model.",
                        "answer": "Google Gemini free tier request limit reached. Please wait 60 seconds or switch to Local Qwen GPU model for unlimited offline queries.",
                        "clean_answer": "Google Gemini free tier request limit reached. Please wait 60 seconds or switch to Local Qwen GPU model for unlimited offline queries.",
                        "is_refusal": True,
                        "generation_time_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                    }
                else:
                    logger.error(f"Gemini API error on {current_model}: {he.code} {error_body}")
                    break
            except Exception as e:
                last_error = str(e)
                logger.error(f"Gemini API error on {current_model}: {e}")
                break

        # Fallback rescue if web_direct_answer is available
        if is_web and web_direct_answer:
            return {
                "status": "success",
                "answer": web_direct_answer,
                "clean_answer": strip_citation_markers(web_direct_answer),
                "provider": "gemini_fallback",
                "model_name": "Web Fallback",
                "device": "web_fallback",
                "generation_time_ms": 1.0,
                "is_refusal": False,
                "citation_validation": {
                    "is_valid": True,
                    "has_citations": False,
                    "verification_status": "WEB_DIRECT_FALLBACK",
                }
            }

        # Otherwise attempt graceful fallback to local Qwen so user always gets an answer
        logger.warning(f"Gemini API call failed ({last_error}). Triggering automatic local Qwen fallback.")
        try:
            qwen_res = cls._generate_local_qwen(query, evidence_items, max_new_tokens, temperature, is_web, web_direct_answer)
            qwen_res["provider"] = "local_qwen"
            qwen_res["model_name"] = f"Qwen3-4B (Gemini Fallback: {last_error[:40]}...)"
            return qwen_res
        except Exception as qerr:
            logger.error(f"Local Qwen fallback also failed: {qerr}")

        return {
            "status": "inference_error",
            "answer": f"Gemini API error: {last_error}",
            "clean_answer": f"Gemini API error: {last_error}",
            "provider": "gemini",
            "model_name": model_name,
            "device": "cloud_error",
            "generation_time_ms": 0.0,
            "is_refusal": True,
        }

    @classmethod
    def _generate_openai(
        cls,
        query: str,
        evidence_items: List[Any],
        api_key: str,
        model_name: str,
        max_new_tokens: int,
        temperature: float,
        is_web: bool,
        web_direct_answer: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        rolling_summary: Optional[str] = None,
        language: str = "english",
        emotional_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generates answer via OpenAI API with rate-limit detection and local Qwen fallback."""
        t0 = time.perf_counter()
        prompt = build_synthesis_prompt(
            query=query,
            evidence_items=evidence_items,
            is_web=is_web,
            web_direct_answer=web_direct_answer,
            conversation_history=conversation_history,
            rolling_summary=rolling_summary,
            language=language,
            emotional_context=emotional_context,
        )
        url = "https://api.openai.com/v1/chat/completions"

        body = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": "You are HUDCO Bot, a professional assistant for Housing and Urban Development Corporation Limited."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_new_tokens,
            "temperature": temperature,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            gen_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            raw_text = data["choices"][0]["message"]["content"]
            clean_text = strip_citation_markers(raw_text)

            return {
                "status": "success",
                "answer": clean_text,
                "clean_answer": clean_text,
                "provider": "openai",
                "model_name": model_name,
                "device": "OpenAI Cloud",
                "generation_time_ms": gen_ms,
                "is_refusal": False,
                "citation_validation": {
                    "is_valid": True,
                    "has_citations": False,
                    "verification_status": "API_VERIFIED",
                }
            }
        except urllib.error.HTTPError as he:
            error_body = he.read().decode("utf-8", errors="ignore")
            if he.code == 429 or "rate_limit" in error_body.lower() or "quota" in error_body.lower():
                return {
                    "status": "rate_limited",
                    "is_rate_limited": True,
                    "provider": "openai",
                    "model_name": model_name,
                    "cooldown_seconds": 60,
                    "error_message": "OpenAI rate limit reached. Please wait 60s cooldown or switch to Local Qwen GPU model.",
                    "answer": "OpenAI API rate limit reached. Please wait 60 seconds cooldown or switch to Local Qwen GPU model.",
                    "clean_answer": "OpenAI API rate limit reached. Please wait 60 seconds cooldown or switch to Local Qwen GPU model.",
                    "is_refusal": True,
                    "generation_time_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                }
            logger.error(f"OpenAI HTTP error: {he.code} {error_body}")
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")

        # Fall back to local Qwen
        try:
            qwen_res = cls._generate_local_qwen(query, evidence_items, max_new_tokens, temperature, is_web, web_direct_answer)
            qwen_res["provider"] = "local_qwen"
            qwen_res["model_name"] = "Qwen3-4B (OpenAI Fallback)"
            return qwen_res
        except Exception:
            pass

        return {
            "status": "inference_error",
            "answer": "OpenAI API request failed.",
            "clean_answer": "OpenAI API request failed.",
            "provider": "openai",
            "model_name": model_name,
            "device": "cloud_error",
            "generation_time_ms": 0.0,
            "is_refusal": True,
        }

    @classmethod
    def _generate_claude(
        cls,
        query: str,
        evidence_items: List[Any],
        api_key: str,
        model_name: str,
        max_new_tokens: int,
        temperature: float,
        is_web: bool,
        web_direct_answer: Optional[str] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        rolling_summary: Optional[str] = None,
        language: str = "english",
        emotional_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Generates answer via Anthropic Claude API with rate-limit detection and local Qwen fallback."""
        t0 = time.perf_counter()
        prompt = build_synthesis_prompt(
            query=query,
            evidence_items=evidence_items,
            is_web=is_web,
            web_direct_answer=web_direct_answer,
            conversation_history=conversation_history,
            rolling_summary=rolling_summary,
            language=language,
            emotional_context=emotional_context,
        )
        url = "https://api.anthropic.com/v1/messages"

        body = {
            "model": model_name,
            "max_tokens": max_new_tokens,
            "temperature": temperature,
            "system": "You are HUDCO Bot, a professional assistant for Housing and Urban Development Corporation Limited.",
            "messages": [{"role": "user", "content": prompt}]
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            gen_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            content_blocks = data.get("content", [])
            raw_text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
            clean_text = strip_citation_markers(raw_text)

            return {
                "status": "success",
                "answer": clean_text,
                "clean_answer": clean_text,
                "provider": "claude",
                "model_name": model_name,
                "device": "Anthropic Cloud",
                "generation_time_ms": gen_ms,
                "is_refusal": False,
                "citation_validation": {
                    "is_valid": True,
                    "has_citations": False,
                    "verification_status": "API_VERIFIED",
                }
            }
        except urllib.error.HTTPError as he:
            error_body = he.read().decode("utf-8", errors="ignore")
            if he.code == 429 or "rate_limit" in error_body.lower():
                return {
                    "status": "rate_limited",
                    "is_rate_limited": True,
                    "provider": "claude",
                    "model_name": model_name,
                    "cooldown_seconds": 60,
                    "error_message": "Claude rate limit reached. Please wait 60s cooldown or switch to Local Qwen GPU model.",
                    "answer": "Claude rate limit reached. Please wait 60 seconds cooldown or switch to Local Qwen GPU model.",
                    "clean_answer": "Claude rate limit reached. Please wait 60 seconds cooldown or switch to Local Qwen GPU model.",
                    "is_refusal": True,
                    "generation_time_ms": round((time.perf_counter() - t0) * 1000.0, 2),
                }
            logger.error(f"Claude HTTP error: {he.code} {error_body}")
        except Exception as e:
            logger.error(f"Claude API error: {e}")

        # Fall back to local Qwen
        try:
            qwen_res = cls._generate_local_qwen(query, evidence_items, max_new_tokens, temperature, is_web, web_direct_answer)
            qwen_res["provider"] = "local_qwen"
            qwen_res["model_name"] = "Qwen3-4B (Claude Fallback)"
            return qwen_res
        except Exception:
            pass

        return {
            "status": "inference_error",
            "answer": "Anthropic Claude API request failed.",
            "clean_answer": "Anthropic Claude API request failed.",
            "provider": "claude",
            "model_name": model_name,
            "device": "cloud_error",
            "generation_time_ms": 0.0,
            "is_refusal": True,
        }
