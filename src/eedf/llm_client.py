"""Raw Google Gemini GenAI wrapper."""

import json
import re
from typing import Optional

from google import genai

from .config import GEMINI_MODEL, GOOGLE_API_KEY
from .schemas import Clause, ContractExtraction, Obligation, Party


def get_client() -> genai.Client:
    """Get configured Gemini client."""
    return genai.Client(api_key=GOOGLE_API_KEY)


EXTRACTION_PROMPT = """You are a legal document analysis expert. Extract contract/legal information from this document.

Return a JSON object with the following structure:
{
    "contract_type": "string - type of contract (e.g., 'Service Agreement', 'NDA', 'Employment Contract')",
    "parties": [
        {"name": "party name", "role": "their role in contract", "address": "address if mentioned"}
    ],
    "effective_date": "date when contract becomes effective (YYYY-MM-DD format if possible)",
    "termination_date": "date when contract ends (YYYY-MM-DD format if possible)",
    "key_terms": ["list of key terms and conditions"],
    "obligations": [
        {"party": "party name", "description": "what they must do", "due_date": "deadline if any", "status": "active"}
    ],
    "clauses": [
        {"clause_type": "type (e.g., confidentiality, termination, liability)", "clause_text": "summary of clause", "section_reference": "section number if mentioned"}
    ],
    "signatures": ["list of signatories mentioned"]
}

Be thorough and extract all relevant information. If a field is not found, use null or empty array.
Return ONLY valid JSON, no other text.

Document:
"""


def parse_json_response(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code blocks."""
    text = text.strip()

    # Remove markdown code blocks if present
    if text.startswith("```"):
        # Remove opening ```json or ```
        text = re.sub(r"^```(?:json)?\s*\n?", "", text)
        # Remove closing ```
        text = re.sub(r"\n?```\s*$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {}


def extract_contract_data(document_text: str) -> ContractExtraction:
    """Extract contract data from document text using Gemini."""
    client = get_client()

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=EXTRACTION_PROMPT + document_text,
    )

    data = parse_json_response(response.text)

    # Parse into structured format
    parties = [
        Party(
            name=p.get("name", ""),
            role=p.get("role", ""),
            address=p.get("address", ""),
        )
        for p in data.get("parties", [])
    ]

    obligations = [
        Obligation(
            party=o.get("party", ""),
            description=o.get("description", ""),
            due_date=o.get("due_date"),
            status=o.get("status", "active"),
        )
        for o in data.get("obligations", [])
    ]

    clauses = [
        Clause(
            clause_type=c.get("clause_type", ""),
            clause_text=c.get("clause_text", ""),
            section_reference=c.get("section_reference", ""),
        )
        for c in data.get("clauses", [])
    ]

    return ContractExtraction(
        contract_type=data.get("contract_type", ""),
        parties=parties,
        effective_date=data.get("effective_date"),
        termination_date=data.get("termination_date"),
        key_terms=data.get("key_terms", []),
        obligations=obligations,
        clauses=clauses,
        signatures=data.get("signatures", []),
    )


def merge_extractions(extractions: list[ContractExtraction]) -> ContractExtraction:
    """Merge multiple chunk extractions into a single result."""
    if not extractions:
        return ContractExtraction()

    if len(extractions) == 1:
        return extractions[0]

    # Use the first non-empty contract type
    contract_type = ""
    for e in extractions:
        if e.contract_type:
            contract_type = e.contract_type
            break

    # Merge and deduplicate parties by name
    parties_by_name: dict[str, Party] = {}
    for e in extractions:
        for p in e.parties:
            if p.name and p.name not in parties_by_name:
                parties_by_name[p.name] = p

    # Use the first non-empty dates
    effective_date = None
    termination_date = None
    for e in extractions:
        if e.effective_date and not effective_date:
            effective_date = e.effective_date
        if e.termination_date and not termination_date:
            termination_date = e.termination_date

    # Merge and deduplicate key terms
    key_terms = list(dict.fromkeys(
        term for e in extractions for term in e.key_terms
    ))

    # Merge obligations (deduplicate by description)
    obligations_by_desc: dict[str, Obligation] = {}
    for e in extractions:
        for o in e.obligations:
            key = f"{o.party}:{o.description}"
            if key not in obligations_by_desc:
                obligations_by_desc[key] = o

    # Merge clauses (deduplicate by type+text)
    clauses_by_key: dict[str, Clause] = {}
    for e in extractions:
        for c in e.clauses:
            key = f"{c.clause_type}:{c.clause_text[:100]}"
            if key not in clauses_by_key:
                clauses_by_key[key] = c

    # Merge signatures
    signatures = list(dict.fromkeys(
        sig for e in extractions for sig in e.signatures
    ))

    return ContractExtraction(
        contract_type=contract_type,
        parties=list(parties_by_name.values()),
        effective_date=effective_date,
        termination_date=termination_date,
        key_terms=key_terms,
        obligations=list(obligations_by_desc.values()),
        clauses=list(clauses_by_key.values()),
        signatures=signatures,
    )
