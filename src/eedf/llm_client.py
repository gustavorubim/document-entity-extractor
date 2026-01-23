"""Raw Google Gemini GenAI wrapper."""

import json
import re
from typing import Any

from google import genai

from .config import GEMINI_MODEL, GOOGLE_API_KEY
from .schema_loader import build_prompt, get_active_schema, normalize_extraction


def get_client() -> genai.Client:
    """Get configured Gemini client."""
    return genai.Client(api_key=GOOGLE_API_KEY)

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


def extract_structured_data(document_text: str) -> dict[str, Any]:
    """Extract structured data from document text using Gemini and active schema."""
    client = get_client()
    schema = get_active_schema()
    prompt = build_prompt(schema)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt + document_text,
    )

    data = parse_json_response(response.text)
    return normalize_extraction(schema, data)
