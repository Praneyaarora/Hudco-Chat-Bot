"""
Relational Database Models for PostgreSQL / SQLAlchemy.
Maintains the master document registry, SHA-256 deduplication state, and exact key-value facts.
"""

from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, Boolean, Text, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class DocumentRegistry(Base):
    """Catalogues raw parent documents (Annual Reports, Circulars, Web Pages)."""
    __tablename__ = "document_registry"

    document_id = Column(String(100), primary_key=True)
    title = Column(String(255), nullable=False)
    document_type = Column(String(50), nullable=False)  # annual_report, circular, faq, web_page
    fiscal_year = Column(String(20), nullable=True)
    source_url = Column(Text, nullable=True)
    sha256 = Column(String(64), nullable=False, unique=True)
    total_pages = Column(Integer, nullable=True)
    authority_tier = Column(Integer, default=1)
    is_latest = Column(Boolean, default=True)
    status = Column(String(30), default="PENDING")  # PENDING, INGESTED, INDEXED, ERROR
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChunkRegistry(Base):
    """Maps every atomic chunk in ChromaDB back to relational metadata and full content."""
    __tablename__ = "chunk_registry"

    chunk_id = Column(String(150), primary_key=True)
    document_id = Column(String(100), nullable=False)
    primary_intent = Column(String(50), nullable=False)
    section_title = Column(String(255), nullable=True)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)
    content_payload = Column(JSON, nullable=False)
    sha256 = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class OfficeDirectory(Base):
    """Structured directory for HUDCO Regional and Head Offices."""
    __tablename__ = "office_directory"

    office_id = Column(String(50), primary_key=True)
    office_type = Column(String(50), nullable=False)  # HEAD_OFFICE, REGIONAL_OFFICE, BRANCH
    city = Column(String(100), nullable=False)
    state = Column(String(100), nullable=False)
    address = Column(Text, nullable=False)
    contact_person = Column(String(150), nullable=True)
    email = Column(String(150), nullable=True)
    phone = Column(String(100), nullable=True)
