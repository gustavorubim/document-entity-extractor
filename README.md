# EEDF - Intelligent Document Processing

A Python application that leverages Google Gemini LLM to extract structured data from legal contracts and documents (PDF/DOCX). Built with FastAPI, LangGraph, and SQLite.

## Features

- **AI-Powered Extraction**: Uses Google Gemini to extract parties, terms, dates, obligations, and clauses
- **Multi-Format Support**: Processes PDF and DOCX documents
- **Agentic Workflow**: LangGraph orchestrates the extraction pipeline
- **Web Interface**: Clean single-page UI for document management
- **SQL Explorer**: Query extracted data directly with SQL
- **Async Processing**: Non-blocking document processing with real-time status updates

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Installation](#installation)
  - [Using UV (Recommended)](#using-uv-recommended)
  - [Using Python venv](#using-python-venv)
- [Configuration](#configuration)
- [Running the Application](#running-the-application)
- [How It Works](#how-it-works)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [Schema & Migration Plan](#schema--migration-plan)
  - [Schema File Format](#schema-file-format)
  - [Schema Structure Tutorial](#schema-structure-tutorial)
  - [Defining Simple Fields](#defining-simple-fields)
  - [Defining Array Fields](#defining-array-fields)
  - [Merge Strategies](#merge-strategies)
  - [Complete Example: Invoice Schema](#complete-example-invoice-schema)
- [Project Structure](#project-structure)

---

## System Architecture

```mermaid
flowchart TB
    subgraph Client["Client Layer"]
        UI[Web UI<br/>Single Page App]
        API_CLIENT[API Client]
    end

    subgraph Server["Server Layer"]
        FASTAPI[FastAPI Server<br/>Port 8000]
        STATIC[Static Files<br/>index.html]
    end

    subgraph Processing["Processing Layer"]
        LOADER[Document Loader<br/>PDF/DOCX Parser]
        LANGGRAPH[LangGraph Agent<br/>Extraction Pipeline]
        LLM[Google Gemini<br/>gemini-3-flash-preview]
    end

    subgraph Storage["Storage Layer"]
        SQLITE[(SQLite Database<br/>extractions.db)]
    end

    UI --> FASTAPI
    API_CLIENT --> FASTAPI
    FASTAPI --> STATIC
    FASTAPI --> LOADER
    LOADER --> LANGGRAPH
    LANGGRAPH --> LLM
    LANGGRAPH --> SQLITE
    FASTAPI --> SQLITE
```

---

## Installation

### Prerequisites

- Python 3.11 or higher
- Google API Key for Gemini

### Using UV (Recommended)

[UV](https://github.com/astral-sh/uv) is a fast Python package manager written in Rust.

#### Install UV

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or via pip
pip install uv
```

#### Create Virtual Environment

```bash
# Create and sync dependencies
uv sync
```

#### Activate Virtual Environment

**macOS/Linux:**
```bash
source .venv/bin/activate
```

**Windows (Command Prompt):**
```cmd
.venv\Scripts\activate.bat
```

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

---

### Using Python venv

#### Create Virtual Environment

**macOS/Linux:**
```bash
python3 -m venv .venv
```

**Windows:**
```cmd
python -m venv .venv
```

#### Activate Virtual Environment

**macOS/Linux:**
```bash
source .venv/bin/activate
```

**Windows (Command Prompt):**
```cmd
.venv\Scripts\activate.bat
```

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

> **Note:** If you get an execution policy error on PowerShell, run:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

#### Install Dependencies

```bash
pip install -e .
```

Or install from requirements:

```bash
pip install fastapi uvicorn python-multipart pypdf python-docx google-genai langchain langgraph aiosqlite pydantic reportlab
```

---

## Configuration

### Environment Variables

Create a `.env` file in the project root or export the variable:

**macOS/Linux:**
```bash
export GOOGLE_API_KEY=your_gemini_api_key
```

**Windows (Command Prompt):**
```cmd
set GOOGLE_API_KEY=your_gemini_api_key
```

**Windows (PowerShell):**
```powershell
$env:GOOGLE_API_KEY="your_gemini_api_key"
```

### Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `GOOGLE_API_KEY` | Required | Google Gemini API key |
| `LLM_MODEL` | `gemini-3-flash-preview` | Gemini model to use |
| `MAX_CHUNK_SIZE` | 8000 | Maximum characters per chunk |
| `CHUNK_OVERLAP` | 500 | Overlap between chunks |
| `DATABASE_PATH` | `data/extractions.db` | SQLite database path |
| `EXTRACTION_SCHEMA_PATH` | `config/extraction_schema.yaml` | Active extraction schema file (YAML or JSON) |

---

## Running the Application

### Generate Test Documents (Optional)

Generate synthetic legal contracts for testing:

```bash
# Using UV
uv run python -m eedf.generate_test_docs

# Using venv
python -m eedf.generate_test_docs
```

This creates 6 test documents in `test_documents/`:
- 3 PDFs: Service Agreement, NDA, Commercial Lease
- 3 DOCX: Employment Contract, Partnership Agreement, Consulting Agreement

### Start the Server

```bash
# Using UV
uv run uvicorn eedf.main:app --reload

# Using venv
uvicorn eedf.main:app --reload
```

Open your browser at **http://localhost:8000**

---

## How It Works

### Document Upload Flow

```mermaid
sequenceDiagram
    participant User
    participant UI as Web UI
    participant API as FastAPI
    participant Loader as Document Loader
    participant DB as SQLite
    participant Agent as LangGraph Agent
    participant LLM as Gemini LLM

    User->>UI: Upload Document
    UI->>API: POST /api/upload
    API->>Loader: Extract text from file
    Loader-->>API: Raw text content
    API->>DB: Create document record (pending)
    API-->>UI: Return document_id

    Note over API,Agent: Background Processing

    API->>Agent: Start extraction pipeline
    Agent->>Agent: Chunk document

    loop For each chunk
        Agent->>LLM: Extract contract data
        LLM-->>Agent: JSON extraction
    end

    Agent->>Agent: Merge extractions
    Agent->>DB: Save schema-based rows
    Agent->>DB: Update status (completed)

    UI->>API: Poll GET /api/documents
    API-->>UI: Updated status
    User->>UI: View extracted data
```

### LangGraph Extraction Pipeline

```mermaid
stateDiagram-v2
    [*] --> ChunkDocument: Start Pipeline

    ChunkDocument: chunk_document_node
    ChunkDocument: Split text into 8KB chunks
    ChunkDocument: 500 char overlap

    ExtractInfo: extract_contract_info_node
    ExtractInfo: Call Gemini for each chunk
    ExtractInfo: Parse JSON responses

    MergeResults: merge_results_node
    MergeResults: Deduplicate parties
    MergeResults: Merge obligations
    MergeResults: Combine clauses

    SaveDB: save_to_database_node
    SaveDB: Insert root record
    SaveDB: Insert child rows per schema
    SaveDB: Update document status

    ChunkDocument --> ExtractInfo
    ExtractInfo --> MergeResults
    MergeResults --> SaveDB
    SaveDB --> [*]: End Pipeline
```

### Agent State Flow

```mermaid
flowchart LR
    subgraph State["ExtractionState (TypedDict)"]
        direction TB
        S1[document_id: int]
        S2[text: str]
        S3[file_type: str]
        S4[chunks: list]
        S5[raw_extractions: list]
        S6[extraction_data: JSON]
        S7[status: str]
        S8[error: Optional str]
    end

    subgraph Nodes["Pipeline Nodes"]
        N1[chunk_document]
        N2[extract_contract_info]
        N3[merge_results]
        N4[save_to_database]
    end

    S1 & S2 & S3 --> N1
    N1 --> S4
    S4 --> N2
    N2 --> S5
    S5 --> N3
    N3 --> S6
    S6 --> N4
    N4 --> S7 & S8
```

### Document Processing Pipeline

```mermaid
flowchart TD
    subgraph Input["Document Input"]
        PDF[PDF File]
        DOCX[DOCX File]
    end

    subgraph Parsing["Text Extraction"]
        PYPDF[pypdf Library]
        PYDOCX[python-docx Library]
        RAW[Raw Text]
    end

    subgraph Chunking["Text Chunking"]
        SPLIT[Smart Splitting]
        OVERLAP[Overlap Handling]
        CHUNKS[Text Chunks]
    end

    subgraph Extraction["LLM Extraction"]
        PROMPT[Extraction Prompt]
        GEMINI[Gemini API Call]
        JSON[JSON Response]
    end

    subgraph Merging["Result Merging"]
        DEDUP[Deduplication]
        MERGE[Field Merging]
        FINAL[Final Extraction]
    end

    PDF --> PYPDF
    DOCX --> PYDOCX
    PYPDF --> RAW
    PYDOCX --> RAW
    RAW --> SPLIT
    SPLIT --> OVERLAP
    OVERLAP --> CHUNKS
    CHUNKS --> PROMPT
    PROMPT --> GEMINI
    GEMINI --> JSON
    JSON --> DEDUP
    DEDUP --> MERGE
    MERGE --> FINAL
```

### Extraction Data Model (Default Schema)

The default schema is defined in `config/extraction_schema.yaml` and extracts:

- `contract_type` (string)
- `parties` (array of objects)
- `effective_date`, `termination_date` (string)
- `key_terms` (array of string)
- `obligations` (array of objects)
- `clauses` (array of objects)
- `signatures` (array of string)

---

## API Reference

### Endpoints Overview

```mermaid
flowchart LR
    subgraph Endpoints["API Endpoints"]
        E1["GET /"]
        E2["POST /api/upload"]
        E3["GET /api/documents"]
        E4["GET /api/documents/{id}"]
        E5["POST /api/sql"]
        E6["GET /api/schema"]
    end

    subgraph Responses["Responses"]
        R1[HTML Page]
        R2[UploadResponse]
        R3[DocumentRecord List]
        R4[DocumentWithExtraction]
        R5[SQLQueryResponse]
        R6[ExtractionSchema]
    end

    E1 --> R1
    E2 --> R2
    E3 --> R3
    E4 --> R4
    E5 --> R5
    E6 --> R6
```

### Endpoint Details

| Endpoint | Method | Description | Request | Response |
|----------|--------|-------------|---------|----------|
| `/` | GET | Serve web UI | - | HTML |
| `/api/upload` | POST | Upload document | `multipart/form-data` | `{document_id, filename, status, message}` |
| `/api/documents` | GET | List all documents | - | `{documents: DocumentRecord[]}` |
| `/api/documents/{id}` | GET | Get document details | Path: `id` | `DocumentWithExtraction` |
| `/api/schema` | GET | Get active extraction schema | - | JSON schema |
| `/api/sql` | POST | Execute SQL query | `{query: string}` | `{columns, rows, row_count}` |

### Upload Response

```json
{
  "document_id": 1,
  "filename": "contract.pdf",
  "status": "processing",
  "message": "Document uploaded and processing started"
}
```

### Document Status Values

```mermaid
stateDiagram-v2
    [*] --> pending: Document Created
    pending --> processing: Processing Started
    processing --> completed: Extraction Success
    processing --> error: Extraction Failed
    processing --> no_data: No Data Extracted
```

---

## Database Schema

Database tables are generated from the active schema file (`EXTRACTION_SCHEMA_PATH`). The diagram below reflects the **default** schema in `config/extraction_schema.json`.

### Entity Relationship Diagram

```mermaid
erDiagram
    documents ||--o| contracts : "has"
    contracts ||--o{ parties : "contains"
    contracts ||--o{ obligations : "contains"
    contracts ||--o{ clauses : "contains"
    contracts ||--o{ key_terms : "contains"
    contracts ||--o{ signatures : "contains"

    documents {
        int id PK
        string filename
        string file_type
        timestamp upload_date
        text raw_text
        string status
    }

    contracts {
        int id PK
        int document_id FK
        string contract_type
        string effective_date
        string termination_date
        timestamp extracted_at
    }

    parties {
        int id PK
        int contract_id FK
        string name
        string role
        string address
    }

    obligations {
        int id PK
        int contract_id FK
        string party
        text description
        string due_date
        string status
    }

    clauses {
        int id PK
        int contract_id FK
        string clause_type
        text clause_text
        string section_reference
    }

    key_terms {
        int id PK
        int contract_id FK
        string term
    }

    signatures {
        int id PK
        int contract_id FK
        string signatory
    }
```

### Table Descriptions

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `documents` | Uploaded files and raw text | filename, status, raw_text |
| `contracts` | Extracted contract metadata | contract_type, dates |
| `parties` | Contract parties | name, role, address |
| `obligations` | Party obligations | party, description, due_date |
| `clauses` | Legal clauses | clause_type, clause_text |
| `key_terms` | Key terms | term |
| `signatures` | Signatories | signatory |

### Sample SQL Queries

```sql
-- Get all completed documents with contract types
SELECT d.filename, c.contract_type, c.effective_date
FROM documents d
JOIN contracts c ON d.id = c.document_id
WHERE d.status = 'completed';

-- Get all obligations grouped by party
SELECT party, COUNT(*) as obligation_count
FROM obligations
GROUP BY party;

-- Get clauses by type
SELECT clause_type, COUNT(*) as count
FROM clauses
GROUP BY clause_type
ORDER BY count DESC;
```

---

## Schema & Migration Plan

This app uses a single active extraction schema defined by `EXTRACTION_SCHEMA_PATH` (default: `config/extraction_schema.yaml`). On startup, EEDF:

1. Creates any missing tables for the schema.
2. Adds any missing columns to existing tables.
3. Records the schema hash in `schema_meta`.

### Schema File Format

EEDF supports both **YAML** (recommended) and **JSON** schema files. YAML is preferred for human editing due to:

| Feature | JSON | YAML |
|---------|------|------|
| Comments | Not allowed | `# comment` supported |
| Quoting | Required for all strings | Optional for most |
| Multi-line strings | Escaped `\n` | Native block scalars |
| Visual nesting | Brackets `{}[]` | Indentation |
| Trailing commas | Syntax error | Not needed |

---

### Schema Structure Tutorial

The extraction schema defines **what to extract** from documents and **how to store it** in SQLite. Here's a complete walkthrough.

#### Top-Level Structure

```yaml
# Schema metadata
name: my_schema          # Unique identifier
version: 1               # Schema version number
description: What this schema extracts.

# LLM prompt configuration
prompt:
  system: You are an expert at analyzing documents.
  instructions: >-
    Extract all relevant information.
    Return ONLY valid JSON, no other text.

# Root table configuration (main extraction record)
root:
  table: extractions           # Main table name
  primary_key: id
  document_fk:
    column: document_id        # Foreign key to documents table
    references: documents(id)
  extra_columns:               # Additional columns for the root table
    - name: extracted_at
      type: TIMESTAMP
      default: CURRENT_TIMESTAMP

# Fields to extract (see below)
fields:
  - name: field_name
    # ... field definition
```

#### Field Types

EEDF supports these field types:

| Type | Description | Example Value |
|------|-------------|---------------|
| `string` | Text value | `"Service Agreement"` |
| `date` | Date string (YYYY-MM-DD preferred) | `"2024-01-15"` |
| `integer` | Whole number | `42` |
| `number` | Decimal number | `3.14` |
| `boolean` | True/false | `true` |
| `array` | List of items | `["item1", "item2"]` |
| `object` | Nested structure | `{"key": "value"}` |

---

### Defining Simple Fields

Simple fields store a single value in the root table:

```yaml
fields:
  # String field
  - name: contract_type
    type: string
    description: Type of contract (e.g., NDA, Service Agreement).
    sql:
      table: contracts        # Store in root table
      column: contract_type   # Column name
      type: TEXT              # SQLite type
    merge:
      strategy: first_non_empty

  # Date field
  - name: effective_date
    type: date
    description: Date when contract becomes effective (YYYY-MM-DD).
    sql:
      table: contracts
      column: effective_date
      type: TEXT
    merge:
      strategy: first_non_empty

  # Integer field
  - name: total_value
    type: integer
    description: Total contract value in dollars.
    sql:
      table: contracts
      column: total_value
      type: INTEGER
    merge:
      strategy: first_non_empty
```

---

### Defining Array Fields

Array fields create **child tables** with foreign keys to the root table.

#### Simple Array (list of strings)

```yaml
- name: key_terms
  type: array
  description: Key terms and conditions.
  items:
    type: string                    # Each item is a string
  sql:
    table: key_terms                # Child table name
    columns:
      - name: term                  # Column for each item
        type: TEXT
    fk:
      column: contract_id           # Foreign key column
      references: contracts(id)     # References root table
  merge:
    strategy: union_unique          # Deduplicate across chunks
```

This creates a `key_terms` table:
```sql
CREATE TABLE key_terms (
    id INTEGER PRIMARY KEY,
    contract_id INTEGER REFERENCES contracts(id),
    term TEXT
);
```

#### Array of Objects (structured items)

```yaml
- name: parties
  type: array
  description: Parties to the contract.
  items:
    type: object
    unique_by: [name]               # Deduplication key
    fields:
      - name: name
        type: string
        description: Party name.
      - name: role
        type: string
        description: Role in contract (e.g., Buyer, Seller).
      - name: address
        type: string
        description: Address if mentioned.
  sql:
    table: parties
    columns:
      - name: name
        type: TEXT
      - name: role
        type: TEXT
      - name: address
        type: TEXT
    fk:
      column: contract_id
      references: contracts(id)
  merge:
    strategy: union_by_key
    key_fields: [name]              # Merge by party name
```

This creates a `parties` table:
```sql
CREATE TABLE parties (
    id INTEGER PRIMARY KEY,
    contract_id INTEGER REFERENCES contracts(id),
    name TEXT,
    role TEXT,
    address TEXT
);
```

---

### Merge Strategies

When documents are split into chunks, each chunk may extract partial data. Merge strategies combine results:

| Strategy | Use Case | Behavior |
|----------|----------|----------|
| `first_non_empty` | Single-value fields | Takes first non-null value found |
| `union_unique` | String arrays | Combines all unique strings |
| `union_by_key` | Object arrays | Deduplicates by specified key fields |
| `concat` | Arrays where duplicates are OK | Concatenates all items |

```yaml
# For single values - take the first one found
merge:
  strategy: first_non_empty

# For string arrays - combine unique values
merge:
  strategy: union_unique

# For object arrays - deduplicate by key
merge:
  strategy: union_by_key
  key_fields: [name, date]          # Composite key
```

---

### Complete Example: Invoice Schema

Here's a complete custom schema for extracting invoice data:

```yaml
# config/invoice_schema.yaml
name: invoice_extraction
version: 1
description: Extract structured data from invoices.

prompt:
  system: You are an expert at analyzing invoices and financial documents.
  instructions: >-
    Extract all invoice details accurately.
    Use YYYY-MM-DD format for dates.
    Use numeric values without currency symbols for amounts.
    Return ONLY valid JSON.

root:
  table: invoices
  primary_key: id
  document_fk:
    column: document_id
    references: documents(id)
  extra_columns:
    - name: extracted_at
      type: TIMESTAMP
      default: CURRENT_TIMESTAMP

fields:
  # Invoice metadata
  - name: invoice_number
    type: string
    description: The invoice number or ID.
    sql:
      table: invoices
      column: invoice_number
      type: TEXT
    merge:
      strategy: first_non_empty

  - name: invoice_date
    type: date
    description: Date the invoice was issued (YYYY-MM-DD).
    sql:
      table: invoices
      column: invoice_date
      type: TEXT
    merge:
      strategy: first_non_empty

  - name: due_date
    type: date
    description: Payment due date (YYYY-MM-DD).
    sql:
      table: invoices
      column: due_date
      type: TEXT
    merge:
      strategy: first_non_empty

  # Amounts
  - name: subtotal
    type: number
    description: Subtotal before tax.
    sql:
      table: invoices
      column: subtotal
      type: REAL
    merge:
      strategy: first_non_empty

  - name: tax_amount
    type: number
    description: Total tax amount.
    sql:
      table: invoices
      column: tax_amount
      type: REAL
    merge:
      strategy: first_non_empty

  - name: total_amount
    type: number
    description: Total amount due.
    sql:
      table: invoices
      column: total_amount
      type: REAL
    merge:
      strategy: first_non_empty

  # Vendor and customer
  - name: vendor_name
    type: string
    description: Name of the vendor/seller.
    sql:
      table: invoices
      column: vendor_name
      type: TEXT
    merge:
      strategy: first_non_empty

  - name: customer_name
    type: string
    description: Name of the customer/buyer.
    sql:
      table: invoices
      column: customer_name
      type: TEXT
    merge:
      strategy: first_non_empty

  # Line items (child table)
  - name: line_items
    type: array
    description: Individual items on the invoice.
    items:
      type: object
      unique_by: [description, quantity]
      fields:
        - name: description
          type: string
          description: Item description.
        - name: quantity
          type: number
          description: Quantity ordered.
        - name: unit_price
          type: number
          description: Price per unit.
        - name: line_total
          type: number
          description: Total for this line item.
    sql:
      table: invoice_line_items
      columns:
        - name: description
          type: TEXT
        - name: quantity
          type: REAL
        - name: unit_price
          type: REAL
        - name: line_total
          type: REAL
      fk:
        column: invoice_id
        references: invoices(id)
    merge:
      strategy: union_by_key
      key_fields: [description, quantity]
```

#### Using the Custom Schema

```bash
# Set the schema path
export EXTRACTION_SCHEMA_PATH=config/invoice_schema.yaml

# Start the server
uv run uvicorn eedf.main:app --reload
```

---

### Changing to a Different Extraction Schema

1. Copy the default schema file and update fields, merge strategies, and SQL mappings.
2. Set `EXTRACTION_SCHEMA_PATH` to point at the new schema file.
3. Restart the server to apply schema changes.

### Breaking Changes (Renames/Drops)

Automatic migration is **additive only**. For renames or removals:

- **Recommended**: start a new database by setting `DATABASE_PATH` to a new file and reprocess documents.
- **Advanced**: perform manual SQL migrations (rename table/column, move data) before starting the server.

### Tips for Custom Schemas

- Prefer stable table/column names early.
- Use array fields for repeatable entities and map them to child tables.
- Keep one active schema per deployment to avoid conflicting table definitions.
- Add descriptive comments in YAML to document field purposes.
- Test with a few documents before processing large batches.

## Project Structure

```mermaid
flowchart TB
    subgraph Root["eedf/"]
        PYPROJECT[pyproject.toml]
        README[README.md]
        CLAUDE[CLAUDE.md]
    end

    subgraph Src["src/eedf/"]
        MAIN[main.py<br/>FastAPI Entry]
        CONFIG[config.py<br/>Settings]
        SCHEMAS[schemas.py<br/>Pydantic Models]
        DATABASE[database.py<br/>SQLite Operations]
        LOADER[document_loader.py<br/>PDF/DOCX Parser]
        LLM[llm_client.py<br/>Gemini Wrapper]
        AGENT[extraction_agent.py<br/>LangGraph Pipeline]
        TESTGEN[generate_test_docs.py<br/>Test Data Generator]
    end

    subgraph Static["src/eedf/static/"]
        INDEX[index.html<br/>Web UI]
    end

    subgraph Data["data/"]
        DB[(extractions.db)]
    end

    subgraph TestDocs["test_documents/"]
        PDF1[service_agreement.pdf]
        PDF2[nda_mutual.pdf]
        PDF3[lease_commercial.pdf]
        DOCX1[employment_contract.docx]
        DOCX2[partnership_agreement.docx]
        DOCX3[consulting_agreement.docx]
    end

    Root --> Src
    Src --> Static
    Root --> Data
    Root --> TestDocs
```

### File Descriptions

| File | Purpose |
|------|---------|
| `main.py` | FastAPI application, routes, and startup logic |
| `config.py` | Environment variables and configuration constants |
| `schemas.py` | Pydantic models for request/response validation |
| `database.py` | SQLite schema, async operations, CRUD functions |
| `document_loader.py` | PDF/DOCX text extraction and chunking |
| `llm_client.py` | Google Gemini API integration and prompt engineering |
| `extraction_agent.py` | LangGraph workflow definition and node implementations |
| `generate_test_docs.py` | Synthetic test document generator |
| `static/index.html` | Single-page web application |
| `config/extraction_schema.yaml` | Active extraction schema (tables, fields, prompt) - YAML or JSON supported |

---

## Web UI Overview

```mermaid
flowchart TB
    subgraph Layout["Page Layout"]
        direction LR
        SIDEBAR[Sidebar<br/>Navigation]
        MAIN[Main Content<br/>Dynamic]
    end

    subgraph Navigation["Navigation Items"]
        NAV1[Process Documents]
        NAV2[SQL Explorer]
    end

    subgraph ProcessDocs["Process Documents Page"]
        UPLOAD[Upload Zone<br/>Drag & Drop]
        TABLE[Documents Table<br/>Status, Actions]
        MODAL[Detail Modal<br/>Extracted Data]
    end

    subgraph SQLExplorer["SQL Explorer Page"]
        QUERY[Query Editor<br/>Textarea]
        SHORTCUTS[Quick Shortcuts<br/>Preset Queries]
        RESULTS[Results Table<br/>Dynamic Columns]
    end

    SIDEBAR --> NAV1
    SIDEBAR --> NAV2
    NAV1 --> ProcessDocs
    NAV2 --> SQLExplorer
```

### UI Features

- **Light Theme**: Clean, professional design
- **Drag & Drop Upload**: Easy document upload
- **Real-time Status**: Auto-polling for processing updates
- **Modal View**: Detailed extraction results
- **SQL Explorer**: Direct database queries with preset shortcuts

---

## Technology Stack

```mermaid
mindmap
    root((EEDF))
        Backend
            FastAPI
            Uvicorn
            Pydantic
        AI/ML
            Google Gemini
            LangGraph
            LangChain
        Document Processing
            pypdf
            python-docx
        Database
            SQLite
            aiosqlite
        Frontend
            HTML5
            CSS3
            Vanilla JS
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | >=0.115.0 | Web framework |
| uvicorn | >=0.32.0 | ASGI server |
| python-multipart | >=0.0.12 | File upload handling |
| pypdf | >=5.0.0 | PDF text extraction |
| python-docx | >=1.1.0 | DOCX text extraction |
| google-genai | >=1.0.0 | Gemini LLM API |
| langchain | >=0.3.0 | LLM orchestration |
| langgraph | >=0.2.0 | Agentic workflows |
| aiosqlite | >=0.20.0 | Async SQLite |
| pydantic | >=2.9.0 | Data validation |
| reportlab | >=4.2.0 | PDF generation (test docs) |

---

## Error Handling

```mermaid
flowchart TD
    subgraph Upload["Upload Errors"]
        U1[Invalid File Type] --> U1R[HTTP 400]
        U2[Text Extraction Failed] --> U2R[HTTP 400]
    end

    subgraph Processing["Processing Errors"]
        P1[Chunk Extraction Failed] --> P1R[Continue with other chunks]
        P2[All Chunks Failed] --> P2R[Status: error]
        P3[No Data Extracted] --> P3R[Status: no_data]
    end

    subgraph SQL["SQL Errors"]
        S1[Non-SELECT Query] --> S1R[HTTP 400: Only SELECT allowed]
        S2[Syntax Error] --> S2R[Return error message]
    end
```

---

## License

MIT License

---

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

---

## Support

For issues and feature requests, please open an issue on GitHub.
