"""
orchestrator.py — Receive a message, dispatch to agent, validate, log.

This is intentionally minimal. It is not durable, distributed, or transactional.
Future work: replace the in-memory queue with Redis Streams or NATS, replace
EventLog with Postgres, add at-least-once semantics, retries, and DLQ.

What it DOES today:
  - Loads all agents (JSON metadata + system prompts)
  - Loads the protocol schema and validates every envelope
  - Maintains a FIFO queue of pending messages
  - Calls the configured model (mock or live) for each message
  - Logs every event to logs/events.jsonl
  - Stops when the queue drains
"""
from __future__ import annotations
import json
from collections import deque
from typing import Any, Deque, Dict, List

from agents import Agent, load_agents
from model_client import ModelClient, MockModel
from protocol import load_protocol, validate_envelope
from storage import EventLog


class Orchestrator:
    def __init__(
        self,
        model: ModelClient,
        agents: Dict[str, Agent],
        protocol: Dict[str, Any],
        event_log: EventLog,
    ):
        self.model = model
        self.agents = agents
        self.protocol = protocol
        self.event_log = event_log
        self.queue: Deque[Dict[str, Any]] = deque()
        self.responses: List[Dict[str, Any]] = []

    def submit(self, envelope: Dict[str, Any]) -> None:
        ok, errors = validate_envelope(envelope, self.protocol)
        self.event_log.append(
            "envelope_submitted",
            {"envelope": envelope, "valid": ok, "errors": errors},
        )
        if not ok:
            self.event_log.append("envelope_rejected", {"envelope": envelope, "errors": errors})
            self.responses.append(
                {
                    "status": "ERROR",
                    "in_reply_to": envelope.get("message_id"),
                    "error": {"code": "INVALID_ENVELOPE", "details": errors},
                }
            )
            return
        self.queue.append(envelope)

    def run_until_drained(self, max_steps: int = 50) -> None:
        steps = 0
        while self.queue and steps < max_steps:
            envelope = self.queue.popleft()
            self._dispatch(envelope)
            steps += 1
        if self.queue:
            self.event_log.append(
                "queue_overflow",
                {"remaining": len(self.queue), "max_steps": max_steps},
            )

    def _dispatch(self, envelope: Dict[str, Any]) -> None:
        target_id = envelope.get("to_agent_id")
        agent = self.agents.get(target_id)
        if agent is None:
            # External endpoint: any target not starting with agent_ is treated as
            # an external service (data store, payment processor, email server, etc.)
            # We auto-ack and log; real implementations would forward to a webhook.
            if target_id and not target_id.startswith("agent_"):
                self.event_log.append(
                    "external_dispatch",
                    {"to": target_id, "intent": envelope.get("intent"), "message_id": envelope.get("message_id")},
                )
                self.responses.append({
                    "status": "OK",
                    "in_reply_to": envelope.get("message_id"),
                    "result": {
                        "endpoint": target_id,
                        "handled_intent": envelope.get("intent"),
                        "note": f"[external] {target_id} acknowledged {envelope.get("intent")}",
                    },
                })
                return
            # Unknown agent_-prefixed target is a real error.
            self.event_log.append(
                "dispatch_failed",
                {"reason": "unknown_agent", "to_agent_id": target_id, "envelope": envelope},
            )
            self.responses.append(
                {
                    "status": "ERROR",
                    "in_reply_to": envelope.get("message_id"),
                    "error": {"code": "UNKNOWN_AGENT", "to_agent_id": target_id},
                }
            )
            return

        self.event_log.append(
            "dispatch", {"to": target_id, "intent": envelope.get("intent"), "message_id": envelope.get("message_id")}
        )

        try:
            response = self.model.call_agent(
                agent_id=agent.id,
                system_prompt=agent.system_prompt or "",
                incoming_envelope=envelope,
            )
        except Exception as e:
            self.event_log.append(
                "model_error",
                {"agent_id": agent.id, "error": str(e), "envelope": envelope},
            )
            self.responses.append(
                {
                    "status": "ERROR",
                    "in_reply_to": envelope.get("message_id"),
                    "error": {"code": "MODEL_ERROR", "message": str(e)},
                }
            )
            return

        self.event_log.append(
            "agent_response",
            {"agent_id": agent.id, "response": response},
        )
        self.responses.append(response)

        # If the response is itself a fully-formed envelope (has to_agent_id),
        # enqueue it for further routing. This is how multi-hop flows work.
        if isinstance(response, dict) and response.get("to_agent_id") and response.get("intent"):
            ok, errors = validate_envelope(response, self.protocol)
            if ok:
                self.queue.append(response)
            else:
                self.event_log.append(
                    "follow_up_invalid",
                    {"response": response, "errors": errors},
                )


def build(model_mode: str = "mock", model_name: str = None) -> Orchestrator:
    """Convenience factory."""
    agents = load_agents()
    protocol = load_protocol()
    event_log = EventLog()
    if model_mode == "mock":
        model = MockModel()
    elif model_mode == "live":
        from model_client import AnthropicModel
        model = AnthropicModel(model=model_name) if model_name else AnthropicModel()
    else:
        raise ValueError(f"Unknown model_mode: {model_mode}")
    return Orchestrator(model=model, agents=agents, protocol=protocol, event_log=event_log)
