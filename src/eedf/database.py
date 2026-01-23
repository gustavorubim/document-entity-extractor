"""SQLite models and operations."""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime
from typing import Any, Optional

import aiosqlite

from .config import DATABASE_PATH
from .schema_loader import get_active_schema, schema_hash
from .schemas import DocumentRecord, DocumentWithExtraction

logger = logging.getLogger(__name__)

# Regex for valid SQL identifiers (table/column names)
# Allows alphanumeric characters and underscores, must start with letter or underscore
VALID_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def validate_identifier(name: str, identifier_type: str = "identifier") -> str:
    """Validate and return a safe SQL identifier.

    Args:
        name: The identifier to validate
        identifier_type: Type of identifier for error messages (e.g., "table", "column")

    Returns:
        The validated identifier

    Raises:
        ValueError: If the identifier is invalid
    """
    if not name or not isinstance(name, str):
        raise ValueError(f"Invalid {identifier_type}: must be a non-empty string")

    if not VALID_IDENTIFIER_PATTERN.match(name):
        raise ValueError(
            f"Invalid {identifier_type} '{name}': must contain only alphanumeric "
            "characters and underscores, and start with a letter or underscore"
        )

    # Additional check for SQL reserved words that could be problematic
    reserved_words = {"select", "insert", "update", "delete", "drop", "create",
                      "alter", "table", "from", "where", "and", "or", "union"}
    if name.lower() in reserved_words:
        raise ValueError(f"Invalid {identifier_type} '{name}': cannot use SQL reserved word")

    return name

DOCUMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_text TEXT,
    status TEXT DEFAULT 'pending'
);
"""

SCHEMA_META_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    version INTEGER NOT NULL,
    hash TEXT NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db() -> None:
    """Initialize the database with schema."""
    DATABASE_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.executescript(DOCUMENTS_SCHEMA)
    conn.executescript(SCHEMA_META_SCHEMA)

    schema = get_active_schema()
    apply_schema(conn, schema)

    conn.commit()
    conn.close()


from contextlib import asynccontextmanager


@asynccontextmanager
async def get_db():
    """Get async database connection as context manager."""
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    try:
        yield db
    finally:
        await db.close()


def apply_schema(conn: sqlite3.Connection, schema: dict[str, Any]) -> None:
    """Create or update tables based on the active schema."""
    tables = build_table_specs(schema)
    for table_name, columns in tables.items():
        ensure_table(conn, table_name, columns)

    record_schema_meta(conn, schema)


def build_table_specs(schema: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Build table specs for root and child tables from schema."""
    tables: dict[str, list[dict[str, Any]]] = {}
    root = schema["root"]
    root_table = root["table"]
    root_columns: list[dict[str, Any]] = []

    root_pk = root.get("primary_key", "id")
    _add_column(root_columns, {"name": root_pk, "type": "INTEGER", "constraints": "PRIMARY KEY"})

    doc_fk = root["document_fk"]
    _add_column(
        root_columns,
        {
            "name": doc_fk["column"],
            "type": "INTEGER",
            "constraints": f"REFERENCES {doc_fk['references']}",
        },
    )

    for column in root.get("extra_columns", []):
        _add_column(root_columns, _normalize_column(column))

    for field in schema["fields"]:
        field_type = field["type"]
        sql = field["sql"]
        if field_type == "array":
            table_name = sql["table"]
            table_columns = tables.get(table_name, [])
            if not table_columns:
                _add_column(table_columns, {"name": "id", "type": "INTEGER", "constraints": "PRIMARY KEY"})
                _add_column(
                    table_columns,
                    {
                        "name": sql["fk"]["column"],
                        "type": "INTEGER",
                        "constraints": f"REFERENCES {sql['fk']['references']}",
                    },
                )
            for column in sql.get("columns", []):
                _add_column(table_columns, _normalize_column(column))
            tables[table_name] = table_columns
        else:
            if sql["table"] == root_table:
                _add_column(root_columns, _normalize_column({"name": sql["column"], "type": sql.get("type", "TEXT")}))

    tables[root_table] = root_columns
    return tables


def _normalize_column(column: dict[str, Any]) -> dict[str, Any]:
    column_type = column.get("type", "TEXT")
    normalized = {
        "name": column["name"],
        "type": column_type.upper(),
    }
    if "default" in column:
        normalized["default"] = column["default"]
    if "constraints" in column:
        normalized["constraints"] = column["constraints"]
    return normalized


def _add_column(columns: list[dict[str, Any]], column: dict[str, Any]) -> None:
    existing = {col["name"] for col in columns}
    if column["name"] not in existing:
        columns.append(column)


