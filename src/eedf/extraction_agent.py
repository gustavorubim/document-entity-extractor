"""LangGraph agent for schema-driven extraction."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from .config import MAX_CHUNK_SIZE, CHUNK_OVERLAP
from .database import save_extraction, update_document_status
from .document_loader import chunk_text
from .llm_client import extract_structured_data
from .schema_loader import get_active_schema, merge_extractions

logger = logging.getLogger(__name__)

# Thread pool for parallel LLM calls
_executor = ThreadPoolExecutor(max_workers=4)


class ExtractionState(TypedDict):
    """State for the extraction pipeline."""
    document_id: int
    document_text: str
    document_type: str
    chunks: list[str]
    raw_extractions: list[dict[str, Any]]
    extraction_data: dict[str, Any] | None
    status: str
    error: str | None


def chunk_document_node(state: ExtractionState) -> ExtractionState:
    """Split document into manageable chunks for LLM context."""
    text = state["document_text"]
    chunks = chunk_text(text, MAX_CHUNK_SIZE, CHUNK_OVERLAP)
    return {
        **state,
        "chunks": chunks,
        "status": "chunking_complete",
    }


async def extract_single_chunk(chunk: str, chunk_index: int) -> dict[str, Any] | None:
    """Extract data from a single chunk asynchronously."""
    loop = asyncio.get_event_loop()
    try:
        extraction = await loop.run_in_executor(_executor, extract_structured_data, chunk)
        logger.debug(f"Successfully extracted chunk {chunk_index}")
        return extraction
    except Exception as e:
        logger.warning(f"Error extracting from chunk {chunk_index}: {e}", exc_info=True)
        return None


async def extract_contract_info_node(state: ExtractionState) -> ExtractionState:
    """Call Gemini for each chunk to extract contract information (parallel)."""
    chunks = state["chunks"]
    logger.info(f"Processing {len(chunks)} chunks in parallel")

    # Create tasks for parallel extraction
    tasks = [
        extract_single_chunk(chunk, i)
        for i, chunk in enumerate(chunks)
    ]

    # Execute all extractions in parallel
    results = await asyncio.gather(*tasks, return_exceptions=False)

    # Filter out failed extractions (None results)
    extractions = [r for r in results if r is not None]
    logger.info(f"Successfully extracted {len(extractions)}/{len(chunks)} chunks")

    return {
        **state,
        "raw_extractions": extractions,
        "status": "extraction_complete",
    }


def merge_results_node(state: ExtractionState) -> ExtractionState:
    """Combine extractions from all chunks, deduplicate."""
    extractions = state["raw_extractions"]
    schema = get_active_schema()
    merged = merge_extractions(schema, extractions)

    return {
        **state,
        "extraction_data": merged,
        "status": "merge_complete",
    }


async def save_to_database_node(state: ExtractionState) -> ExtractionState:
    """Persist extraction results to SQLite."""
    document_id = state["document_id"]
    extraction_data = state["extraction_data"]

    if extraction_data:
        try:
            schema = get_active_schema()
            await save_extraction(document_id, extraction_data, schema)
            await update_document_status(document_id, "completed")
            return {
                **state,
                "status": "saved",
            }
        except Exception as e:
            await update_document_status(document_id, "error")
            return {
                **state,
                "status": "error",
                "error": str(e),
            }
    else:
        await update_document_status(document_id, "no_data")
        return {
            **state,
            "status": "no_data",
        }


def build_extraction_graph() -> StateGraph:
    """Build the LangGraph extraction pipeline."""
    graph = StateGraph(ExtractionState)

    # Add nodes
    graph.add_node("chunk_document", chunk_document_node)
    graph.add_node("extract_contract_info", extract_contract_info_node)
    graph.add_node("merge_results", merge_results_node)
    graph.add_node("save_to_db", save_to_database_node)

    # Set entry point
    graph.set_entry_point("chunk_document")

    # Add edges (sequential flow)
    graph.add_edge("chunk_document", "extract_contract_info")
    graph.add_edge("extract_contract_info", "merge_results")
    graph.add_edge("merge_results", "save_to_db")
    graph.add_edge("save_to_db", END)

    return graph


# Compile the graph
extraction_graph = build_extraction_graph()
extraction_pipeline = extraction_graph.compile()


async def process_document(
    document_id: int,
    document_text: str,
    document_type: str,
) -> ExtractionState:
    """Run the extraction pipeline on a document."""
    initial_state: ExtractionState = {
        "document_id": document_id,
        "document_text": document_text,
        "document_type": document_type,
        "chunks": [],
        "raw_extractions": [],
        "extraction_data": None,
        "status": "started",
        "error": None,
    }

    # Run the pipeline
    result = await extraction_pipeline.ainvoke(initial_state)
    return result
