"""
Pydantic request/response models for the MedRAG API. Explicit models
(rather than raw dicts) give automatic request validation and power
FastAPI's auto-generated /docs UI.
"""

from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from uuid import UUID


class CreateSessionRequest(BaseModel):
    title: Optional[str] = None


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value):
        return value.lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


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

    @field_validator("session_id")
    @classmethod
    def valid_session_id(cls, value: str) -> str:
        return str(UUID(value))

    @field_validator("message")
    @classmethod
    def nonempty_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message must not be blank")
        return value


class SourceTable(BaseModel):
    rows: List[List[str]]
    page_number: Optional[int] = None
    part: Optional[int] = None


class SourceImage(BaseModel):
    filename: str
    page_number: Optional[int] = None
    figure_number: Optional[str] = None
    image_type: str = "embedded"
    caption: Optional[str] = None


class CitationOut(BaseModel):
    marker: int
    chunk_id: str
    source: str
    source_id: Optional[str] = None
    title: str
    url: Optional[str] = None
    linked_images: list = []
    table: Optional[SourceTable] = None
    images: List[SourceImage] = Field(default_factory=list)


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
    
class SessionSummary(BaseModel):
    session_id: UUID
    title: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    sessions: list[SessionSummary]
