"""
main.py — CLI entry point.

Usage:
  python backend/main.py list-agents
  python backend/main.py run-case <case_name> [--mode mock|live] [--model <id>]
  python backend/main.py list-approvals
  python backend/main.py approve <approval_id> [--comments "..."]
  python backend/main.py deny <approval_id> [--comments "..."]
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

from agents import list_loaded, load_agents
from approvals import ApprovalStore
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

    for i, step in enumerate(case["steps"], start=1):
        envelope = _coerce_to_envelope(step, default_correlation_id=case.get("name", args.case))
        print(f"[step {i}] submit  to={envelope['to_agent_id']:25s}  intent={envelope['intent']}")
        orchestrator.submit(envelope)

    orchestrator.run_until_drained()

    print()
    print(f"Processed. {len(orchestrator.responses)} responses collected.")
    print(f"Event log: logs/events.jsonl ({orchestrator.event_log.events_path.stat().st_size} bytes)")

    # Show parked approvals if any
    pending = orchestrator.approval_store.list_pending()
    if pending:
        print(f"\n{len(pending)} approval(s) pending human decision:")
        for p in pending:
            aid = p["approval_id"]
            ctx = p["envelope"].get("payload", {}).get("context_summary", "(no context)")
            print(f"  - {aid}: {ctx[:80]}")
        print(f"\nResolve with:  python backend/main.py approve <id>  |  deny <id>")
        print(f"Then re-run the case to feed the response back to the originating agent.")

    print()
    print("=== Responses ===")
    for i, r in enumerate(orchestrator.responses, start=1):
        status = r.get("status", "?")
        intent = r.get("intent") or r.get("result", {}).get("handled_intent", "—")
        print(f"  [{i}] status={status}  intent={intent}")

    error_count = sum(1 for r in orchestrator.responses if r.get("status") == "ERROR")
    if error_count:
        print(f"\n{error_count} error response(s).", file=sys.stderr)
        sys.exit(2)


def cmd_list_approvals(args):
    store = ApprovalStore()
    pending = store.list_pending()
    if not pending:
        print("No pending approvals.")
        return
    print(f"{len(pending)} pending approval(s):\n")
    for p in pending:
        aid = p["approval_id"]
        env = p["envelope"]
        payload = env.get("payload", {})
        print(f"approval_id:     {aid}")
        print(f"  from_agent:    {env.get('from_agent_id', '?')}")
        print(f"  parked_at:     {p.get('parked_at', '?')}")
        print(f"  context:       {payload.get('context_summary', '(none)')}")
        print(f"  options:       {payload.get('options', [])}")
        print(f"  expires_at:    {payload.get('expires_at', 'none')}")
        print(f"  related_id:    {payload.get('related_request_id', 'none')}")
        print()


def cmd_resolve(args, decision: str):
    store = ApprovalStore()
    try:
        envelope = store.resolve(args.approval_id, decision, comments=args.comments or "")
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    print(f"{decision.upper()}: {args.approval_id}")
    print(f"USER_APPROVAL_RESPONSE envelope written to logs/approvals/responses/{args.approval_id}.json")
    print(f"Re-run the case (or run-case the originating workflow) to deliver this response to {envelope['to_agent_id']}.")


def cmd_approve(args):
    cmd_resolve(args, "approve")


def cmd_deny(args):
    cmd_resolve(args, "deny")


def _coerce_to_envelope(step: dict, default_correlation_id: str) -> dict:
    if "metadata" not in step:
        step = dict(step)
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
    p_run.add_argument("case")
    p_run.add_argument("--mode", choices=["mock", "live"], default="mock")
    p_run.add_argument("--model", default=None)
    p_run.set_defaults(func=cmd_run_case)

    p_la = sub.add_parser("list-approvals", help="List pending USER_APPROVAL_REQUEST items awaiting human decision")
    p_la.set_defaults(func=cmd_list_approvals)

    p_app = sub.add_parser("approve", help="Approve a pending USER_APPROVAL_REQUEST")
    p_app.add_argument("approval_id")
    p_app.add_argument("--comments", default="")
    p_app.set_defaults(func=cmd_approve)

    p_den = sub.add_parser("deny", help="Deny a pending USER_APPROVAL_REQUEST")
    p_den.add_argument("approval_id")
    p_den.add_argument("--comments", default="")
    p_den.set_defaults(func=cmd_deny)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
