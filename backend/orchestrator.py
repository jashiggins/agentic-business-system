"""
orchestrator.py — Receive a message, dispatch to agent, validate, log.

What it DOES today:
  - Loads all agents (JSON metadata + system prompts)
  - Loads the protocol schema and validates every envelope
  - Maintains a FIFO queue of pending messages with loop detection
  - Calls the configured model (mock or live) for each message
  - Logs every event to logs/events.jsonl
  - Parks USER_APPROVAL_REQUEST messages for human decision (HITL)
  - Replays USER_APPROVAL_RESPONSE envelopes from prior decisions on next run
  - Stops when the queue drains, max_steps reached, or a loop is detected

Loop prevention:
  - Response-only intents (OK/ERROR/PENDING/DEFERRED/ESCALATED) are TERMINAL.
  - Same (from_agent, to_agent, intent) triple within one correlation_id may
    repeat at most MAX_TRIPLE_REPEATS times before that triple is dropped.

Human-in-the-loop:
  - Envelopes with to_agent_id="external_user" AND intent="USER_APPROVAL_REQUEST"
    are PARKED to logs/approvals/pending/. The orchestrator emits a PENDING
    response and continues processing other queue items.
  - On startup, replays any USER_APPROVAL_RESPONSE envelopes left in
    logs/approvals/responses/ from prior CLI 'approve'/'deny' commands.
"""
from __future__ import annotations
import json
from collections import Counter, deque
from typing import Any, Deque, Dict, List

from agents import Agent, load_agents
from approvals import ApprovalStore
from model_client import ModelClient, MockModel
from protocol import load_protocol, validate_envelope
from storage import EventLog


TERMINAL_INTENTS = {"OK", "ERROR", "PENDING", "DEFERRED", "ESCALATED", "ACK"}
MAX_TRIPLE_REPEATS = 2


class Orchestrator:
    def __init__(
        self,
        model: ModelClient,
        agents: Dict[str, Agent],
        protocol: Dict[str, Any],
        event_log: EventLog,
        approval_store: ApprovalStore,
    ):
        self.model = model
        self.agents = agents
        self.protocol = protocol
        self.event_log = event_log
        self.approval_store = approval_store
        self.queue: Deque[Dict[str, Any]] = deque()
        self.responses: List[Dict[str, Any]] = []
        self._triple_counts: Counter = Counter()

        # On startup, inject any prior approval responses awaiting replay
        replay = self.approval_store.consume_responses()
        for env in replay:
            self.event_log.append(
                "approval_response_replayed",
                {"approval_id": env.get("payload", {}).get("approval_id"), "envelope": env},
            )
            self.queue.append(env)

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

    def _is_user_approval_request(self, envelope: Dict[str, Any]) -> bool:
        return (
            envelope.get("to_agent_id") == "external_user"
            and envelope.get("intent") == "USER_APPROVAL_REQUEST"
        )

    def _dispatch(self, envelope: Dict[str, Any]) -> None:
        target_id = envelope.get("to_agent_id")

        # HITL: park USER_APPROVAL_REQUEST instead of auto-acking
        if self._is_user_approval_request(envelope):
            approval_id = self.approval_store.park(envelope)
            self.event_log.append(
                "approval_parked",
                {
                    "approval_id": approval_id,
                    "from": envelope.get("from_agent_id"),
                    "context_summary": envelope.get("payload", {}).get("context_summary"),
                },
            )
            self.responses.append({
                "status": "PENDING",
                "in_reply_to": envelope.get("message_id"),
                "result": {
                    "approval_id": approval_id,
                    "note": (
                        f"USER_APPROVAL_REQUEST {approval_id} parked for human decision. "
                        f"Run 'python backend/main.py list-approvals' to view, "
                        f"'approve <id>' or 'deny <id>' to resolve."
                    ),
                },
            })
            return

        agent = self.agents.get(target_id)
        if agent is None:
            # External endpoint (non-agent_ target, not USER_APPROVAL_REQUEST)
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
                        "note": f"[external] {target_id} acknowledged {envelope.get('intent')}",
                    },
                })
                return
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
            "dispatch",
            {"to": target_id, "intent": envelope.get("intent"), "message_id": envelope.get("message_id")},
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

        self.event_log.append("agent_response", {"agent_id": agent.id, "response": response})
        self.responses.append(response)
        self._maybe_route_followup(response, source_agent_id=agent.id)

    def _maybe_route_followup(self, response: Dict[str, Any], source_agent_id: str) -> None:
        if not isinstance(response, dict):
            return
        to_id = response.get("to_agent_id")
        intent = response.get("intent")
        if not (to_id and intent):
            return
        if intent in TERMINAL_INTENTS:
            self.event_log.append(
                "followup_terminal",
                {"intent": intent, "from": source_agent_id, "to": to_id},
            )
            return
        ok, errors = validate_envelope(response, self.protocol)
        if not ok:
            self.event_log.append("follow_up_invalid", {"response": response, "errors": errors})
            return
        corr = response.get("metadata", {}).get("correlation_id", "—")
        from_id = response.get("from_agent_id", source_agent_id)
        triple = (corr, from_id, to_id, intent)
        self._triple_counts[triple] += 1
        if self._triple_counts[triple] > MAX_TRIPLE_REPEATS:
            self.event_log.append(
                "loop_detected",
                {"correlation_id": corr, "from": from_id, "to": to_id, "intent": intent,
                 "count": self._triple_counts[triple], "action": "dropped"},
            )
            return
        self.queue.append(response)


def build(model_mode: str = "mock", model_name: str = None) -> Orchestrator:
    agents = load_agents()
    protocol = load_protocol()
    event_log = EventLog()
    approval_store = ApprovalStore()
    if model_mode == "mock":
        model = MockModel()
    elif model_mode == "live":
        from model_client import AnthropicModel
        model = AnthropicModel(model=model_name) if model_name else AnthropicModel()
    else:
        raise ValueError(f"Unknown model_mode: {model_mode}")
    return Orchestrator(
        model=model, agents=agents, protocol=protocol,
        event_log=event_log, approval_store=approval_store,
    )
