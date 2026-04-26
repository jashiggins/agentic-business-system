"""
approvals.py — Human-in-the-loop approval store.

Stores pending USER_APPROVAL_REQUEST envelopes to disk and allows resuming when
a human responds via CLI. Approval state is durable across orchestrator runs.

Layout:
  logs/approvals/pending/<approval_id>.json   — awaiting human decision
  logs/approvals/resolved/<approval_id>.json  — decided (approve/deny)
  logs/approvals/responses/<approval_id>.json — USER_APPROVAL_RESPONSE envelope
                                                ready to be fed back to the
                                                requesting agent on next run
"""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class ApprovalStore:
    def __init__(self, root: str = "logs/approvals"):
        self.root = Path(root)
        self.pending = self.root / "pending"
        self.resolved = self.root / "resolved"
        self.responses = self.root / "responses"
        for d in (self.pending, self.resolved, self.responses):
            d.mkdir(parents=True, exist_ok=True)

    # --- Writing pending requests ---

    def park(self, envelope: Dict[str, Any]) -> str:
        """
        Park a USER_APPROVAL_REQUEST envelope. Returns the approval_id used.
        If payload.approval_id is missing, generates one.
        """
        payload = envelope.get("payload", {})
        approval_id = payload.get("approval_id") or f"ua-{uuid.uuid4().hex[:10]}"
        record = {
            "approval_id": approval_id,
            "parked_at": datetime.now(timezone.utc).isoformat(),
            "envelope": envelope,
        }
        path = self.pending / f"{approval_id}.json"
        path.write_text(json.dumps(record, indent=2))
        return approval_id

    # --- Reading pending requests ---

    def list_pending(self) -> List[Dict[str, Any]]:
        out = []
        for p in sorted(self.pending.glob("*.json")):
            out.append(json.loads(p.read_text()))
        return out

    def get_pending(self, approval_id: str) -> Optional[Dict[str, Any]]:
        path = self.pending / f"{approval_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    # --- Resolving ---

    def resolve(self, approval_id: str, decision: str, comments: str = "") -> Dict[str, Any]:
        """
        Mark a pending approval as resolved. Decision must be 'approve' or 'deny'.
        Writes:
          - resolved/<id>.json (the decision record)
          - responses/<id>.json (the USER_APPROVAL_RESPONSE envelope to feed back)
        Removes:
          - pending/<id>.json
        """
        if decision not in ("approve", "deny"):
            raise ValueError(f"decision must be 'approve' or 'deny', got '{decision}'")
        pending = self.get_pending(approval_id)
        if pending is None:
            raise FileNotFoundError(f"No pending approval with id={approval_id}")

        original = pending["envelope"]
        decided_at = datetime.now(timezone.utc).isoformat()

        decision_record = {
            "approval_id": approval_id,
            "decision": decision,
            "comments": comments,
            "decided_at": decided_at,
            "original_envelope": original,
        }
        (self.resolved / f"{approval_id}.json").write_text(json.dumps(decision_record, indent=2))

        # Build the USER_APPROVAL_RESPONSE envelope routed back to the originator
        response_envelope = {
            "message_id": f"msg-ua-resp-{uuid.uuid4().hex[:10]}",
            "timestamp": decided_at,
            "from_agent_id": "external_user",
            "to_agent_id": original.get("from_agent_id", "agent_ceo"),
            "intent": "USER_APPROVAL_RESPONSE",
            "payload": {
                "approval_id": approval_id,
                "decision": decision,
                "responder_id": "user_owner",
                "comments": comments,
                "in_reply_to_message_id": original.get("message_id"),
                "in_reply_to_request_id": original.get("payload", {}).get("related_request_id"),
            },
            "metadata": {
                "correlation_id": original.get("metadata", {}).get("correlation_id", approval_id),
                "priority": original.get("metadata", {}).get("priority", "NORMAL"),
                "sensitivity": "CONFIDENTIAL",
                "persist": True,
            },
        }
        (self.responses / f"{approval_id}.json").write_text(json.dumps(response_envelope, indent=2))

        # Remove from pending
        (self.pending / f"{approval_id}.json").unlink()
        return response_envelope

    # --- Replay ---

    def consume_responses(self) -> List[Dict[str, Any]]:
        """
        Read and remove all response envelopes ready for replay. Used at run start
        to inject prior USER_APPROVAL_RESPONSE envelopes back into the queue.
        """
        envelopes = []
        for p in sorted(self.responses.glob("*.json")):
            envelopes.append(json.loads(p.read_text()))
            p.unlink()
        return envelopes
