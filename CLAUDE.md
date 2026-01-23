# EEDF - Document Processing App

## Project Overview
A Python application that uses Google Gemini LLM to extract contract/legal data (parties, terms, dates, obligations, clauses) from PDF/DOCX documents, stores results in SQLite, and provides a web UI for management.

## Tech Stack
- **Backend**: FastAPI, uvicorn
- **LLM**: Google Gemini (`gemini-3-flash-preview`) via `google-genai`
- **Orchestration**: LangGraph for agentic workflow
- **Document Parsing**: pypdf (PDF), python-docx (DOCX)
- **Database**: SQLite with aiosqlite
- **UI**: Single-page HTML with light theme

## Directory Structure
```
eedf/
├── pyproject.toml              # UV/pip dependencies
├── src/eedf/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Configuration (API keys, DB path)
│   ├── database.py             # SQLite models and operations
│   ├── document_loader.py      # PDF/DOCX parsing
│   ├── llm_client.py           # Google Gemini GenAI wrapper
│   ├── extraction_agent.py     # LangGraph agent for extraction
│   ├── schemas.py              # Pydantic models
│   ├── generate_test_docs.py   # Synthetic test document generator
│   └── static/index.html       # Single-page UI
├── test_documents/             # Synthetic legal contract files
└── data/extractions.db         # SQLite database
```

## Running the Application

### Setup
```bash
# Install dependencies
uv sync

# Set API key
export GOOGLE_API_KEY=your_gemini_api_key
```

### Generate Test Documents
```bash
uv run python -m eedf.generate_test_docs
```

### Start Server
```bash
uv run uvicorn eedf.main:app --reload
```

Then open http://localhost:8000 in your browser.

## API Endpoints
- `GET /` - Serve the UI
- `POST /api/upload` - Upload and process documents
- `GET /api/documents` - List all documents
- `GET /api/documents/{id}` - Get document details with extracted data
- `POST /api/sql` - Execute read-only SQL queries

## Database Schema
- `documents` - Uploaded documents with raw text and status
- `contracts` - Extracted contract metadata (type, parties, dates)
- `obligations` - Party obligations from contracts
- `clauses` - Legal clauses (confidentiality, termination, etc.)

## LangGraph Pipeline
The extraction pipeline uses LangGraph with these nodes:
1. `chunk_document` - Split large documents for LLM context
2. `extract_contract_info` - Call Gemini for each chunk
3. `merge_results` - Combine and deduplicate extractions
4. `save_to_db` - Persist to SQLite
