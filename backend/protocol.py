"""
protocol.py — Load the agent protocol schema and validate envelopes.

Now also validates `payload` against a per-intent payload schema when the
catalog entry includes `payload_schema_ref`. Schemas referenced this way are
loaded relative to schemas/.
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROTOCOL_PATH = Path("schemas/agent_protocol.json")
SCHEMAS_DIR = Path("schemas")

# Cache loaded payload schemas by ref so we don't re-read on every call
_payload_schema_cache: Dict[str, Dict[str, Any]] = {}


def load_protocol(path: Path = PROTOCOL_PATH) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def known_intents(protocol: Dict[str, Any]) -> List[str]:
    return list(
        protocol.get("properties", {})
        .get("intents", {})
        .get("properties", {})
        .keys()
    )


def _payload_schema_for(intent: str, protocol: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the payload schema for an intent if the catalog defines one."""
    catalog = (
        protocol.get("properties", {})
        .get("intents", {})
        .get("properties", {})
    )
    entry = catalog.get(intent, {})
    ref = entry.get("payload_schema_ref")
    if not ref:
        return None
    if ref in _payload_schema_cache:
        return _payload_schema_cache[ref]
    full_path = SCHEMAS_DIR / ref
    if not full_path.exists():
        return None
    schema = json.loads(full_path.read_text(encoding="utf-8"))
    _payload_schema_cache[ref] = schema
    return schema


def validate_envelope(envelope: Dict[str, Any], protocol: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate envelope structure AND, if a payload_schema_ref is registered for
    the intent, validate the payload against that schema as well.
    Returns (is_valid, list_of_error_messages). Unknown intents are warnings.
    """
    errors: List[str] = []
    schema = protocol.get("properties", {}).get("envelope_schema", {})
    required = schema.get("required", [])
    for field in required:
        if field not in envelope:
            errors.append(f"missing required field: {field}")
    intent = envelope.get("intent")
    if intent and intent not in known_intents(protocol):
        errors.append(f"unknown intent (warning): {intent}")

    try:
        import jsonschema
        try:
            jsonschema.Draft7Validator(schema).validate(envelope)
        except jsonschema.ValidationError as e:
            errors.append(f"schema: {e.message}")

        # Per-intent payload validation
        if intent:
            pschema = _payload_schema_for(intent, protocol)
            if pschema is not None:
                payload = envelope.get("payload", {})
                for e in jsonschema.Draft7Validator(pschema).iter_errors(payload):
                    path = ".".join(str(p) for p in e.absolute_path) or "(root)"
                    errors.append(f"payload[{intent}]: {path}: {e.message}")
    except ImportError:
        pass

    fatal = [e for e in errors if not e.startswith("unknown intent")]
    return (len(fatal) == 0, errors)


def new_envelope(
    from_agent_id: str,
    to_agent_id: str,
    intent: str,
    payload: Dict[str, Any],
    correlation_id: Optional[str] = None,
    priority: str = "NORMAL",
    sensitivity: str = "INTERNAL",
    requires_security_review: bool = False,
) -> Dict[str, Any]:
    return {
        "message_id": f"msg-{uuid.uuid4().hex[:12]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "from_agent_id": from_agent_id,
        "to_agent_id": to_agent_id,
        "intent": intent,
        "payload": payload,
        "metadata": {
            "correlation_id": correlation_id or f"thread-{uuid.uuid4().hex[:8]}",
            "priority": priority,
            "sensitivity": sensitivity,
            "requires_security_review": requires_security_review,
            "persist": True,
        },
    }
