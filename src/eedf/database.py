"""SQLite models and operations."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import aiosqlite

from .config import DATABASE_PATH
from .schemas import (
    Clause,
    ContractExtraction,
    ContractRecord,
    DocumentRecord,
    DocumentWithContract,
    Obligation,
    Party,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_text TEXT,
    status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    contract_type TEXT,
    parties JSON,
    effective_date TEXT,
    termination_date TEXT,
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS obligations (
    id INTEGER PRIMARY KEY,
    contract_id INTEGER REFERENCES contracts(id),
    party TEXT,
    description TEXT,
    due_date TEXT,
    status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS clauses (
    id INTEGER PRIMARY KEY,
    contract_id INTEGER REFERENCES contracts(id),
    clause_type TEXT,
    clause_text TEXT,
    section_reference TEXT
);
"""


def init_db() -> None:
    """Initialize the database with schema."""
    DATABASE_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


async def get_db() -> aiosqlite.Connection:
    """Get async database connection."""
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def create_document(filename: str, file_type: str, raw_text: str) -> int:
    """Create a new document record."""
    async with await get_db() as db:
        cursor = await db.execute(
            "INSERT INTO documents (filename, file_type, raw_text, status) VALUES (?, ?, ?, ?)",
            (filename, file_type, raw_text, "pending"),
        )
        await db.commit()
        return cursor.lastrowid


async def update_document_status(document_id: int, status: str) -> None:
    """Update document processing status."""
    async with await get_db() as db:
        await db.execute(
            "UPDATE documents SET status = ? WHERE id = ?",
            (status, document_id),
        )
        await db.commit()


async def get_document(document_id: int) -> Optional[DocumentRecord]:
    """Get a document by ID."""
    async with await get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        )
        row = await cursor.fetchone()
        if row:
            return DocumentRecord(
                id=row["id"],
                filename=row["filename"],
                file_type=row["file_type"],
                upload_date=datetime.fromisoformat(row["upload_date"]),
                raw_text=row["raw_text"],
                status=row["status"],
            )
        return None


async def get_all_documents() -> list[DocumentRecord]:
    """Get all documents."""
    async with await get_db() as db:
        cursor = await db.execute(
            "SELECT * FROM documents ORDER BY upload_date DESC"
        )
        rows = await cursor.fetchall()
        return [
            DocumentRecord(
                id=row["id"],
                filename=row["filename"],
                file_type=row["file_type"],
                upload_date=datetime.fromisoformat(row["upload_date"]),
                raw_text=row["raw_text"],
                status=row["status"],
            )
            for row in rows
        ]


async def save_extraction(document_id: int, extraction: ContractExtraction) -> int:
    """Save extracted contract data to database."""
    async with await get_db() as db:
        # Save contract
        parties_json = json.dumps([p.model_dump() for p in extraction.parties])
        cursor = await db.execute(
            """INSERT INTO contracts
               (document_id, contract_type, parties, effective_date, termination_date)
               VALUES (?, ?, ?, ?, ?)""",
            (
                document_id,
                extraction.contract_type,
                parties_json,
                extraction.effective_date,
                extraction.termination_date,
            ),
        )
        contract_id = cursor.lastrowid

        # Save obligations
        for obligation in extraction.obligations:
            await db.execute(
                """INSERT INTO obligations
                   (contract_id, party, description, due_date, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    contract_id,
                    obligation.party,
                    obligation.description,
                    obligation.due_date,
                    obligation.status,
                ),
            )

        # Save clauses
        for clause in extraction.clauses:
            await db.execute(
                """INSERT INTO clauses
                   (contract_id, clause_type, clause_text, section_reference)
                   VALUES (?, ?, ?, ?)""",
                (
                    contract_id,
                    clause.clause_type,
                    clause.clause_text,
                    clause.section_reference,
                ),
            )

        await db.commit()
        return contract_id


async def get_document_with_contract(document_id: int) -> Optional[DocumentWithContract]:
    """Get document with all extracted contract data."""
    async with await get_db() as db:
        # Get document
        cursor = await db.execute(
            "SELECT * FROM documents WHERE id = ?", (document_id,)
        )
        doc_row = await cursor.fetchone()
        if not doc_row:
            return None

        document = DocumentRecord(
            id=doc_row["id"],
            filename=doc_row["filename"],
            file_type=doc_row["file_type"],
            upload_date=datetime.fromisoformat(doc_row["upload_date"]),
            raw_text=doc_row["raw_text"],
            status=doc_row["status"],
        )

        # Get contract
        cursor = await db.execute(
            "SELECT * FROM contracts WHERE document_id = ?", (document_id,)
        )
        contract_row = await cursor.fetchone()

        contract = None
        obligations = []
        clauses = []

        if contract_row:
            parties = [Party(**p) for p in json.loads(contract_row["parties"] or "[]")]
            contract = ContractRecord(
                id=contract_row["id"],
                document_id=contract_row["document_id"],
                contract_type=contract_row["contract_type"],
                parties=parties,
                effective_date=contract_row["effective_date"],
                termination_date=contract_row["termination_date"],
                extracted_at=datetime.fromisoformat(contract_row["extracted_at"]),
            )

            # Get obligations
            cursor = await db.execute(
                "SELECT * FROM obligations WHERE contract_id = ?", (contract.id,)
            )
            obl_rows = await cursor.fetchall()
            obligations = [
                Obligation(
                    party=row["party"],
                    description=row["description"],
                    due_date=row["due_date"],
                    status=row["status"],
                )
                for row in obl_rows
            ]

            # Get clauses
            cursor = await db.execute(
                "SELECT * FROM clauses WHERE contract_id = ?", (contract.id,)
            )
            clause_rows = await cursor.fetchall()
            clauses = [
                Clause(
                    clause_type=row["clause_type"],
                    clause_text=row["clause_text"],
                    section_reference=row["section_reference"],
                )
                for row in clause_rows
            ]

        return DocumentWithContract(
            document=document,
            contract=contract,
            obligations=obligations,
            clauses=clauses,
        )


async def execute_sql(query: str) -> tuple[list[str], list[list]]:
    """Execute a read-only SQL query and return results."""
    # Only allow SELECT statements
    query_lower = query.strip().lower()
    if not query_lower.startswith("select"):
        raise ValueError("Only SELECT queries are allowed")

    async with await get_db() as db:
        cursor = await db.execute(query)
        rows = await cursor.fetchall()

        if rows:
            columns = list(rows[0].keys())
            data = [list(row) for row in rows]
        else:
            columns = []
            data = []

        return columns, data
