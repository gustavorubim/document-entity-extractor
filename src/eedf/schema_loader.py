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


def clear_schema_cache() -> None:
    """Clear the cached schema so it gets reloaded on next access."""
    get_active_schema.cache_clear()


def validate_schema_detailed(schema: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate schema and return detailed errors and warnings.

    Returns:
        Tuple of (errors, warnings) where each is a list of dicts with 'path' and 'message' keys.
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not isinstance(schema, dict):
        errors.append({"path": "", "message": "Schema must be a JSON object"})
        return errors, warnings

    # Check required top-level keys
    for key in ("name", "version", "root", "fields"):
        if key not in schema:
            errors.append({"path": key, "message": f"Missing required key: {key}"})

    # Check name
    if "name" in schema:
        name = schema["name"]
        if not isinstance(name, str) or not name.strip():
            errors.append({"path": "name", "message": "Name must be a non-empty string"})
        elif not name.replace("_", "").replace("-", "").isalnum():
            warnings.append({"path": "name", "message": "Name should only contain alphanumeric characters, underscores, and hyphens"})

    # Check version
    if "version" in schema:
        version = schema["version"]
        if not isinstance(version, int) or version < 1:
            errors.append({"path": "version", "message": "Version must be a positive integer"})

    # Check description
    if "description" not in schema or not schema.get("description"):
        warnings.append({"path": "description", "message": "Consider adding a description"})

    # Check prompt
    if "prompt" in schema:
        prompt = schema["prompt"]
        if not isinstance(prompt, dict):
            errors.append({"path": "prompt", "message": "Prompt must be an object"})
        else:
            if "system" not in prompt or not prompt.get("system"):
                warnings.append({"path": "prompt.system", "message": "Consider adding a system prompt"})
            if "instructions" not in prompt or not prompt.get("instructions"):
                warnings.append({"path": "prompt.instructions", "message": "Consider adding instructions"})

    # Check root configuration
    if "root" in schema:
        root = schema["root"]
        if not isinstance(root, dict):
            errors.append({"path": "root", "message": "Root must be an object"})
        else:
            if "table" not in root:
                errors.append({"path": "root.table", "message": "Root must define a table name"})
            elif not root["table"] or not isinstance(root["table"], str):
                errors.append({"path": "root.table", "message": "Table name must be a non-empty string"})

            if "document_fk" not in root:
                errors.append({"path": "root.document_fk", "message": "Root must define document_fk"})
            else:
                doc_fk = root["document_fk"]
                if not isinstance(doc_fk, dict):
                    errors.append({"path": "root.document_fk", "message": "document_fk must be an object"})
                else:
                    if "column" not in doc_fk:
                        errors.append({"path": "root.document_fk.column", "message": "document_fk must define column"})
                    if "references" not in doc_fk:
                        errors.append({"path": "root.document_fk.references", "message": "document_fk must define references"})

    # Check fields
    if "fields" in schema:
        fields = schema["fields"]
        if not isinstance(fields, list):
            errors.append({"path": "fields", "message": "Fields must be a list"})
        elif len(fields) == 0:
            warnings.append({"path": "fields", "message": "Schema has no fields defined"})
        else:
            field_names = set()
            for i, field in enumerate(fields):
                field_path = f"fields[{i}]"
                field_errors, field_warnings = _validate_field_detailed(field, field_path)
                errors.extend(field_errors)
                warnings.extend(field_warnings)

                # Check for duplicate field names
                if "name" in field:
                    if field["name"] in field_names:
                        errors.append({"path": f"{field_path}.name", "message": f"Duplicate field name: {field['name']}"})
                    field_names.add(field["name"])

    return errors, warnings


def _validate_field_detailed(field: dict[str, Any], path: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate a single field and return errors/warnings."""
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not isinstance(field, dict):
        errors.append({"path": path, "message": "Field must be an object"})
        return errors, warnings

    # Check required field properties
    if "name" not in field:
        errors.append({"path": f"{path}.name", "message": "Field must have a name"})
    elif not field["name"] or not isinstance(field["name"], str):
        errors.append({"path": f"{path}.name", "message": "Field name must be a non-empty string"})

    if "type" not in field:
        errors.append({"path": f"{path}.type", "message": "Field must have a type"})
    else:
        field_type = field["type"]
        if field_type not in SUPPORTED_FIELD_TYPES:
            errors.append({"path": f"{path}.type", "message": f"Unsupported field type: {field_type}"})

    # Check description
    if "description" not in field or not field.get("description"):
        warnings.append({"path": f"{path}.description", "message": "Consider adding a field description"})

    # Check SQL mapping
    if "sql" not in field:
        errors.append({"path": f"{path}.sql", "message": "Field must have sql mapping"})
    else:
        sql = field["sql"]
        if not isinstance(sql, dict):
            errors.append({"path": f"{path}.sql", "message": "SQL mapping must be an object"})
        else:
            if "table" not in sql:
                errors.append({"path": f"{path}.sql.table", "message": "SQL mapping must define table"})

            field_type = field.get("type", "")
            if field_type == "array":
                if "columns" not in sql:
                    errors.append({"path": f"{path}.sql.columns", "message": "Array field must define sql.columns"})
                if "fk" not in sql:
                    errors.append({"path": f"{path}.sql.fk", "message": "Array field must define sql.fk"})
                elif not isinstance(sql["fk"], dict) or "column" not in sql["fk"]:
                    errors.append({"path": f"{path}.sql.fk.column", "message": "sql.fk must define column"})
            else:
                if "column" not in sql:
                    errors.append({"path": f"{path}.sql.column", "message": "Non-array field must define sql.column"})

    # Check array items
    field_type = field.get("type", "")
    if field_type == "array":
        if "items" not in field:
            errors.append({"path": f"{path}.items", "message": "Array field must define items"})
        else:
            items = field["items"]
            if not isinstance(items, dict):
                errors.append({"path": f"{path}.items", "message": "Items must be an object"})
            elif items.get("type") == "object":
                if "fields" not in items or not items.get("fields"):
                    warnings.append({"path": f"{path}.items.fields", "message": "Object items should define fields"})
                else:
                    for j, sub_field in enumerate(items.get("fields", [])):
                        sub_path = f"{path}.items.fields[{j}]"
                        # Basic validation for sub-fields
                        if "name" not in sub_field:
                            errors.append({"path": f"{sub_path}.name", "message": "Sub-field must have a name"})
                        if "type" not in sub_field:
                            errors.append({"path": f"{sub_path}.type", "message": "Sub-field must have a type"})

    # Check merge strategy
    if "merge" in field:
        merge = field["merge"]
        if not isinstance(merge, dict):
            errors.append({"path": f"{path}.merge", "message": "Merge must be an object"})
        else:
            strategy = merge.get("strategy", "")
            valid_strategies = {"first_non_empty", "union_unique", "union_by_key", "concat"}
            if strategy and strategy not in valid_strategies:
                errors.append({"path": f"{path}.merge.strategy", "message": f"Invalid merge strategy: {strategy}"})
            if strategy == "union_by_key" and not merge.get("key_fields"):
                errors.append({"path": f"{path}.merge.key_fields", "message": "union_by_key strategy requires key_fields"})

    return errors, warnings


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