def ensure_table(conn: sqlite3.Connection, table_name: str, columns: list[dict[str, Any]]) -> None:
    """Ensure table exists and has required columns."""
    # Validate table name to prevent SQL injection
    safe_table = validate_identifier(table_name, "table name")

    # Validate all column names
    for col in columns:
        validate_identifier(col["name"], "column name")

    if not table_exists(conn, safe_table):
        column_sql = ", ".join(_column_sql(col) for col in columns)
        conn.execute(f"CREATE TABLE IF NOT EXISTS {safe_table} ({column_sql});")
        return

    existing_columns = get_table_columns(conn, safe_table)
    for column in columns:
        if column["name"] in existing_columns:
            continue
        conn.execute(f"ALTER TABLE {safe_table} ADD COLUMN {_column_sql(column)};")


def _column_sql(column: dict[str, Any]) -> str:
    # Validate column name to prevent SQL injection
    safe_name = validate_identifier(column["name"], "column name")
    col_type = column.get("type", "TEXT").upper()

    # Validate column type (only allow known SQL types)
    valid_types = {"TEXT", "INTEGER", "REAL", "BLOB", "NUMERIC", "TIMESTAMP", "BOOLEAN", "NUMBER"}
    if col_type not in valid_types:
        raise ValueError(f"Invalid column type '{col_type}'")

    parts = [safe_name, col_type]
    if column.get("constraints"):
        # Validate constraints - only allow safe patterns
        constraints = column["constraints"]
        if not _is_safe_constraint(constraints):
            raise ValueError(f"Invalid column constraints: {constraints}")
        parts.append(constraints)
    if "default" in column:
        default_val = column["default"]
        # Validate default value - only allow safe patterns
        if not _is_safe_default(default_val):
            raise ValueError(f"Invalid default value: {default_val}")
        parts.append(f"DEFAULT {default_val}")
    return " ".join(parts)


def _is_safe_constraint(constraint: str) -> bool:
    """Check if a constraint is safe to use in SQL."""
    if not constraint or not isinstance(constraint, str):
        return False
    # Allow common safe constraint patterns
    safe_patterns = [
        r"^PRIMARY KEY$",
        r"^NOT NULL$",
        r"^UNIQUE$",
        r"^REFERENCES [a-zA-Z_][a-zA-Z0-9_]*\([a-zA-Z_][a-zA-Z0-9_]*\)$",
    ]
    constraint_upper = constraint.strip().upper()
    for pattern in safe_patterns:
        if re.match(pattern, constraint_upper, re.IGNORECASE):
            return True
    return False


def _is_safe_default(default: Any) -> bool:
    """Check if a default value is safe to use in SQL."""
    if default is None:
        return True
    if isinstance(default, (int, float)):
        return True
    if isinstance(default, str):
        # Allow common safe defaults
        safe_defaults = {"CURRENT_TIMESTAMP", "NULL", "0", "1", "''", '""'}
        return default.upper() in safe_defaults or default.isdigit()
    return False


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    # Using parameterized query - safe from injection
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def get_table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    # Validate table name before using in PRAGMA
    safe_table = validate_identifier(table_name, "table name")
    cursor = conn.execute(f"PRAGMA table_info({safe_table})")
    return {row[1] for row in cursor.fetchall()}


def record_schema_meta(conn: sqlite3.Connection, schema: dict[str, Any]) -> None:
    current_hash = schema_hash(schema)
    cursor = conn.execute(
        "SELECT hash FROM schema_meta ORDER BY applied_at DESC LIMIT 1"
    )
    row = cursor.fetchone()
    if row and row[0] == current_hash:
        return
    conn.execute(
        "INSERT INTO schema_meta (name, version, hash) VALUES (?, ?, ?)",
        (schema["name"], schema["version"], current_hash),
    )


async def create_document(filename: str, file_type: str, raw_text: str) -> int:
    """Create a new document record."""
    async with get_db() as db:
        cursor = await db.execute(
            "INSERT INTO documents (filename, file_type, raw_text, status) VALUES (?, ?, ?, ?)",
            (filename, file_type, raw_text, "pending"),
        )
        await db.commit()
        return cursor.lastrowid


async def update_document_status(document_id: int, status: str) -> None:
    """Update document processing status."""
    async with get_db() as db:
        await db.execute(
            "UPDATE documents SET status = ? WHERE id = ?",
            (status, document_id),
        )
        await db.commit()


async def get_document(document_id: int) -> Optional[DocumentRecord]:
    """Get a document by ID."""
    async with get_db() as db:
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
    async with get_db() as db:
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


