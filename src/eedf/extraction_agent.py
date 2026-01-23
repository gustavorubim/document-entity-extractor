"""LangGraph agent for contract extraction."""

from typing import TypedDict

from langgraph.graph import END, StateGraph

from .config import MAX_CHUNK_SIZE, CHUNK_OVERLAP
from .database import save_extraction, update_document_status
from .document_loader import chunk_text
from .llm_client import extract_contract_data, merge_extractions
from .schemas import ContractExtraction


class ExtractionState(TypedDict):
    """State for the extraction pipeline."""
    document_id: int
    document_text: str
    document_type: str
    chunks: list[str]
    raw_extractions: list[ContractExtraction]
    contract_data: ContractExtraction | None
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


def extract_contract_info_node(state: ExtractionState) -> ExtractionState:
    """Call Gemini for each chunk to extract contract information."""
    chunks = state["chunks"]
    extractions: list[ContractExtraction] = []

    for chunk in chunks:
        try:
            extraction = extract_contract_data(chunk)
            extractions.append(extraction)
        except Exception as e:
            # Continue with other chunks even if one fails
            print(f"Error extracting from chunk: {e}")
            continue

    return {
        **state,
        "raw_extractions": extractions,
        "status": "extraction_complete",
    }


def merge_results_node(state: ExtractionState) -> ExtractionState:
    """Combine extractions from all chunks, deduplicate."""
    extractions = state["raw_extractions"]
    merged = merge_extractions(extractions)

    return {
        **state,
        "contract_data": merged,
        "status": "merge_complete",
    }


async def save_to_database_node(state: ExtractionState) -> ExtractionState:
    """Persist extraction results to SQLite."""
    document_id = state["document_id"]
    contract_data = state["contract_data"]

    if contract_data:
        try:
            await save_extraction(document_id, contract_data)
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
        "contract_data": None,
        "status": "started",
        "error": None,
    }

    # Run the pipeline
    result = await extraction_pipeline.ainvoke(initial_state)
    return result
