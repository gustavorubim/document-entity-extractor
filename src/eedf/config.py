"""Configuration and environment variables."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base paths - go up from src/eedf/config.py to project root
BASE_DIR = Path(__file__).parent.parent.parent

# Load .env file
load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data"
TEST_DOCS_DIR = BASE_DIR / "test_documents"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
TEST_DOCS_DIR.mkdir(exist_ok=True)

# Database
DATABASE_PATH = Path(
    os.environ.get(
        "DATABASE_PATH",
        str(DATA_DIR / "extractions.db"),
    )
)

# Extraction schema
EXTRACTION_SCHEMA_PATH = Path(
    os.environ.get(
        "EXTRACTION_SCHEMA_PATH",
        str(BASE_DIR / "config" / "extraction_schema.yaml"),
    )
)

# Google Gemini API
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

# LLM Model
GEMINI_MODEL = "gemini-3-flash-preview"

# Document processing
MAX_CHUNK_SIZE = 8000  # Characters per chunk for LLM context
CHUNK_OVERLAP = 500    # Overlap between chunks
