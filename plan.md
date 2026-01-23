# Document Processing App with Generative AI

## Overview
A Python application that uses Google Gemini LLM to extract **contract/legal data** (parties, terms, dates, obligations, clauses) from PDF/DOCX documents, stores results in SQLite, and provides a web UI for management.

**User Preferences:**
- **Extraction Type**: Contract/Legal Data
- **LLM Model**: `gemini-3-flash-preview`
- **UI Theme**: Light theme

## Architecture

```
eedf/
├── pyproject.toml              # UV/pip dependencies
├── src/
│   └── eedf/
│       ├── __init__.py
│       ├── main.py             # FastAPI app entry point
│       ├── config.py           # Configuration (API keys, DB path)
│       ├── database.py         # SQLite models and operations
│       ├── document_loader.py  # PDF/DOCX parsing
│       ├── llm_client.py       # Google Gemini GenAI wrapper
│       ├── extraction_agent.py # LangGraph agent for extraction
│       ├── schemas.py          # Pydantic models for structured output
│       └── static/
│           └── index.html      # Single-page UI
├── test_documents/             # Synthetic legal contract files
│   ├── service_agreement.pdf
│   ├── nda_mutual.pdf
│   ├── lease_commercial.pdf
│   ├── employment_contract.docx
│   ├── partnership_agreement.docx
│   └── consulting_agreement.docx
└── data/
    └── extractions.db          # SQLite database
```

## Key Components

### 1. Dependencies (pyproject.toml)
- **Core**: `fastapi`, `uvicorn`, `python-multipart`
- **Document parsing**: `pypdf`, `python-docx`
- **LLM**: `google-genai` (raw Gemini client)
- **Orchestration**: `langchain`, `langgraph`
- **Database**: `sqlite3` (built-in), `aiosqlite`
- **Test doc generation**: `reportlab` (PDF), `python-docx` (DOCX)

### 2. LLM Client (`llm_client.py`)
Direct Google Gemini GenAI usage as specified:
```python
from google import genai

client = genai.Client()

def extract_contract_data(document_text: str) -> dict:
    response = client.models.generate_content(
        model="gemini-3-flash-preview",
        contents=f"""Extract contract/legal information from this document.
        Return JSON with: parties, effective_date, termination_date,
        contract_type, key_terms, obligations, clauses, signatures.

        Document:
        {document_text}"""
    )
    return parse_json_response(response.text)
```

### 3. LangGraph Agent (`extraction_agent.py`)
Agentic workflow using LangGraph for orchestration:

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class ExtractionState(TypedDict):
    document_text: str
    document_type: str
    chunks: list[str]
    raw_extractions: list[dict]
    contract_data: dict
    status: str

# Define the graph
graph = StateGraph(ExtractionState)
graph.add_node("load_document", load_document_node)
graph.add_node("chunk_document", chunk_document_node)
graph.add_node("extract_contract_info", extract_with_gemini)  # Uses raw Gemini
graph.add_node("merge_results", merge_extractions_node)
graph.add_node("save_to_db", save_to_database_node)

graph.set_entry_point("load_document")
graph.add_edge("load_document", "chunk_document")
graph.add_edge("chunk_document", "extract_contract_info")
graph.add_edge("extract_contract_info", "merge_results")
graph.add_edge("merge_results", "save_to_db")
graph.add_edge("save_to_db", END)

extraction_pipeline = graph.compile()
```

- **Nodes**:
  - `load_document` - Parse PDF/DOCX using pypdf/python-docx
  - `chunk_document` - Split into manageable pieces for context window
  - `extract_contract_info` - Call Gemini for each chunk (raw google-genai)
  - `merge_results` - Combine extractions, deduplicate parties/clauses
  - `save_to_db` - Persist to SQLite
- **Edges**: Sequential flow with potential conditional routing for large documents

### 4. Database Schema (`database.py`)
```sql
CREATE TABLE documents (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    file_type TEXT NOT NULL,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    raw_text TEXT,
    status TEXT DEFAULT 'pending'
);

