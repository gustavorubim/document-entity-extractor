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


# Schema Designer API Models


class SchemaNestedFieldDefinition(BaseModel):
    """Simplified field definition for nested object fields (inside array items)."""

    name: str
    type: str
    description: Optional[str] = None


class SchemaFieldItem(BaseModel):
    """Nested item configuration for array fields."""

    type: str = "string"
    description: Optional[str] = None
    unique_by: Optional[list[str]] = None
    fields: Optional[list[SchemaNestedFieldDefinition]] = None


class SchemaFieldSqlColumn(BaseModel):
    """Column definition for SQL mapping."""

    name: str
    type: str = "TEXT"


class SchemaFieldSqlFk(BaseModel):
    """Foreign key definition for array fields."""

    column: str
    references: str


class SchemaFieldSql(BaseModel):
    """SQL mapping configuration for a field."""

    table: str
    column: Optional[str] = None
    type: Optional[str] = None
    columns: Optional[list[SchemaFieldSqlColumn]] = None
    fk: Optional[SchemaFieldSqlFk] = None


class SchemaFieldMerge(BaseModel):
    """Merge strategy configuration."""

    strategy: str = "first_non_empty"
    key_fields: Optional[list[str]] = None


class SchemaFieldDefinition(BaseModel):
    """Full field definition."""

    name: str
    type: str
    description: Optional[str] = None
    sql: SchemaFieldSql
    merge: Optional[SchemaFieldMerge] = None
    items: Optional[SchemaFieldItem] = None


class SchemaPrompt(BaseModel):
    """Prompt configuration."""

    system: str = "You are a document analysis expert."
    instructions: str = "Return ONLY valid JSON, no other text."


class SchemaDocumentFk(BaseModel):
    """Document foreign key configuration."""

    column: str = "document_id"
    references: str = "documents(id)"


class SchemaExtraColumn(BaseModel):
    """Extra column for root table."""

    name: str
    type: str = "TEXT"
    default: Optional[str] = None


class SchemaRoot(BaseModel):
    """Root table configuration."""

    table: str
    primary_key: str = "id"
    document_fk: SchemaDocumentFk
    extra_columns: Optional[list[SchemaExtraColumn]] = None


class ExtractionSchema(BaseModel):
    """Complete extraction schema."""

    name: str
    version: int = 1
    description: Optional[str] = None
    prompt: Optional[SchemaPrompt] = None
    root: SchemaRoot
    fields: list[SchemaFieldDefinition]


class SchemaSaveRequest(BaseModel):
    """Request to save a schema."""

    schema_data: ExtractionSchema


class SchemaValidationError(BaseModel):
    """A single validation error or warning."""

    path: str
    message: str
    severity: str = "error"  # "error" or "warning"


class SchemaValidationResponse(BaseModel):
    """Response from schema validation."""

    valid: bool
    errors: list[SchemaValidationError] = []
    warnings: list[SchemaValidationError] = []


class SchemaSaveResponse(BaseModel):
    """Response from schema save."""

    success: bool
    message: str
    validation: SchemaValidationResponse
