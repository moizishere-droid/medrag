"""
Pydantic request/response models for the MedRAG API. Explicit models
(rather than raw dicts) give automatic request validation and power
FastAPI's auto-generated /docs UI.
"""

from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel


class CreateSessionRequest(BaseModel):
    title: Optional[str] = None
    user_id: Optional[str] = None


class CreateSessionResponse(BaseModel):
    session_id: str


class MessageOut(BaseModel):
    message_id: str
    role: str
    content: str
    citations: Optional[list] = None
    created_at: datetime


class SessionHistoryResponse(BaseModel):
    session_id: str
    messages: List[MessageOut]


class ChatRequest(BaseModel):
    session_id: str
    message: str


class CitationOut(BaseModel):
    marker: int
    chunk_id: str
    source: str
    title: str
    url: Optional[str] = None
    linked_images: list = []


class ChatResponse(BaseModel):
    answer: str
    citations: List[CitationOut]


class DependencyStatus(BaseModel):
    qdrant: str
    neo4j: str
    postgres: str


class HealthResponse(BaseModel):
    status: str
    dependencies: DependencyStatus


class UploadDocumentResponse(BaseModel):
    document_id: str
    filename: str
    chunk_count: int