"""Pydantic models for structured output."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class Party(BaseModel):
    """A party to the contract."""
    name: str
    role: str = ""  # e.g., "Licensor", "Employee", "Landlord"
    address: str = ""


class Obligation(BaseModel):
    """An obligation from the contract."""
    party: str
    description: str
    due_date: Optional[str] = None
    status: str = "active"


class Clause(BaseModel):
    """A clause from the contract."""
    clause_type: str  # e.g., 'termination', 'confidentiality', 'liability'
    clause_text: str
    section_reference: str = ""


class ContractExtraction(BaseModel):
    """Extracted contract data."""
    contract_type: str = ""
    parties: list[Party] = Field(default_factory=list)
    effective_date: Optional[str] = None
    termination_date: Optional[str] = None
    key_terms: list[str] = Field(default_factory=list)
    obligations: list[Obligation] = Field(default_factory=list)
    clauses: list[Clause] = Field(default_factory=list)
    signatures: list[str] = Field(default_factory=list)


class DocumentRecord(BaseModel):
    """Database document record."""
    id: int
    filename: str
    file_type: str
    upload_date: datetime
    raw_text: Optional[str] = None
    status: str = "pending"


class ContractRecord(BaseModel):
    """Database contract record."""
    id: int
    document_id: int
    contract_type: Optional[str] = None
    parties: list[Party] = Field(default_factory=list)
    effective_date: Optional[str] = None
    termination_date: Optional[str] = None
    extracted_at: datetime


class DocumentWithContract(BaseModel):
    """Document with its extracted contract data."""
    document: DocumentRecord
    contract: Optional[ContractRecord] = None
    obligations: list[Obligation] = Field(default_factory=list)
    clauses: list[Clause] = Field(default_factory=list)


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
