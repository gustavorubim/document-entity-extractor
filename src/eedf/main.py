"""FastAPI app entry point."""

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import GOOGLE_API_KEY
from .database import (
    execute_sql,
    get_all_documents,
    init_db,
    create_document,
    update_document_status,
    get_document_with_extraction,
)
from .document_loader import extract_text_from_bytes
from .extraction_agent import process_document
from .schema_loader import get_active_schema
from .schemas import SQLQueryRequest, SQLQueryResponse, UploadResponse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="EEDF - Document Processing App",
    description="Extract contract/legal data from PDF/DOCX documents using Google Gemini",
    version="0.1.0",
)

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"


@app.on_event("startup")
async def startup():
    """Initialize database on startup and validate configuration."""
    # Validate API key
    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY environment variable is not set")
        raise ValueError(
            "GOOGLE_API_KEY environment variable is required. "
            "Please set it in your .env file or environment."
        )

    logger.info("Starting EEDF Document Processing App")
    init_db()
    logger.info("Database initialized successfully")


@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the main UI."""
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse("<h1>UI not found</h1>", status_code=404)


@app.post("/api/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    """Upload and process a document."""
    # Validate file type
    filename = file.filename or "unknown"
    file_ext = Path(filename).suffix.lower()

    if file_ext not in (".pdf", ".docx", ".doc"):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file_ext}. Only PDF and DOCX files are supported.",
        )

    # Read file content
    content = await file.read()

    # Extract text
    try:
        file_type = file_ext.lstrip(".")
        text = extract_text_from_bytes(content, file_type)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to extract text from document: {str(e)}",
        )

    # Create document record
    document_id = await create_document(filename, file_type, text)

    # Start processing in background
    asyncio.create_task(process_document_background(document_id, text, file_type))

    return UploadResponse(
        document_id=document_id,
        filename=filename,
        status="processing",
        message="Document uploaded and processing started",
    )


async def process_document_background(
    document_id: int, text: str, file_type: str
) -> None:
    """Process document in background."""
    try:
        logger.info(f"Starting background processing for document {document_id}")
        await update_document_status(document_id, "processing")
        await process_document(document_id, text, file_type)
        logger.info(f"Successfully processed document {document_id}")
    except Exception as e:
        logger.error(f"Error processing document {document_id}: {e}", exc_info=True)
        await update_document_status(document_id, "error")


@app.get("/api/documents")
async def list_documents():
    """List all documents."""
    documents = await get_all_documents()
    return {"documents": [doc.model_dump() for doc in documents]}


@app.get("/api/documents/{document_id}")
async def get_document(document_id: int):
    """Get document details with extracted contract data."""
    schema = get_active_schema()
    result = await get_document_with_extraction(document_id, schema)
    if not result:
        raise HTTPException(status_code=404, detail="Document not found")
    return result.model_dump()


@app.get("/api/schema")
async def get_schema():
    """Get the active extraction schema."""
    return get_active_schema()


@app.post("/api/sql", response_model=SQLQueryResponse)
async def execute_sql_query(request: SQLQueryRequest):
    """Execute a SQL query against the database."""
    try:
        columns, rows = await execute_sql(request.query)
        return SQLQueryResponse(
            columns=columns,
            rows=rows,
            row_count=len(rows),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"SQL error: {str(e)}")


def run():
    """Run the application with uvicorn."""
    import uvicorn
    uvicorn.run("eedf.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