async def save_extraction(
    document_id: int,
    extraction: dict[str, Any],
    schema: dict[str, Any],
) -> int:
    """Save extracted data to database based on schema."""
    root = schema["root"]
    root_table = validate_identifier(root["table"], "table name")
    doc_fk_column = validate_identifier(root["document_fk"]["column"], "column name")
    root_columns: list[str] = [doc_fk_column]
    root_values: list[Any] = [document_id]

    for field in schema["fields"]:
        if field["type"] == "array":
            continue
        sql = field["sql"]
        if sql["table"] != root["table"]:  # Compare with original value
            continue
        column = validate_identifier(sql["column"], "column name")
        if column in root_columns:
            continue
        root_columns.append(column)
        root_values.append(extraction.get(field["name"]))

    placeholders = ", ".join(["?"] * len(root_columns))
    columns_sql = ", ".join(root_columns)

    async with get_db() as db:
        try:
            cursor = await db.execute(
                f"INSERT INTO {root_table} ({columns_sql}) VALUES ({placeholders})",
                tuple(root_values),
            )
            root_id = cursor.lastrowid

            for field in schema["fields"]:
                if field["type"] != "array":
                    continue
                sql = field["sql"]
                table = validate_identifier(sql["table"], "table name")
                fk_column = validate_identifier(sql["fk"]["column"], "column name")
                column_defs = sql.get("columns", [])
                if not column_defs:
                    continue

                # Validate all column names upfront
                validated_col_names = [validate_identifier(col["name"], "column name") for col in column_defs]

                items = extraction.get(field["name"], []) or []
                for item in items:
                    row_columns = [fk_column] + validated_col_names
                    row_values: list[Any] = [root_id]

                    if field.get("items", {}).get("type") == "object" and isinstance(item, dict):
                        for col in column_defs:
                            row_values.append(item.get(col["name"]))
                    else:
                        row_values.append(item)
                        for _ in column_defs[1:]:
                            row_values.append(None)

                    placeholders = ", ".join(["?"] * len(row_columns))
                    columns_sql = ", ".join(row_columns)
                    await db.execute(
                        f"INSERT INTO {table} ({columns_sql}) VALUES ({placeholders})",
                        tuple(row_values),
                    )

            await db.commit()
            return root_id
        except Exception as e:
            await db.rollback()
            logger.error(f"Error saving extraction for document {document_id}: {e}")
            raise


async def get_document_with_extraction(
    document_id: int,
    schema: dict[str, Any],
) -> Optional[DocumentWithExtraction]:
    """Get document with extracted data based on schema."""
    async with get_db() as db:
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

        root = schema["root"]
        root_table = validate_identifier(root["table"], "table name")
        root_pk = validate_identifier(root.get("primary_key", "id"), "column name")
        doc_fk = validate_identifier(root["document_fk"]["column"], "column name")

        order_column = await _select_order_column(db, root_table)
        cursor = await db.execute(
            f"SELECT * FROM {root_table} WHERE {doc_fk} = ? ORDER BY {order_column} DESC LIMIT 1",
            (document_id,),
        )
        root_row = await cursor.fetchone()
        if not root_row:
            return DocumentWithExtraction(document=document, extraction=None)

        extraction: dict[str, Any] = {}
        root_id = root_row[root_pk]

        for field in schema["fields"]:
            field_type = field["type"]
            sql = field["sql"]
            if field_type == "array":
                table = validate_identifier(sql["table"], "table name")
                fk_column = validate_identifier(sql["fk"]["column"], "column name")
                cursor = await db.execute(
                    f"SELECT * FROM {table} WHERE {fk_column} = ?",
                    (root_id,),
                )
                rows = await cursor.fetchall()
                items: list[Any] = []

                if field.get("items", {}).get("type") == "object":
                    column_defs = sql.get("columns", [])
                    for row in rows:
                        item = {col["name"]: row[col["name"]] for col in column_defs}
                        items.append(item)
                else:
                    column_name = validate_identifier(
                        sql.get("columns", [{"name": "value"}])[0]["name"],
                        "column name"
                    )
                    items = [row[column_name] for row in rows]

                extraction[field["name"]] = items
            else:
                if sql["table"] != root["table"]:  # Compare with original value
                    continue
                column = validate_identifier(sql["column"], "column name")
                extraction[field["name"]] = root_row[column]

        return DocumentWithExtraction(document=document, extraction=extraction)


async def _select_order_column(db: aiosqlite.Connection, table_name: str) -> str:
    """Pick an order column for selecting latest row."""
    # table_name should already be validated by caller
    safe_table = validate_identifier(table_name, "table name")
    cursor = await db.execute(f"PRAGMA table_info({safe_table})")
    rows = await cursor.fetchall()
    available = {row[1] for row in rows}
    if "extracted_at" in available:
        return "extracted_at"
    return "id"


async def execute_sql(query: str) -> tuple[list[str], list[list]]:
    """Execute a read-only SQL query and return results."""
    # Only allow SELECT statements
    query_lower = query.strip().lower()
    if not query_lower.startswith("select"):
        raise ValueError("Only SELECT queries are allowed")

    async with get_db() as db:
        cursor = await db.execute(query)
        rows = await cursor.fetchall()

        if rows:
            columns = list(rows[0].keys())
            data = [list(row) for row in rows]
        else:
            columns = []
            data = []

        return columns, data
