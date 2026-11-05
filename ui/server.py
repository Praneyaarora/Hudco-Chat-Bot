"""
HUDCO Bot — Conversational AI & Research Harness Server
File: ui/server.py

Provides:
- Static file serving for HUDCO Web UI with strict no-cache headers.
- Multi-User Authentication (Argon2id + HttpOnly Session Cookies).
- User-Isolated Persistent Storage (Local `context/` or Render Persistent Disk `/var/data/context`).
- Dynamic Multi-Turn Chat Sessions with Rolling Context Summarizer.
- Context Budget Window Telemetry & Real-Time Token Calculation.
- Hybrid Local RAG (BM25 + Dense Semantic RRF) & Guarded Official Web Search (Tavily + DuckDuckGo Fallback).
- Multi-LLM Orchestration: Local Qwen3-4B-Instruct (4-bit GPU) & Cloud Providers (Gemini, Claude, OpenAI).
"""

import http.server
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
from pathlib import Path
import re
import sys
import threading
import time
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, parse_qs

# UTF-8 stdout configuration for Windows terminals
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from pipeline.core.contracts import CanonicalChunk
from pipeline.retrieval.contracts import RetrievalFilter, RetrievalResponse
from pipeline.retrieval.bm25 import Layer4BM25Index
from pipeline.retrieval.semantic_search import PersistentVectorIndex
from pipeline.retrieval.hybrid_search import HybridRetriever
from pipeline.retrieval.tavily_search import TavilySearchAgent
from pipeline.inference.gpu_telemetry import get_gpu_telemetry
from pipeline.inference.qwen_service import get_qwen_service
from pipeline.inference.conversational_agent import check_conversational_intent, detect_language, detect_emotional_tone
from pipeline.inference.llm_manager import LLMManager, strip_citation_markers

# Storage & Context Management
from pipeline.storage.contracts import ChatMessage, UserProfile, UserProfilePublic
from pipeline.storage.conversation_storage import get_conversation_storage
from pipeline.storage.auth_manager import get_auth_manager
from pipeline.context.token_meter import (
    MODEL_CONTEXT_SPECS,
    validate_context_budget,
    calculate_context_telemetry,
    prune_conversation_turns,
    estimate_tokens,
)
from pipeline.context.rolling_summarizer import RollingSummarizer
from pipeline.context.query_context_rewriter import QueryContextRewriter

logger = logging.getLogger("hudco_bot.server")
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Initialize Subsystems
CONV_STORAGE = get_conversation_storage()
AUTH_MANAGER = get_auth_manager()
ROLLING_SUMMARIZER = RollingSummarizer()
QUERY_REWRITER = QueryContextRewriter()

# Dynamic runtime configuration (Defaults to Gemini; secrets loaded securely from env)
DYNAMIC_CONFIG = {
    "provider": os.environ.get("DEFAULT_LLM_PROVIDER") or getattr(settings, "DEFAULT_LLM_PROVIDER", "gemini"),
    "tavily_api_key": os.environ.get("TAVILY_API_KEY") or getattr(settings, "TAVILY_API_KEY", "") or "",
    "gemini_api_key": os.environ.get("GEMINI_API_KEY") or getattr(settings, "GEMINI_API_KEY", "") or "",
    "claude_api_key": os.environ.get("ANTHROPIC_API_KEY") or getattr(settings, "ANTHROPIC_API_KEY", "") or "",
    "openai_api_key": os.environ.get("OPENAI_API_KEY") or getattr(settings, "OPENAI_API_KEY", "") or "",
    "enable_web_search": True,
    "context_budget": 8192,
}


