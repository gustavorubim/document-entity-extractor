"""Extraction schema loading and helpers."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .config import EXTRACTION_SCHEMA_PATH

SUPPORTED_FIELD_TYPES = {"string", "date", "integer", "number", "boolean", "array", "object"}


def load_schema(path: Path) -> dict[str, Any]:
    """Load and validate an extraction schema from disk.

    Supports both JSON (.json) and YAML (.yaml, .yml) formats.
    """
    with path.open("r", encoding="utf-8") as handle:
        if path.suffix in (".yaml", ".yml"):
            schema = yaml.safe_load(handle)
        else:
            schema = json.load(handle)
    validate_schema(schema)
    return schema


@lru_cache
def get_active_schema() -> dict[str, Any]:
    """Return the active schema configured for this deployment."""
    return load_schema(EXTRACTION_SCHEMA_PATH)


def schema_hash(schema: dict[str, Any]) -> str:
    """Return a stable hash for a schema."""
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_schema(schema: dict[str, Any]) -> None:
    """Basic schema validation for required structure."""
    if not isinstance(schema, dict):
        raise ValueError("Schema must be a JSON object")

    for key in ("name", "version", "root", "fields"):
        if key not in schema:
            raise ValueError(f"Schema missing required key: {key}")

    root = schema["root"]
    if "table" not in root or "document_fk" not in root:
        raise ValueError("Schema root must define table and document_fk")

    if "column" not in root["document_fk"] or "references" not in root["document_fk"]:
        raise ValueError("Schema root document_fk must define column and references")

    fields = schema["fields"]
    if not isinstance(fields, list):
        raise ValueError("Schema fields must be a list")

    for field in fields:
        _validate_field(field)


def _validate_field(field: dict[str, Any]) -> None:
    if "name" not in field or "type" not in field or "sql" not in field:
        raise ValueError("Each field must define name, type, and sql mapping")

    field_type = field["type"]
    if field_type not in SUPPORTED_FIELD_TYPES:
        raise ValueError(f"Unsupported field type: {field_type}")

    sql = field["sql"]
    if "table" not in sql:
        raise ValueError(f"Field {field['name']} missing sql.table")

    if field_type == "array":
        if "items" not in field:
            raise ValueError(f"Array field {field['name']} missing items")
        if "columns" not in sql:
            raise ValueError(f"Array field {field['name']} missing sql.columns")
        if "fk" not in sql or "column" not in sql["fk"]:
            raise ValueError(f"Array field {field['name']} missing sql.fk.column")
    else:
        if "column" not in sql:
            raise ValueError(f"Field {field['name']} missing sql.column")


def build_prompt(schema: dict[str, Any]) -> str:
    """Build a schema-driven extraction prompt."""
    prompt_parts = []
    prompt_info = schema.get("prompt", {})
    system = prompt_info.get("system", "You are a document analysis expert.")
    instructions = prompt_info.get(
        "instructions",
        "Return ONLY valid JSON, no other text.",
    )

    prompt_parts.append(system)
    prompt_parts.append("Extract the following fields and return a JSON object with this structure:")
    prompt_parts.append(render_schema_template(schema))
    prompt_parts.append(instructions)
    prompt_parts.append("Document:\n")
    return "\n\n".join(prompt_parts)


def render_schema_template(schema: dict[str, Any]) -> str:
    """Render a JSON template with descriptions for the prompt."""
    field_lines = []
    for field in schema["fields"]:
        field_lines.append(render_field_template(field, indent=2))
    inner = ",\n".join(field_lines)
    return "{\n" + inner + "\n}"


def render_field_template(field: dict[str, Any], indent: int = 2) -> str:
    """Render a single field template line."""
    name = field["name"]
    field_type = field["type"]
    description = field.get("description", "")
    prefix = " " * indent + f"\"{name}\": "

    if field_type == "array":
        items = field["items"]
        item_type = items.get("type", "string")
        if item_type == "object":
            obj_lines = []
            for obj_field in items.get("fields", []):
                obj_lines.append(render_field_template(obj_field, indent=indent + 4))
            obj_inner = ",\n".join(obj_lines)
            value = "[\n" + (" " * (indent + 2)) + "{\n" + obj_inner + "\n" + (" " * (indent + 2)) + "}\n" + (" " * indent) + "]"
        else:
            item_desc = _format_description(item_type, items.get("description", ""))
            value = f"[\"{item_desc}\"]"
    else:
        value = f"\"{_format_description(field_type, description)}\""

    return prefix + value


def _format_description(field_type: str, description: str) -> str:
    if description:
        return f"{field_type} - {description}"
    return field_type


def normalize_extraction(schema: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    """Normalize raw extraction data to schema fields."""
    normalized: dict[str, Any] = {}
    for field in schema["fields"]:
        name = field["name"]
        field_type = field["type"]
        value = data.get(name)

        if field_type == "array":
            normalized[name] = _normalize_array(field, value)
        elif field_type in {"string", "date"}:
            normalized[name] = value if isinstance(value, str) and value.strip() else None
        elif field_type in {"integer", "number"}:
            normalized[name] = value if isinstance(value, (int, float)) else None
        elif field_type == "boolean":
            normalized[name] = bool(value) if isinstance(value, bool) else None
        else:
            normalized[name] = value

    return normalized


def _normalize_array(field: dict[str, Any], value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []

    items = field.get("items", {})
    item_type = items.get("type", "string")
    if item_type == "object":
        normalized_items = []
        item_fields = items.get("fields", [])
        for item in value:
            if not isinstance(item, dict):
                continue
            normalized_item = {}
            for sub_field in item_fields:
                sub_name = sub_field["name"]
                sub_value = item.get(sub_name)
                if sub_field["type"] in {"string", "date"}:
                    normalized_item[sub_name] = sub_value if isinstance(sub_value, str) else ""
                elif sub_field["type"] in {"integer", "number"}:
                    normalized_item[sub_name] = sub_value if isinstance(sub_value, (int, float)) else None
                elif sub_field["type"] == "boolean":
                    normalized_item[sub_name] = bool(sub_value) if isinstance(sub_value, bool) else None
                else:
                    normalized_item[sub_name] = sub_value
            if any(v not in (None, "", []) for v in normalized_item.values()):
                normalized_items.append(normalized_item)
        return normalized_items

    return [item for item in value if isinstance(item, str) and item.strip()]


def merge_extractions(schema: dict[str, Any], extractions: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge multiple extractions using schema-defined strategies."""
    if not extractions:
        return normalize_extraction(schema, {})

    merged: dict[str, Any] = {}
    for field in schema["fields"]:
        name = field["name"]
        strategy = field.get("merge", {}).get("strategy", "first_non_empty")
        values = [ex.get(name) for ex in extractions if ex]
        merged[name] = _merge_field(field, values, strategy)
    return merged


def _merge_field(field: dict[str, Any], values: list[Any], strategy: str) -> Any:
    field_type = field["type"]
    if strategy == "first_non_empty":
        for value in values:
            if value not in (None, "", [], {}):
                return value
        return [] if field_type == "array" else None

    if field_type == "array":
        if strategy == "union_unique":
            merged: list[Any] = []
            seen = set()
            for value in values:
                for item in value or []:
                    if item in seen:
                        continue
                    seen.add(item)
                    merged.append(item)
            return merged

        if strategy == "union_by_key":
            key_fields = field.get("merge", {}).get("key_fields", [])
            merged_items: list[dict[str, Any]] = []
            seen_keys = set()
            for value in values:
                for item in value or []:
                    if not isinstance(item, dict):
                        continue
                    key = tuple(item.get(k) for k in key_fields)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    merged_items.append(item)
            return merged_items

        if strategy == "concat":
            merged_list: list[Any] = []
            for value in values:
                merged_list.extend(value or [])
            return merged_list

    return values[0] if values else None
