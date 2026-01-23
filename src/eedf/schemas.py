"""Pydantic models for structured output."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class DocumentRecord(BaseModel):
    """Database document record."""

    id: int
    filename: str
    file_type: str
    upload_date: datetime
    raw_text: Optional[str] = None
    status: str = "pending"


class DocumentWithExtraction(BaseModel):
    """Document with its extracted data."""

    document: DocumentRecord
    extraction: Optional[dict[str, Any]] = None


class UploadResponse(BaseModel):
    """Response from document upload."""

    document_id: int
    filename: str
    status: str
    message: str


class SQLQueryRequest(BaseModel):
    """SQL query request."""

    query: str


class SQLQueryResponse(BaseModel):
    """SQL query response."""

    columns: list[str]
    rows: list[list]
    row_count: int
