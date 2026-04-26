"""
main.py — CLI entry point.

Usage:
  python backend/main.py list-agents
  python backend/main.py run-case test_case_1 [--mode mock|live] [--model claude-haiku-4-5-20251001]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from agents import list_loaded, load_agents
from orchestrator import build
from protocol import load_protocol


def cmd_list_agents(args):
    agents = load_agents()
    print(f"Loaded {len(agents)} agents:")
    print(list_loaded(agents))
    protocol = load_protocol()
    intents = protocol.get("properties", {}).get("intents", {}).get("properties", {})
    print(f"\nProtocol: {len(intents)} intents in catalog.")


def cmd_run_case(args):
    case_path = Path("test_harness/cases") / f"{args.case}.json"
    if not case_path.exists():
        print(f"Test case not found: {case_path}", file=sys.stderr)
        sys.exit(1)
    with case_path.open() as f:
        case = json.load(f)

    print(f"Test case: {case.get('name', args.case)}")
    print(f"Mode: {args.mode}")
    print(f"Steps: {len(case['steps'])}")
    print()

    orchestrator = build(model_mode=args.mode, model_name=args.model)

    # Submit all initial steps. Each step in the test case is a flat envelope-ish dict.
    # We coerce to a full envelope by adding metadata if missing.
    for i, step in enumerate(case["steps"], start=1):
        envelope = _coerce_to_envelope(step, default_correlation_id=case.get("name", args.case))
        print(f"[step {i}] submit  to={envelope['to_agent_id']:25s}  intent={envelope['intent']}")
        orchestrator.submit(envelope)

    orchestrator.run_until_drained()

    print()
    print(f"Processed. {len(orchestrator.responses)} responses collected.")
    print(f"Event log: logs/events.jsonl ({orchestrator.event_log.events_path.stat().st_size} bytes)")
    print()
    print("=== Responses ===")
    for i, r in enumerate(orchestrator.responses, start=1):
        status = r.get("status", "?")
        intent = r.get("intent") or r.get("result", {}).get("handled_intent", "—")
        print(f"  [{i}] status={status}  intent={intent}")

    # Exit non-zero if any response had ERROR status
    error_count = sum(1 for r in orchestrator.responses if r.get("status") == "ERROR")
    if error_count:
        print(f"\n{error_count} error response(s).", file=sys.stderr)
        sys.exit(2)


def _coerce_to_envelope(step: dict, default_correlation_id: str) -> dict:
    """Test cases use flat dicts; ensure they have a metadata block."""
    if "metadata" not in step:
        step = dict(step)  # shallow copy
        step["metadata"] = {
            "correlation_id": f"case-{default_correlation_id}",
            "priority": "NORMAL",
            "sensitivity": "INTERNAL",
            "persist": True,
        }
    if "timestamp" not in step:
        from datetime import datetime, timezone
        step["timestamp"] = datetime.now(timezone.utc).isoformat()
    return step


def main():
    parser = argparse.ArgumentParser(prog="agentic-bus", description="Agentic Business System orchestrator")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list-agents", help="List loaded agents and prompt status")
    p_list.set_defaults(func=cmd_list_agents)

    p_run = sub.add_parser("run-case", help="Run a test case end-to-end")
    p_run.add_argument("case", help="Test case name (e.g. test_case_1)")
    p_run.add_argument("--mode", choices=["mock", "live"], default="mock")
    p_run.add_argument("--model", default=None, help="Anthropic model ID (live mode only)")
    p_run.set_defaults(func=cmd_run_case)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