class PipelineState:
    """Caches active indices non-destructively in memory for rapid retrieval."""
    def __init__(self):
        self.bm25_index: Optional[Layer4BM25Index] = None
        self.semantic_index: Optional[PersistentVectorIndex] = None
        self.hybrid_retriever: Optional[HybridRetriever] = None
        self.inventory: List[Dict[str, Any]] = []
        self.index_stats: Dict[str, Any] = {}
        self.init_error: Optional[str] = None

    def initialize(self) -> None:
        try:
            inv_path = PROJECT_ROOT / "data" / "annual_reports_inventory.json"
            if inv_path.exists():
                with open(inv_path, "r", encoding="utf-8") as f:
                    self.inventory = json.load(f)

            self.semantic_index = PersistentVectorIndex()
            if self.semantic_index.exists():
                self.semantic_index.load(strict=False, mmap_mode="r")
                manifest = self.semantic_index.manifest
                self.index_stats = {
                    "exists": True,
                    "total_chunks": manifest.total_chunks if manifest else len(self.semantic_index.metadata_records),
                    "dimension": getattr(manifest, "embedding_dimension", 384) if manifest else 384,
                    "embedding_model": manifest.embedding_model if manifest else "sentence-transformers/all-MiniLM-L6-v2",
                    "embedding_model_revision": getattr(manifest, "embedding_model_revision", "") if manifest else "",
                    "index_schema_version": getattr(manifest, "schema_version", "1.1") if manifest else "1.1",
                    "index_dir": str(self.semantic_index.index_dir),
                }
            else:
                self.index_stats = {"exists": False, "total_chunks": 0}

            chunks_to_index: List[CanonicalChunk] = []
            if self.semantic_index and self.semantic_index.metadata_records:
                for rec in self.semantic_index.metadata_records:
                    chunk = CanonicalChunk(
                        chunk_id=rec["chunk_id"],
                        document_id=rec["document_id"],
                        source_id=rec.get("source_id") or "hudco_source",
                        source_filename=rec.get("source_filename") or f"{rec.get('document_id')}.pdf",
                        version_id=rec.get("version_id") or "v1",
                        chunk_index_in_page=1,
                        char_count=len(rec.get("content", "")),
                        token_estimate=len(rec.get("content", "").split()),
                        section_id=rec.get("section_id") or "sec_00",
                        section_title=rec.get("section_title") or "Section",
                        ancestor_headings=[],
                        physical_page=rec.get("physical_page") or 1,
                        physical_page_end=rec.get("physical_page_end"),
                        physical_pages=rec.get("physical_pages") or [rec.get("physical_page") or 1],
                        printed_page=rec.get("printed_page"),
                        printed_page_end=rec.get("printed_page_end"),
                        printed_pages=rec.get("printed_pages") or [],
                        fiscal_year=rec.get("fiscal_year") or "Unknown",
                        content=rec.get("content") or " ",
                        content_sha256=rec.get("content_sha256") or ("0" * 64),
                        has_table=bool(rec.get("has_table", False)),
                    )
                    chunks_to_index.append(chunk)

            # Direct fallback: if vector index load was bypassed or empty, read chunks_metadata.jsonl directly
            if not chunks_to_index:
                meta_file = PROJECT_ROOT / "data" / "vector_index" / "chunks_metadata.jsonl"
                if meta_file.exists():
                    logger.info("Reading canonical chunks directly from %s for BM25 retrieval...", meta_file)
                    with open(meta_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if not line.strip():
                                continue
                            rec = json.loads(line)
                            chunk = CanonicalChunk(
                                chunk_id=rec["chunk_id"],
                                document_id=rec["document_id"],
                                source_id=rec.get("source_id") or "hudco_source",
                                source_filename=rec.get("source_filename") or f"{rec.get('document_id')}.pdf",
                                version_id=rec.get("version_id") or "v1",
                                chunk_index_in_page=1,
                                char_count=len(rec.get("content", "")),
                                token_estimate=len(rec.get("content", "").split()),
                                section_id=rec.get("section_id") or "sec_00",
                                section_title=rec.get("section_title") or "Section",
                                ancestor_headings=[],
                                physical_page=rec.get("physical_page") or 1,
                                physical_page_end=rec.get("physical_page_end"),
                                physical_pages=rec.get("physical_pages") or [rec.get("physical_page") or 1],
                                printed_page=rec.get("printed_page"),
                                printed_page_end=rec.get("printed_page_end"),
                                printed_pages=rec.get("printed_pages") or [],
                                fiscal_year=rec.get("fiscal_year") or "Unknown",
                                content=rec.get("content") or " ",
                                content_sha256=rec.get("content_sha256") or ("0" * 64),
                                has_table=bool(rec.get("has_table", False)),
                            )
                            chunks_to_index.append(chunk)

            if chunks_to_index:
                self.bm25_index = Layer4BM25Index(chunks=chunks_to_index)
                if hasattr(self.bm25_index, "searchable_texts"):
                    self.bm25_index.searchable_texts.clear()
                logger.info("Initialized BM25 index with %d canonical chunks.", len(chunks_to_index))
                del chunks_to_index
                import gc
                gc.collect()

            # Render Free (512MB RAM constraint):
            # Avoid loading PyTorch CPU runtime (~440MB) which exceeds Render Free 512MB limit.
            is_render = bool(os.environ.get("RENDER")) or os.environ.get("DISABLE_LOCAL_EMBEDDINGS", "").lower() == "true"
            if self.bm25_index:
                if is_render:
                    if self.semantic_index:
                        self.semantic_index.metadata_records = []
                        self.semantic_index.chunk_id_to_idx = {}
                        self.semantic_index.embeddings = None
                        import gc
                        gc.collect()
                    self.hybrid_retriever = HybridRetriever(
                        bm25_index=self.bm25_index,
                        semantic_index=None,
                    )
                    logger.info("Initialized Render Free-optimized Retriever using BM25 lexical engine (PyTorch bypassed to conserve 512MB RAM).")
                elif self.semantic_index:
                    self.hybrid_retriever = HybridRetriever(
                        bm25_index=self.bm25_index,
                        semantic_index=self.semantic_index,
                    )
                    logger.info("Initialized HybridRetriever (RRF) combining BM25 and Semantic search.")

        except Exception as e:
            self.init_error = f"Pipeline initialization failed: {e}"
            logger.error(self.init_error, exc_info=True)


GLOBAL_STATE = PipelineState()


class HUDCOUIRequestHandler(SimpleHTTPRequestHandler):
    """
    Handles static asset requests and full REST API routing for HUDCO Bot.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self):
        """Strict no-cache headers for instant UI hot-reloading."""
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def _is_allowed_origin(self, origin: str) -> bool:
        """Determines if Origin header is allowed for CORS."""
        if not origin:
            return False
        return (
            origin in ("http://127.0.0.1:8501", "http://localhost:8501")
            or origin.endswith(".onrender.com")
            or origin.startswith("https://hudco")
            or origin == os.environ.get("ALLOWED_ORIGIN")
        )

    def do_OPTIONS(self):
        self.send_response(204)
        origin = self.headers.get("Origin", "")
        if self._is_allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    # =========================================================================
    # Request Routing
    # =========================================================================
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Static assets
        if path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()

        # Health check endpoint for Render zero-downtime health checking
        if path in ("/health", "/api/health"):
            storage_type = "postgres" if getattr(CONV_STORAGE, "is_postgres", False) else "file"
            health_payload = {
                "status": "ok",
                "service": "hudco-bot",
                "render_deployment": bool(os.environ.get("RENDER")),
                "storage_backend": storage_type,
                "uptime": time.time(),
            }
            return self._send_json(200, health_payload)

        # Auth & System APIs
        if path == "/api/status":
            return self._handle_status()
        elif path == "/api/reports":
            return self._handle_reports()
        elif path == "/api/config":
            return self._handle_get_config()
        elif path == "/api/auth/me":
            return self._handle_auth_me()

        # Chat Management APIs
        elif path == "/api/chats":
            return self._handle_list_chats()
        elif path.startswith("/api/chats/"):
            # Check for export or detail: /api/chats/{id} or /api/chats/{id}/export
            parts = path.strip("/").split("/")
            if len(parts) == 3:  # api, chats, {session_id}
                session_id = parts[2]
                return self._handle_get_chat(session_id)
            elif len(parts) == 4 and parts[3] == "export":  # api, chats, {session_id}, export
                session_id = parts[2]
                return self._handle_export_chat(session_id)

        return super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Auth APIs
        if path == "/api/auth/register":
            return self._handle_auth_register()
        elif path == "/api/auth/login":
            return self._handle_auth_login()
        elif path == "/api/auth/logout":
            return self._handle_auth_logout()

        # Chat & Inference APIs
        elif path == "/api/chats":
            return self._handle_create_chat()
        elif path == "/api/chats/import":
            return self._handle_import_chat()
        elif path == "/api/query":
            return self._handle_query()
        elif path == "/api/config":
            return self._handle_post_config()

        self._send_json(404, {"error": f"Endpoint not found: {path}"})

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/chats/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:  # api, chats, {session_id}
                session_id = parts[2]
                return self._handle_update_chat(session_id)

        self._send_json(404, {"error": f"Endpoint not found: {path}"})

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/chats/"):
            parts = path.strip("/").split("/")
            if len(parts) == 3:  # api, chats, {session_id}
                session_id = parts[2]
                return self._handle_delete_chat(session_id)

        self._send_json(404, {"error": f"Endpoint not found: {path}"})

    # =========================================================================
    # Response & Auth Helpers
    # =========================================================================
    def _send_json(self, status_code: int, data: Any, extra_headers: Optional[List[tuple]] = None) -> None:
        payload = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        origin = self.headers.get("Origin", "")
        if self._is_allowed_origin(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
        if extra_headers:
            for k, v in extra_headers:
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(payload)

    def _get_authenticated_user(self) -> Optional[UserProfile]:
        """Strictly extracts authenticated user from verified session token."""
        return AUTH_MANAGER.authenticate_request(self.headers)

    def _resolve_active_user(self) -> str:
        """
        Returns authenticated user_id if logged in, or provisions/returns
        the default guest user for seamless out-of-the-box usage.
        Operates uniformly on PostgreSQL and local file storage without touching users_dir.
        """
        user = self._get_authenticated_user()
        if user:
            return user.user_id

        guest_email = "guest@local.dev"
        guest = CONV_STORAGE.get_user_by_email(guest_email)
        if guest:
            return guest.user_id

        try:
            guest = CONV_STORAGE.create_user(
                email=guest_email,
                username="Guest User",
                password="guest_local_password_secure",
                role="guest",
            )
            return guest.user_id
        except Exception:
            # Re-query in case of concurrent creation race condition
            guest = CONV_STORAGE.get_user_by_email(guest_email)
            if guest:
                return guest.user_id
            return "usr_guest_fallback"

    # =========================================================================
    # Auth Endpoints
    # =========================================================================
    def _handle_auth_register(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8") if length > 0 else "{}")
            name = (body.get("name") or body.get("username") or "").strip()
            email = (body.get("email") or "").strip().lower()
            password = body.get("password", "")

            if not name or len(name) < 2:
                self._send_json(400, {"error": "Name must be at least 2 characters long."})
                return
            if not email or "@" not in email:
                self._send_json(400, {"error": "A valid email address is required."})
                return
            if not password or len(password) < 6:
                self._send_json(400, {"error": "Password must be at least 6 characters long."})
                return

            user = CONV_STORAGE.create_user(email=email, username=name, password=password)
            token = AUTH_MANAGER.create_session(user.user_id)
            cookie_header = AUTH_MANAGER.build_set_cookie_header(token)

            self._send_json(
                201,
                {
                    "success": True,
                    "message": "Account created successfully.",
                    "user": user.to_public().dict(),
                },
                extra_headers=[("Set-Cookie", cookie_header)]
            )
        except ValueError as ve:
            self._send_json(400, {"error": str(ve)})
        except Exception as e:
            logger.error("Registration error: %s", e, exc_info=True)
            self._send_json(500, {"error": f"Server registration error: {e}"})

    def _handle_auth_login(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8") if length > 0 else "{}")
            email = (body.get("email") or "").strip().lower()
            password = body.get("password", "")

            if not email or not password:
                self._send_json(400, {"error": "Email and password are required."})
                return

            user = CONV_STORAGE.authenticate_user(email=email, password=password)
            if not user:
                self._send_json(401, {"error": "Invalid email or password."})
                return

            token = AUTH_MANAGER.create_session(user.user_id)
            cookie_header = AUTH_MANAGER.build_set_cookie_header(token)

            self._send_json(
                200,
                {
                    "success": True,
                    "message": "Authenticated successfully.",
                    "user": user.to_public().dict(),
                },
                extra_headers=[("Set-Cookie", cookie_header)]
            )
        except Exception as e:
            logger.error("Login error: %s", e, exc_info=True)
            self._send_json(500, {"error": f"Authentication server error: {e}"})
        except Exception as e:
            logger.error("Login error: %s", e, exc_info=True)
            self._send_json(500, {"error": f"Authentication server error: {e}"})

    def _handle_auth_logout(self) -> None:
        token = AUTH_MANAGER.extract_token_from_headers(self.headers)
        if token:
            AUTH_MANAGER.revoke_session(token)
        clear_cookie_hdr = AUTH_MANAGER.build_clear_cookie_header()
        self._send_json(
            200,
            {"success": True, "message": "Signed out successfully."},
            extra_headers=[("Set-Cookie", clear_cookie_hdr)]
        )

    def _handle_auth_me(self) -> None:
        user = self._get_authenticated_user()
        if not user:
            self._send_json(200, {"authenticated": False, "user": None})
            return
        self._send_json(200, {"authenticated": True, "user": user.to_public().dict()})

    # =========================================================================
    # Conversation Sessions Management Endpoints (Strict User Ownership)
    # =========================================================================
    def _handle_list_chats(self) -> None:
        user_id = self._resolve_active_user()
        sessions = CONV_STORAGE.list_conversations(user_id)
        self._send_json(200, {"user_id": user_id, "conversations": [s.dict() for s in sessions]})

    def _handle_create_chat(self) -> None:
        try:
            user_id = self._resolve_active_user()
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8") if length > 0 else "{}")
            title = body.get("title", "New Conversation")
            session = CONV_STORAGE.create_conversation(user_id=user_id, title=title)
            self._send_json(201, {"success": True, "session": session.dict()})
        except Exception as e:
            logger.error("Error creating chat session: %s", e, exc_info=True)
            self._send_json(500, {"error": str(e)})

    def _handle_get_chat(self, session_id: str) -> None:
        user_id = self._resolve_active_user()
        session = CONV_STORAGE.get_conversation(user_id=user_id, session_id=session_id)
        if not session:
            self._send_json(404, {"error": "Conversation not found."})
            return

        # Calculate context telemetry for loaded session
        turns = [m.dict() if hasattr(m, "dict") else m for m in session.messages]
        telemetry = calculate_context_telemetry(
            system_prompt="You are HUDCO Bot, the official AI research and customer assistant for Housing and Urban Development Corporation Limited.",
            rolling_summary=session.rolling_summary,
            active_turns=turns,
            evidence_items=[],
            user_query="",
            max_budget=DYNAMIC_CONFIG.get("context_budget", 8192),
        )
        self._send_json(200, {
            "success": True,
            "session": session.dict(),
            "context_telemetry": telemetry.dict(),
        })

    def _handle_update_chat(self, session_id: str) -> None:
        try:
            user_id = self._resolve_active_user()
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8") if length > 0 else "{}")
            new_title = body.get("title", "").strip()
            if not new_title:
                self._send_json(400, {"error": "Title cannot be empty."})
                return
            ok = CONV_STORAGE.rename_conversation(user_id=user_id, session_id=session_id, new_title=new_title)
            if not ok:
                self._send_json(404, {"error": "Conversation not found."})
                return
            self._send_json(200, {"success": True, "title": new_title})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_delete_chat(self, session_id: str) -> None:
        user_id = self._resolve_active_user()
        ok = CONV_STORAGE.delete_conversation(user_id=user_id, session_id=session_id)
        if not ok:
            self._send_json(404, {"error": "Conversation not found."})
            return
        self._send_json(200, {"success": True, "message": "Conversation deleted."})

    def _handle_export_chat(self, session_id: str) -> None:
        user_id = self._resolve_active_user()
        export_data = CONV_STORAGE.export_conversation(user_id=user_id, session_id=session_id)
        if not export_data:
            self._send_json(404, {"error": "Conversation not found."})
            return
        self._send_json(200, export_data)

    def _handle_import_chat(self) -> None:
        try:
            user_id = self._resolve_active_user()
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length).decode("utf-8") if length > 0 else "{}")
            session = CONV_STORAGE.import_conversation(user_id=user_id, data=body)
            if not session:
                self._send_json(400, {"error": "Failed to parse imported conversation data."})
                return
            self._send_json(201, {"success": True, "session": session.dict()})
        except Exception as e:
            self._send_json(400, {"error": f"Import failed: {e}"})

    # =========================================================================
    # Status & Configuration Endpoints
    # =========================================================================
    def _handle_status(self) -> None:
        gpu_data = get_gpu_telemetry()
        qwen_srv = get_qwen_service()
        qwen_status = qwen_srv.get_status()

        eligible_count = sum(
            1 for r in GLOBAL_STATE.inventory
            if not ((r.get("status") == "PROCESSING_BLOCKED_REQUIRES_OCR") or ("ar20" in r.get("document_id", "")))
        )

        response = {
            "status": "online" if not GLOBAL_STATE.init_error else "degraded",
            "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "gpu": gpu_data,
            "qwen": qwen_status,
            "index": GLOBAL_STATE.index_stats,
            "reports_count": eligible_count,
            "total_reports_inventory": len(GLOBAL_STATE.inventory),
            "bm25_chunks_indexed": GLOBAL_STATE.bm25_index.N if GLOBAL_STATE.bm25_index else 0,
            "semantic_chunks_indexed": GLOBAL_STATE.index_stats.get("total_chunks", 0) if GLOBAL_STATE.semantic_index else 0,
            "active_provider": DYNAMIC_CONFIG["provider"],
            "tavily_configured": bool(DYNAMIC_CONFIG["tavily_api_key"]),
            "context_budget": DYNAMIC_CONFIG["context_budget"],
            "model_context_specs": MODEL_CONTEXT_SPECS,
            "init_error": GLOBAL_STATE.init_error,
        }
        self._send_json(200, response)

    def _handle_get_config(self) -> None:
        def mask_key(k: str) -> str:
            if not k:
                return ""
            if len(k) <= 8:
                return "********"
            return f"{k[:4]}...{k[-4:]}"

        data = {
            "provider": DYNAMIC_CONFIG["provider"],
            "enable_web_search": DYNAMIC_CONFIG["enable_web_search"],
            "context_budget": DYNAMIC_CONFIG["context_budget"],
            "tavily_configured": bool(DYNAMIC_CONFIG["tavily_api_key"]),
            "gemini_configured": bool(DYNAMIC_CONFIG["gemini_api_key"]),
            "claude_configured": bool(DYNAMIC_CONFIG["claude_api_key"]),
            "openai_configured": bool(DYNAMIC_CONFIG["openai_api_key"]),
            "local_qwen_available": bool(get_qwen_service().enabled),
            "model_specs": MODEL_CONTEXT_SPECS,
            "masked_keys": {
                "tavily": mask_key(DYNAMIC_CONFIG["tavily_api_key"]),
                "gemini": mask_key(DYNAMIC_CONFIG["gemini_api_key"]),
                "claude": mask_key(DYNAMIC_CONFIG["claude_api_key"]),
                "openai": mask_key(DYNAMIC_CONFIG["openai_api_key"]),
            }
        }
        self._send_json(200, data)

    def _handle_post_config(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(length).decode("utf-8") if length > 0 else "{}")

            if "provider" in data:
                prov = data["provider"].lower().strip()
                if prov in ("local_qwen", "gemini", "claude", "openai"):
                    DYNAMIC_CONFIG["provider"] = prov

            if "enable_web_search" in data:
                DYNAMIC_CONFIG["enable_web_search"] = bool(data["enable_web_search"])

            if "context_budget" in data:
                try:
                    requested_budget = int(data["context_budget"])
                    safe_b, _ = validate_context_budget(DYNAMIC_CONFIG["provider"], requested_budget)
                    DYNAMIC_CONFIG["context_budget"] = safe_b
                except (ValueError, TypeError):
                    pass

            keys = data.get("api_keys", {})
            if "tavily" in keys and keys["tavily"].strip():
                DYNAMIC_CONFIG["tavily_api_key"] = keys["tavily"].strip()
            if "gemini" in keys and keys["gemini"].strip():
                DYNAMIC_CONFIG["gemini_api_key"] = keys["gemini"].strip()
            if "claude" in keys and keys["claude"].strip():
                DYNAMIC_CONFIG["claude_api_key"] = keys["claude"].strip()
            if "openai" in keys and keys["openai"].strip():
                DYNAMIC_CONFIG["openai_api_key"] = keys["openai"].strip()

            self._send_json(200, {"status": "success", "config": DYNAMIC_CONFIG})
        except Exception as e:
            self._send_json(400, {"error": f"Failed to update config: {e}"})

    def _handle_reports(self) -> None:
        """Returns verified HUDCO Annual Reports inventory (FY 2014-24)."""
        reports = []
        for item in GLOBAL_STATE.inventory:
            is_quarantined = (item.get("status") == "PROCESSING_BLOCKED_REQUIRES_OCR") or ("ar20" in item.get("document_id", ""))
            reports.append({
                "document_id": item.get("document_id"),
                "fiscal_year": item.get("fiscal_year"),
                "filename": item.get("filename"),
                "total_pages": item.get("page_count", 0),
                "status": "QUARANTINED" if is_quarantined else "INDEXED",
                "quarantine_reason": item.get("quarantine_reason") if is_quarantined else None,
                "is_selectable": not is_quarantined
            })
        self._send_json(200, {"reports": reports, "total": len(reports)})

    # =========================================================================
    # Conversational RAG Inference with Multi-Turn Memory & Rolling Summary
    # =========================================================================
    def _handle_query(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                self._send_json(400, {"error": "Missing JSON request body."})
                return

            data = json.loads(self.rfile.read(length).decode("utf-8"))
            query = data.get("query", "").strip()
            if not query:
                self._send_json(400, {"error": "Query parameter cannot be empty."})
                return

            user_id = self._resolve_active_user()
            session_id = data.get("session_id")

            # Resolve or create conversation session
            session = None
            if session_id:
                session = CONV_STORAGE.get_conversation(user_id=user_id, session_id=session_id)
            if not session:
                session = CONV_STORAGE.create_conversation(
                    user_id=user_id,
                    title=query[:36] + ("..." if len(query) > 36 else "")
                )
                session_id = session.session_id

            # Context budget configuration
            provider = data.get("provider") or DYNAMIC_CONFIG.get("provider", "local_qwen")
            req_budget = int(data.get("context_budget") or DYNAMIC_CONFIG.get("context_budget", 8192))
            context_budget, budget_warning = validate_context_budget(provider, req_budget)

            # Language and Emotional Tone Detection
            lang = detect_language(query)
            emotional_context = detect_emotional_tone(query)

            # 1. Conversational Greeting / Chit-chat / Incomplete Visit Intent Filter
            conv_res = check_conversational_intent(query, recent_turns=session.messages)
            if conv_res:
                conv_reply = conv_res.get("answer", "")
                user_msg = ChatMessage(role="user", content=query, token_count=estimate_tokens(query))
                bot_msg = ChatMessage(
                    role="assistant",
                    content=conv_reply,
                    evidence_payload=[],
                    token_count=estimate_tokens(conv_reply)
                )
                CONV_STORAGE.save_message(user_id=user_id, session_id=session_id, message=user_msg)
                CONV_STORAGE.save_message(user_id=user_id, session_id=session_id, message=bot_msg)

                telemetry = calculate_context_telemetry(
                    system_prompt="HUDCO Conversational Assistant",
                    rolling_summary=session.rolling_summary,
                    active_turns=[{"role": "user", "content": query}],
                    evidence_items=[],
                    user_query=query,
                    max_budget=context_budget,
                )

                self._send_json(200, {
                    "query": query,
                    "session_id": session_id,
                    "retrieval_method": "conversational_intent",
                    "status": "conversational_greeting",
                    "is_abstention": False,
                    "is_conversational": True,
                    "results": [],
                    "answer": {
                        "status": "success",
                        "answer": conv_reply,
                        "clean_answer": conv_reply,
                        "provider": "conversational_guardrail",
                        "model_name": "Direct Intent Handler",
                        "device": "in-memory",
                        "generation_time_ms": 0.5,
                        "is_refusal": False,
                        "citation_validation": {"is_valid": True, "has_citations": False}
                    },
                    "context_telemetry": telemetry.dict(),
                    "live_gpu_telemetry": get_gpu_telemetry(),
                })
                return

            # 2. Context Window Sliding & Rolling Summary
            # Split prior session messages into active window and pruned turns
            # Max tokens allocated for history turns = ~40% of context budget
            max_history_budget = int(context_budget * 0.40)
            active_turns, pruned_turns = prune_conversation_turns(
                messages=session.messages,
                max_history_tokens=max_history_budget
            )

            # Update rolling summary if older turns were pruned
            rolling_summary = session.rolling_summary
            if pruned_turns:
                rolling_summary = ROLLING_SUMMARIZER.summarize_turns(
                    existing_summary=rolling_summary,
                    pruned_turns=pruned_turns,
                    active_provider=provider,
                    gemini_api_key=DYNAMIC_CONFIG.get("gemini_api_key")
                )
                CONV_STORAGE.update_rolling_summary(
                    user_id=user_id,
                    session_id=session_id,
                    summary_text=rolling_summary,
                    pruned_turns=len(pruned_turns)
                )

            # 3. Contextual Query Rewriting for Pronouns/Follow-ups
            search_query = QUERY_REWRITER.rewrite_query(
                current_query=query,
                recent_turns=active_turns,
                rolling_summary=rolling_summary
            )

            # Request Parameters
            method = data.get("method", "hybrid_rrf")
            top_k = int(data.get("top_k", 5))
            generate_answer = bool(data.get("generate_answer", True))
            max_new_tokens = int(data.get("max_new_tokens", 256))
            temperature = float(data.get("temperature", 0.0))
            enable_web = data.get("enable_web_search", DYNAMIC_CONFIG.get("enable_web_search", True))
            api_keys_payload = data.get("api_keys") or {}

            merged_keys = {
                "tavily": api_keys_payload.get("tavily") or DYNAMIC_CONFIG.get("tavily_api_key") or getattr(settings, "TAVILY_API_KEY", ""),
                "gemini": api_keys_payload.get("gemini") or DYNAMIC_CONFIG.get("gemini_api_key") or getattr(settings, "GEMINI_API_KEY", ""),
                "claude": api_keys_payload.get("claude") or DYNAMIC_CONFIG.get("claude_api_key") or getattr(settings, "ANTHROPIC_API_KEY", ""),
                "openai": api_keys_payload.get("openai") or DYNAMIC_CONFIG.get("openai_api_key") or getattr(settings, "OPENAI_API_KEY", ""),
            }

            # Filter extraction
            doc_filter = data.get("document_filter")
            norm_doc = None if doc_filter in (None, "", "ALL") else str(doc_filter).strip()

            if norm_doc and ("ar20" in norm_doc.lower()):
                self._send_json(400, {
                    "error": "ar20.pdf is quarantined due to missing OCR text layer and cannot be queried directly."
                })
                return

            filters = RetrievalFilter(document_id=norm_doc) if norm_doc else None

            # 4. Local Annual Reports Retrieval
            t0 = time.perf_counter()
            retrieval_response: Optional[RetrievalResponse] = None

            if method == "bm25":
                if not GLOBAL_STATE.bm25_index:
                    self._send_json(503, {"error": "BM25 index not loaded."})
                    return
                retrieval_response = GLOBAL_STATE.bm25_index.search(query=search_query, top_k=top_k, filters=filters)
            elif method == "semantic":
                if not GLOBAL_STATE.semantic_index or not GLOBAL_STATE.semantic_index.exists():
                    self._send_json(503, {"error": "Semantic index not loaded."})
                    return
                retrieval_response = GLOBAL_STATE.semantic_index.search(query=search_query, top_k=top_k, filters=filters)
            else:  # hybrid_rrf
                if not GLOBAL_STATE.hybrid_retriever:
                    self._send_json(503, {"error": "Hybrid retriever not loaded."})
                    return
                retrieval_response = GLOBAL_STATE.hybrid_retriever.search(query=search_query, top_k=top_k, filters=filters)

            retrieval_latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)

            evidence_items = []
            for item in retrieval_response.results:
                evidence_items.append({
                    "rank": item.rank,
                    "evidence_index": item.rank,
                    "chunk_id": item.chunk_id,
                    "document_id": item.document_id,
                    "source_filename": item.source_filename,
                    "fiscal_year": item.fiscal_year,
                    "section_title": item.section_title,
                    "physical_page": item.physical_page,
                    "printed_page": item.printed_page,
                    "citation_label": item.citation_label,
                    "content": item.content,
                    "score": item.score,
                    "bm25_score": item.bm25_score,
                    "semantic_score": item.semantic_score,
                    "rrf_score": item.rrf_score,
                    "is_web": False,
                })

            used_web_search = False
            web_results = []
            answer_payload = None

            # 5. Live Corporate Inquiry Detection & Web Fallback
            local_evidence_valid = (not retrieval_response.is_abstention) and (len(retrieval_response.results) > 0)
            live_public_keywords = ["job", "career", "apply", "recruitment", "vacancy", "opening", "hire", "head office", "registered office", "contact", "phone", "helpline", "telephone", "mobile", "number", "email", "address", "website", "portal", "toll free", "cmd", "managing director", "complaint", "grievance", "shikayat", "problem", "issue", "dispute", "redressal", "consumer", "ombudsman", "action", "haryana", "gurgaon", "chandigarh", "delhi", "branch"]
            is_live_public_query = any(kw in search_query.lower() for kw in live_public_keywords)

            # Prioritize official web retrieval for live corporate inquiries
            if is_live_public_query and enable_web:
                logger.info("Query '%s' detected as live corporate inquiry. Prioritizing official web retrieval.", search_query)
                tavily_agent = TavilySearchAgent(api_key=merged_keys["tavily"])
                web_res = tavily_agent.search(query=search_query, max_results=top_k)
                if web_res.get("success") and web_res.get("evidence"):
                    used_web_search = True
                    web_results = web_res["evidence"]
                    evidence_items = web_results
                    if generate_answer:
                        answer_payload = LLMManager.generate(
                            query=query,
                            evidence_items=web_results,
                            provider=provider,
                            api_keys=merged_keys,
                            max_new_tokens=max_new_tokens,
                            temperature=temperature,
                            is_web=True,
                            web_direct_answer=web_res.get("tavily_answer"),
                            conversation_history=[{"role": m.role, "content": m.content} for m in active_turns],
                            rolling_summary=rolling_summary,
                            language=lang,
                            emotional_context=emotional_context,
                        )

            # Local evidence answer generation
            if not used_web_search:
                if local_evidence_valid and generate_answer:
                    answer_payload = LLMManager.generate(
                        query=query,
                        evidence_items=retrieval_response.results,
                        provider=provider,
                        api_keys=merged_keys,
                        max_new_tokens=max_new_tokens,
                        temperature=temperature,
                        is_web=False,
                        conversation_history=[{"role": m.role, "content": m.content} for m in active_turns],
                        rolling_summary=rolling_summary,
                        language=lang,
                        emotional_context=emotional_context,
                    )

                # Fallback to Web if local retrieval abstained or produced refusal
                local_insufficient = (
                    (not local_evidence_valid)
                    or (answer_payload and answer_payload.get("is_refusal"))
                    or (answer_payload and "sufficient information" in answer_payload.get("clean_answer", "").lower())
                )

                if local_insufficient and enable_web:
                    logger.info("Local retrieval insufficient for '%s'. Falling back to Web Agent.", search_query)
                    tavily_agent = TavilySearchAgent(api_key=merged_keys["tavily"])
                    web_res = tavily_agent.search(query=search_query, max_results=top_k)
                    if web_res.get("success") and web_res.get("evidence"):
                        used_web_search = True
                        web_results = web_res["evidence"]
                        evidence_items = web_results
                        if generate_answer:
                            answer_payload = LLMManager.generate(
                                query=query,
                                evidence_items=web_results,
                                provider=provider,
                                api_keys=merged_keys,
                                max_new_tokens=max_new_tokens,
                                temperature=temperature,
                                is_web=True,
                                web_direct_answer=web_res.get("tavily_answer"),
                                conversation_history=[{"role": m.role, "content": m.content} for m in active_turns],
                                rolling_summary=rolling_summary,
                                language=lang,
                                emotional_context=emotional_context,
                            )

            # Refusal fallback if both branches yielded no groundable results
            if generate_answer and not answer_payload:
                if emotional_context.get("is_complaint"):
                    if lang == "hinglish":
                        abstain_msg = (
                            "Main samajh sakta hoon ki aapko HUDCO sambandhit shikayat ya samasya ka samna karna pada hai, aur iske liye khed hai. "
                            "Aap apni shikayat seedhe HUDCO ke Grievance Redressal Officer (HUDCO Bhawan, Core 7-A, India Habitat Centre, Lodhi Road, New Delhi – 110003, Phone: 011-24649610) "
                            "ya Bharat Sarkar ke official CPGRAMS portal https://pgportal.gov.in par darj kar sakte hain."
                        )
                    else:
                        abstain_msg = (
                            "I understand that you have experienced an issue or grievance with HUDCO, and I apologize for the inconvenience. "
                            "To lodge a formal complaint, you can contact the HUDCO Grievance Redressal Officer at HUDCO Bhawan, Core 7-A, India Habitat Centre, Lodhi Road, New Delhi – 110003 (Phone: 011-24649610), "
                            "or submit your grievance online through the Government's CPGRAMS portal at https://pgportal.gov.in."
                        )
                elif lang == "hinglish":
                    abstain_msg = (
                        "Mujhe HUDCO ke verified annual reports ya official web records par is baare mein poori jaankari nahi mili. "
                        "Official jaankari ke liye aap HUDCO ki website https://www.hudco.org.in par dekh sakte hain ya apna prashn thoda spasht kar sakte hain."
                    )
                else:
                    abstain_msg = (
                        "I could not find verified supporting information in HUDCO's annual reports or official web sources regarding this query. "
                        "For official inquiries, please check the HUDCO corporate portal at https://www.hudco.org.in or specify your question."
                    )
                answer_payload = {
                    "status": "abstained",
                    "answer": abstain_msg,
                    "clean_answer": abstain_msg,
                    "is_refusal": True,
                    "cited_chunk_ids": [],
                    "evidence_truncated": False,
                    "generation_time_ms": 0.0,
                    "provider": provider,
                    "device": "offline",
                    "citation_validation": {
                        "is_valid": True,
                        "has_citations": False,
                        "verification_status": "ABSTAINED_NO_GROUNDING",
                    }
                }

            if not answer_payload:
                answer_payload = {
                    "status": "retrieval_only",
                    "answer": "",
                    "clean_answer": "",
                    "is_refusal": False,
                    "cited_chunk_ids": [],
                    "evidence_truncated": False,
                    "generation_time_ms": 0.0,
                    "provider": provider,
                    "device": "offline",
                }

            # 6. Save Turn to Persistent Storage
            clean_ans = answer_payload.get("clean_answer") or answer_payload.get("answer") or ""
            clean_ans = strip_citation_markers(clean_ans)
            answer_payload["clean_answer"] = clean_ans
            answer_payload["answer"] = clean_ans

            saved_evidence = []
            for i, it in enumerate(evidence_items):
                saved_evidence.append({
                    "chunk_id": it.get("chunk_id", f"ev_{i}"),
                    "document_id": it.get("document_id", "DOC"),
                    "title": it.get("title") or it.get("section_title") or f"Evidence [{i+1}]",
                    "section_title": it.get("section_title") or it.get("title"),
                    "source_filename": it.get("source_filename"),
                    "fiscal_year": it.get("fiscal_year"),
                    "physical_page": it.get("physical_page"),
                    "printed_page": it.get("printed_page"),
                    "content": (it.get("content") or it.get("snippet") or "")[:1200],
                    "url": it.get("url"),
                    "domain": it.get("domain"),
                    "is_web": bool(it.get("is_web", False)),
                })

            if generate_answer:
                user_msg = ChatMessage(role="user", content=query, token_count=estimate_tokens(query))
                bot_msg = ChatMessage(
                    role="assistant",
                    content=clean_ans,
                    evidence_payload=saved_evidence,
                    token_count=estimate_tokens(clean_ans),
                    provider_used=provider,
                    model_name=answer_payload.get("model_name"),
                )
                CONV_STORAGE.save_message(user_id=user_id, session_id=session_id, message=user_msg)
                CONV_STORAGE.save_message(user_id=user_id, session_id=session_id, message=bot_msg)

                # Auto-title on first turn
                if len(session.messages) <= 2:
                    title_suggestion = query[:36] + ("..." if len(query) > 36 else "")
                    CONV_STORAGE.rename_conversation(user_id=user_id, session_id=session_id, new_title=title_suggestion)

            # 7. Context Usage Telemetry Calculation
            context_telemetry = calculate_context_telemetry(
                system_prompt="HUDCO Bot Enterprise Assistant",
                rolling_summary=rolling_summary,
                active_turns=[{"role": m.role, "content": m.content} for m in active_turns] + [{"role": "user", "content": query}],
                evidence_items=evidence_items,
                user_query=query,
                max_budget=context_budget,
                reserved_output_tokens=max_new_tokens
            )

            total_elapsed_ms = round(
                retrieval_latency_ms + (answer_payload.get("generation_time_ms", 0.0) if answer_payload else 0.0),
                2
            )

            is_rate_limited = bool(answer_payload and answer_payload.get("is_rate_limited"))
            rate_limit_info = {}
            if is_rate_limited:
                status_str = "rate_limited"
                rate_limit_info = {
                    "is_rate_limited": True,
                    "provider": answer_payload.get("provider", provider),
                    "cooldown_seconds": answer_payload.get("cooldown_seconds", 60),
                    "error_message": answer_payload.get("error_message", "API rate limit reached."),
                }
            else:
                status_str = "web_evidence_available" if used_web_search else ("evidence_available" if local_evidence_valid else "abstained")

            retrieval_method_str = "web_search" if used_web_search else retrieval_response.retrieval_method

            result = {
                "query": query,
                "rewritten_query": search_query if search_query != query else None,
                "session_id": session_id,
                "retrieval_method": retrieval_method_str,
                "status": status_str,
                "is_rate_limited": is_rate_limited,
                "rate_limit_info": rate_limit_info,
                "is_abstention": not (local_evidence_valid or used_web_search),
                "is_conversational": False,
                "used_web_search": used_web_search,
                "abstention_reason": None if (local_evidence_valid or used_web_search) else retrieval_response.abstention_reason,
                "total_results": len(evidence_items),
                "results": evidence_items,
                "retrieval_latency_ms": retrieval_latency_ms,
                "total_query_latency_ms": total_elapsed_ms,
                "answer": answer_payload,
                "context_telemetry": context_telemetry.dict(),
                "live_gpu_telemetry": get_gpu_telemetry(),
            }

            self._send_json(200, result)

        except Exception as e:
            logger.error("Error handling query: %s", e, exc_info=True)
            self._send_json(500, {"error": f"Server error: {str(e)}"})


def run_server(host: Optional[str] = None, port: Optional[int] = None) -> None:
    """Initializes retrieval pipeline state, storage, and starts HTTP server."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logger.info("Initializing HUDCO Retrieval Pipeline, Context Storage & Model Services...")
    GLOBAL_STATE.initialize()

    # Preload Local LLM asynchronously on GPU only if enabled and not running on Render
    if get_qwen_service().enabled and not os.environ.get("RENDER"):
        threading.Thread(target=get_qwen_service().preload, daemon=True, name="qwen-background-preload").start()

    effective_port = int(port or os.environ.get("PORT", 8501))
    effective_host = host or ("0.0.0.0" if (os.environ.get("RENDER") or os.environ.get("HOST") == "0.0.0.0") else "127.0.0.1")

    server_address = (effective_host, effective_port)
    httpd = ThreadingHTTPServer(server_address, HUDCOUIRequestHandler)
    is_pg = getattr(CONV_STORAGE, "is_postgres", False)
    storage_desc = "Neon Serverless PostgreSQL" if is_pg else f"File / Persistent Disk ({getattr(CONV_STORAGE, 'base_dir', 'context')})"
    print("\n=======================================================")
    print(" HUDCO Bot — Conversational AI & Diagnostics Server")
    print(f" URL: http://{effective_host}:{effective_port}/")
    print(f" Storage Subsystem: {storage_desc}")
    print(" Authentication: Argon2id + Secure HttpOnly Cookies")
    print(" Press Ctrl+C to stop.")
    print("=======================================================\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down HUDCO server...")
        httpd.server_close()
        get_qwen_service().close()
        logger.info("Server shutdown complete.")


if __name__ == "__main__":
    run_server()