CREATE TABLE contracts (
    id INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    contract_type TEXT,
    parties JSON,              -- Array of party names/roles
    effective_date TEXT,
    termination_date TEXT,
    extracted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE obligations (
    id INTEGER PRIMARY KEY,
    contract_id INTEGER REFERENCES contracts(id),
    party TEXT,
    description TEXT,
    due_date TEXT,
    status TEXT DEFAULT 'active'
);

CREATE TABLE clauses (
    id INTEGER PRIMARY KEY,
    contract_id INTEGER REFERENCES contracts(id),
    clause_type TEXT,          -- e.g., 'termination', 'confidentiality', 'liability'
    clause_text TEXT,
    section_reference TEXT
);
```

### 5. FastAPI Backend (`main.py`)
Endpoints:
- `POST /api/upload` - Upload and process documents
- `GET /api/documents` - List all documents
- `GET /api/documents/{id}` - Get document details
- `POST /api/sql` - Execute SQL queries
- `GET /` - Serve the UI

### 6. Web UI (`static/index.html`)
Single HTML file with embedded CSS/JS:
- **Left Ribbon**: Navigation sidebar
  - "Process Documents" section
  - "SQL Explorer" section
- **Main Area**:
  - Drag-and-drop file upload zone
  - Processing status indicators
  - SQL query editor with results table

### 7. Synthetic Test Documents (Contract/Legal Focus)
Create 6 test documents with realistic legal contract data:

**PDFs (using reportlab):**
1. `service_agreement.pdf` - IT Services Agreement between two companies
2. `nda_mutual.pdf` - Mutual Non-Disclosure Agreement
3. `lease_commercial.pdf` - Commercial Property Lease Agreement

**DOCX (using python-docx):**
4. `employment_contract.docx` - Employment Agreement with salary, benefits, terms
5. `partnership_agreement.docx` - Business Partnership Agreement
6. `consulting_agreement.docx` - Independent Contractor/Consulting Agreement

Each document will contain:
- Clearly identified parties with roles
- Effective and termination dates
- Key obligations for each party
- Standard legal clauses (confidentiality, termination, liability)
- Signature blocks

## Implementation Steps

### Step 1: Project Setup
- Create directory structure
- Write `pyproject.toml` with all dependencies
- Initialize UV environment

### Step 2: Core Infrastructure
- `config.py` - Environment variables, paths
- `database.py` - SQLite setup and CRUD operations
- `schemas.py` - Pydantic models for extractions

### Step 3: Document Processing
- `document_loader.py` - PDF/DOCX text extraction
- `llm_client.py` - Gemini GenAI wrapper

### Step 4: LangGraph Agent
- `extraction_agent.py` - Define graph, nodes, state
- Integrate with LLM client for extraction calls

### Step 5: FastAPI Application
- `main.py` - All API endpoints
- File upload handling
- SQL execution endpoint

### Step 6: Web UI
- `static/index.html` - Complete SPA
- Ribbon navigation
- File drop zone
- SQL executor interface

### Step 7: Test Documents
- Script to generate synthetic PDFs and DOCX files
- Realistic data with tables and structured content

## Verification Plan
1. Run `uv sync` to install dependencies
2. Generate test documents: `uv run python -m eedf.generate_test_docs`
3. Start server: `uv run uvicorn eedf.main:app --reload`
4. Open browser to `http://localhost:8000`
5. Upload test documents via UI
6. Verify extractions appear in database
7. Test SQL queries in SQL Explorer

## Environment Variables Required
```
GOOGLE_API_KEY=your_gemini_api_key
```

## Files Created

| File | Purpose |
|------|---------|
| `pyproject.toml` | UV dependencies and project config |
| `src/eedf/__init__.py` | Package init |
| `src/eedf/main.py` | FastAPI app, all endpoints, serves UI |
| `src/eedf/config.py` | Configuration and environment variables |
| `src/eedf/database.py` | SQLite schema and CRUD operations |
| `src/eedf/document_loader.py` | PDF/DOCX text extraction |
| `src/eedf/llm_client.py` | Raw Google Gemini GenAI wrapper |
| `src/eedf/extraction_agent.py` | LangGraph pipeline for extraction |
| `src/eedf/schemas.py` | Pydantic models |
| `src/eedf/static/index.html` | Complete UI (light theme) |
| `src/eedf/generate_test_docs.py` | Script to create synthetic contracts |

## Notes
- Using `gemini-3-flash-preview` as specified by user
- SQLite chosen for simplicity (no external DB setup)
- Single HTML file with light theme for UI keeps deployment simple
- LangGraph handles retry logic and state management
- Contract extraction focuses on: parties, dates, obligations, clauses
