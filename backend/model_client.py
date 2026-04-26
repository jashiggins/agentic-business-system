"""
model_client.py — Pluggable Claude client.

Two implementations:
  - MockModel: deterministic canned responses, no API calls. Free, fast.
  - AnthropicModel: calls real Anthropic API. Requires ANTHROPIC_API_KEY env var.

The orchestrator picks one at startup based on --mode flag.
"""
from __future__ import annotations
import json
import os
import re
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class ModelClient(ABC):
    @abstractmethod
    def call_agent(
        self,
        agent_id: str,
        system_prompt: str,
        incoming_envelope: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Return a response envelope or response object as a dict.
        """
        ...


class MockModel(ModelClient):
    """
    Deterministic mock. Produces a plausible response envelope based on the
    incoming intent. Lets us test the full orchestrator wiring without API calls.
    """

    def call_agent(
        self,
        agent_id: str,
        system_prompt: str,
        incoming_envelope: Dict[str, Any],
    ) -> Dict[str, Any]:
        intent = incoming_envelope.get("intent", "UNKNOWN")
        correlation_id = incoming_envelope.get("metadata", {}).get(
            "correlation_id", f"thread-{uuid.uuid4().hex[:8]}"
        )
        in_reply_to = incoming_envelope.get("message_id", "unknown")

        # Default: acknowledgment response (no follow-up message)
        ack = {
            "message_id": f"msg-{uuid.uuid4().hex[:12]}",
            "in_reply_to": in_reply_to,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "OK",
            "result": {
                "agent_id": agent_id,
                "handled_intent": intent,
                "note": f"[mock] {agent_id} acknowledges {intent}",
            },
        }
        return ack


class AnthropicModel(ModelClient):
    """
    Real Claude API call. Requires `pip install anthropic` and ANTHROPIC_API_KEY.
    """

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        try:
            import anthropic
        except ImportError as e:
            raise ImportError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from e
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY environment variable not set. "
                "Get a key from console.anthropic.com and: setx ANTHROPIC_API_KEY <your-key>"
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def call_agent(
        self,
        agent_id: str,
        system_prompt: str,
        incoming_envelope: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not system_prompt:
            # No prompt loaded for this agent; degrade to mock-style ack.
            return MockModel().call_agent(agent_id, system_prompt, incoming_envelope)

        user_message = (
            "You have received the following message envelope. "
            "Respond with a single JSON object — either an outgoing envelope "
            "or a response object per your system prompt. No prose outside the JSON.\n\n"
            "Incoming envelope:\n```json\n"
            + json.dumps(incoming_envelope, indent=2)
            + "\n```"
        )

        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        ).strip()

        return _parse_json_from_response(text, fallback_in_reply_to=incoming_envelope.get("message_id"))


def _parse_json_from_response(text: str, fallback_in_reply_to: Optional[str] = None) -> Dict[str, Any]:
    """
    Try hard to extract a JSON object from the model's response. Models sometimes
    wrap output in ```json ... ``` fences or add stray prose despite instructions.
    """
    # Strip markdown code fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    else:
        # Take first { ... } block at top level
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1:
            candidate = text[first_brace : last_brace + 1]
        else:
            candidate = text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return {
            "message_id": f"msg-parse-error-{uuid.uuid4().hex[:8]}",
            "in_reply_to": fallback_in_reply_to or "unknown",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "ERROR",
            "result": {"raw_text": text[:500]},
            "error": {
                "code": "MODEL_OUTPUT_NOT_JSON",
                "message": "Could not parse model response as JSON envelope.",
            },
        }
