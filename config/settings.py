"""
Global Settings and Configuration for HUDCO Enterprise Conversational AI Pipeline.
Uses Pydantic Settings to manage environment variables and directory paths.
"""

from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

# Base Directory of Project Root
BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    """Application and Pipeline Configuration."""

    # Project Metadata
    PROJECT_NAME: str = "HUDCO Enterprise Conversational AI"
    ENVIRONMENT: str = Field(default="development", description="Runtime environment")
    LOG_LEVEL: str = Field(default="INFO", description="Logging level")

    # Storage Paths
    ROOT_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    RAW_DATA_DIR: Path = BASE_DIR / "data" / "raw"
    ANNUAL_REPORTS_DIR: Path = BASE_DIR / "data" / "raw" / "annual_reports"
    CIRCULARS_DIR: Path = BASE_DIR / "data" / "raw" / "circulars"
    WEB_PAGES_DIR: Path = BASE_DIR / "data" / "raw" / "web_pages"
    INTERMEDIATE_DIR: Path = BASE_DIR / "data" / "intermediate" / "sections"
    INGESTION_RUNS_DIR: Path = BASE_DIR / "data" / "intermediate" / "ingestion_runs"
    OUTPUT_CHUNKS_DIR: Path = BASE_DIR / "data" / "output_chunks"
    CHROMA_PERSIST_DIR: Path = BASE_DIR / "data" / "chroma_db"
    VECTOR_INDEX_DIR: Path = BASE_DIR / "data" / "vector_index"
    DOCUMENT_REGISTRY_JSON: Path = BASE_DIR / "data" / "document_registry.json"

    # Ingestion & Downloader Configuration
    DOWNLOAD_CHUNK_SIZE_BYTES: int = 65536  # 64 KB streaming buffer
    DOWNLOAD_TIMEOUT_SECONDS: int = 60
    DOWNLOAD_MAX_RETRIES: int = 3

    # PDF & TOC Segmentation Parameters
    TOC_SCAN_MAX_PAGES: int = 35           # Max pages to scan from start for TOC
    TOC_MIN_VALID_ENTRIES: int = 5         # Minimum valid outline/TOC entries required
    MAX_PDF_CHUNK_PAGES: int = 25          # Fallback window chunk size

    # Text & Chunking Parameters
    MIN_CHUNK_CHAR_LEN: int = 150
    MAX_CHUNK_CHAR_LEN: int = 2500

    # AI & Embedding Providers
    GEMINI_API_KEY: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    ANTHROPIC_API_KEY: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")
    OPENAI_API_KEY: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    TAVILY_API_KEY: Optional[str] = Field(default=None, alias="TAVILY_API_KEY")
    GROQ_API_KEY: Optional[str] = Field(default=None, alias="GROQ_API_KEY")
    DEFAULT_LLM_PROVIDER: str = Field(default="gemini", alias="DEFAULT_LLM_PROVIDER")
    EMBEDDING_MODEL_NAME: str = "sentence-transformers/all-MiniLM-L6-v2"
    LLM_MODEL_NAME: str = "gemini-2.5-flash"

    # Database Configuration (PostgreSQL / SQLite fallback for later stages)
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://hudco_admin:hudco_pass@localhost:5432/hudco_db",
        description="Async connection string for PostgreSQL knowledge registry"
    )

    # Redis Session & Rate Limiting
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for session memory and rate limiting"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def init_directories(self) -> None:
        """Ensure all required directories exist."""
        for path in [
            self.RAW_DATA_DIR,
            self.ANNUAL_REPORTS_DIR,
            self.CIRCULARS_DIR,
            self.WEB_PAGES_DIR,
            self.INTERMEDIATE_DIR,
            self.INGESTION_RUNS_DIR,
            self.OUTPUT_CHUNKS_DIR,
            self.CHROMA_PERSIST_DIR,
            self.VECTOR_INDEX_DIR,
        ]:
            path.mkdir(parents=True, exist_ok=True)


# Singleton Instance
settings = Settings()
settings.init_directories()
