"""
router.py — Backward-compatible thin wrapper around the orchestrator.

The original backend/router.py exposed a route_message() function. New code
should use orchestrator.Orchestrator directly. This shim is kept so any old
imports don't break.
"""
from typing import Any, Dict


def route_message(message: Dict[str, Any], agents: Dict[str, Any]) -> Dict[str, Any]:
    """Deprecated. Use orchestrator.Orchestrator.submit() instead."""
    target = message["to_agent_id"]
    agent = agents.get(target)
    if agent is None:
        return {"status": "ERROR", "error": {"code": "UNKNOWN_AGENT"}}
    if hasattr(agent, "config"):
        return {"status": "OK", "result": {"agent_id": target, "echoed": message}}
    return {"status": "ERROR", "error": {"code": "AGENT_NOT_CALLABLE"}}
