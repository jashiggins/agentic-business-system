"""
protocol.py — Load the agent protocol schema and validate envelopes.
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROTOCOL_PATH = Path("schemas/agent_protocol.json")


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


def validate_envelope(envelope: Dict[str, Any], protocol: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate a message envelope against the protocol's envelope_schema.
    Returns (is_valid, list_of_error_messages).

    Uses jsonschema if available; falls back to basic structural checks otherwise.
    """
    errors: List[str] = []
    schema = protocol.get("properties", {}).get("envelope_schema", {})
    required = schema.get("required", [])
    for field in required:
        if field not in envelope:
            errors.append(f"missing required field: {field}")
    intent = envelope.get("intent")
    if intent and intent not in known_intents(protocol):
        # Soft warning — protocol allows additionalProperties on the catalog.
        # We log but don't reject; this matches the protocol's design.
        errors.append(f"unknown intent (warning): {intent}")
    try:
        import jsonschema
        try:
            jsonschema.Draft7Validator(schema).validate(envelope)
        except jsonschema.ValidationError as e:
            errors.append(f"schema: {e.message}")
    except ImportError:
        pass

    # Treat 'unknown intent (warning)' as non-fatal; everything else is fatal.
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
    """Construct a well-formed envelope with sensible defaults."""
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
