"""FastAPI app entry point."""

import asyncio
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .database import (
    execute_sql,
    get_all_documents,
    get_document_with_contract,
    init_db,
    create_document,
    update_document_status,
)
from .document_loader import extract_text_from_bytes
from .extraction_agent import process_document
from .schemas import SQLQueryRequest, SQLQueryResponse, UploadResponse

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
    """Initialize database on startup."""
    init_db()


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
        await update_document_status(document_id, "processing")
        await process_document(document_id, text, file_type)
    except Exception as e:
        print(f"Error processing document {document_id}: {e}")
        await update_document_status(document_id, "error")


@app.get("/api/documents")
async def list_documents():
    """List all documents."""
    documents = await get_all_documents()
    return {"documents": [doc.model_dump() for doc in documents]}


@app.get("/api/documents/{document_id}")
async def get_document(document_id: int):
    """Get document details with extracted contract data."""
    result = await get_document_with_contract(document_id)
    if not result:
        raise HTTPException(status_code=404, detail="Document not found")
    return result.model_dump()


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
