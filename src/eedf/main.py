"""FastAPI app entry point."""

import asyncio
import json
import logging
from pathlib import Path

import yaml
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from .config import EXTRACTION_SCHEMA_PATH, GOOGLE_API_KEY
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
from .schema_loader import clear_schema_cache, get_active_schema, validate_schema_detailed
from .schemas import (
    ChatRequest,
    ChatResponse,
    ChatStepResponse,
    SchemaSaveRequest,
    SchemaSaveResponse,
    SchemaValidationError,
    SchemaValidationResponse,
    SQLQueryRequest,
    SQLQueryResponse,
    UploadResponse,
)

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


@app.post("/api/schema", response_model=SchemaSaveResponse)
async def save_schema(request: SchemaSaveRequest):
    """Save a new extraction schema."""
    try:
        # Convert Pydantic model to dict, excluding None values
        schema_dict = request.schema_data.model_dump(exclude_none=True)

        # Validate the schema
        errors, warnings = validate_schema_detailed(schema_dict)

        validation_response = SchemaValidationResponse(
            valid=len(errors) == 0,
            errors=[SchemaValidationError(path=e["path"], message=e["message"], severity="error") for e in errors],
            warnings=[SchemaValidationError(path=w["path"], message=w["message"], severity="warning") for w in warnings],
        )

        if not validation_response.valid:
            return SchemaSaveResponse(
                success=False,
                message="Schema validation failed",
                validation=validation_response,
            )

        # Write the schema to file
        EXTRACTION_SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(EXTRACTION_SCHEMA_PATH, "w", encoding="utf-8") as f:
            yaml.dump(schema_dict, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

        # Clear the schema cache so changes take effect
        clear_schema_cache()

        # Reinitialize database to apply schema changes
        init_db()

        return SchemaSaveResponse(
            success=True,
            message="Schema saved successfully",
            validation=validation_response,
        )

    except Exception as e:
        logger.error(f"Error saving schema: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save schema: {str(e)}")


@app.post("/api/schema/validate", response_model=SchemaValidationResponse)
async def validate_schema(request: SchemaSaveRequest):
    """Validate a schema without saving."""
    try:
        # Convert Pydantic model to dict
        schema_dict = request.schema_data.model_dump(exclude_none=True)

        # Validate the schema
        errors, warnings = validate_schema_detailed(schema_dict)

        return SchemaValidationResponse(
            valid=len(errors) == 0,
            errors=[SchemaValidationError(path=e["path"], message=e["message"], severity="error") for e in errors],
            warnings=[SchemaValidationError(path=w["path"], message=w["message"], severity="warning") for w in warnings],
        )

    except Exception as e:
        logger.error(f"Error validating schema: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to validate schema: {str(e)}")


@app.get("/api/schema/export/{format}")
async def export_schema(format: str):
    """Export the current schema as YAML or JSON."""
    try:
        schema = get_active_schema()

        if format.lower() == "yaml":
            content = yaml.dump(schema, default_flow_style=False, allow_unicode=True, sort_keys=False)
            return Response(
                content=content,
                media_type="application/x-yaml",
                headers={"Content-Disposition": f"attachment; filename=extraction_schema.yaml"},
            )
        elif format.lower() == "json":
            content = json.dumps(schema, indent=2)
            return Response(
                content=content,
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename=extraction_schema.json"},
            )
        else:
            raise HTTPException(status_code=400, detail="Format must be 'yaml' or 'json'")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting schema: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to export schema: {str(e)}")


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


@app.post("/api/chat", response_model=ChatResponse)
async def chat_with_database(request: ChatRequest):
    """Chat with the database using natural language."""
    from .chat_agent import run_chat_agent

    try:
        # Convert history to the format expected by the agent
        history = None
        if request.history:
            history = [{"role": msg.role, "content": msg.content} for msg in request.history]

        result = await run_chat_agent(request.message, history)

        return ChatResponse(
            answer=result.answer,
            steps=[
                ChatStepResponse(
                    thought=step.thought,
                    action=step.action,
                    action_input=step.action_input,
                    observation=step.observation,
                )
                for step in result.steps
            ],
            error=result.error,
        )
    except Exception as e:
        logger.error(f"Error in chat agent: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Chat error: {str(e)}")


def run():
    """Run the application with uvicorn."""
    import uvicorn
    uvicorn.run("eedf.main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
