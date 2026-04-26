"""
main.py — CLI entry point.

Usage:
  python backend/main.py list-agents
  python backend/main.py run-case <case_name> [--mode mock|live] [--model <id>]
  python backend/main.py list-approvals
  python backend/main.py approve <approval_id> [--comments "..."]
  python backend/main.py deny <approval_id> [--comments "..."]
  python backend/main.py events [--type ...] [--corr ...] [--agent ...] [--intent ...] [--message-id ...] [--limit N]
  python backend/main.py event-stats
  python backend/main.py sweep-approvals
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
from storage import EventLog


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

    # Auto-sweep expired approvals before run; their auto-resolved
    # responses will be replayed by the orchestrator on startup.
    _do_sweep(quiet=False)

    orchestrator = build(model_mode=args.mode, model_name=args.model)

    for i, step in enumerate(case["steps"], start=1):
        envelope = _coerce_to_envelope(step, default_correlation_id=case.get("name", args.case))
        print(f"[step {i}] submit  to={envelope['to_agent_id']:25s}  intent={envelope['intent']}")
        orchestrator.submit(envelope)

    orchestrator.run_until_drained()

    print()
    print(f"Processed. {len(orchestrator.responses)} responses collected.")
    db_size = orchestrator.event_log.db_path.stat().st_size if orchestrator.event_log.db_path.exists() else 0
    jsonl_size = orchestrator.event_log.events_path.stat().st_size if orchestrator.event_log.events_path.exists() else 0
    print(f"Event log: SQLite {db_size}B / JSONL mirror {jsonl_size}B (logs/events.db, logs/events.jsonl)")

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
        print(str(e), file=sys.stderr); sys.exit(1)
    except ValueError as e:
        print(str(e), file=sys.stderr); sys.exit(1)
    print(f"{decision.upper()}: {args.approval_id}")
    print(f"USER_APPROVAL_RESPONSE envelope written to logs/approvals/responses/{args.approval_id}.json")
    print(f"Re-run the case (or run-case the originating workflow) to deliver this response to {envelope['to_agent_id']}.")


def cmd_approve(args):
    cmd_resolve(args, "approve")


def cmd_deny(args):
    cmd_resolve(args, "deny")


def _do_sweep(quiet: bool = False):
    """Run the expiry sweep, print summary unless quiet, return list of swept items."""
    store = ApprovalStore()
    swept = store.sweep_expired()
    if swept and not quiet:
        print(f"Auto-resolved {len(swept)} expired approval(s):")
        for s in swept:
            print(f"  - {s['approval_id']}: {s['decision'].upper()} (expires_at={s['expires_at']})")
    return swept


def cmd_sweep(args):
    swept = _do_sweep(quiet=False)
    if not swept:
        print("No expired approvals to sweep.")


def cmd_events(args):
    log = EventLog()
    rows = log.query(
        event_type=args.type,
        correlation_id=args.corr,
        agent_id=args.agent,
        intent=args.intent,
        message_id=args.message_id,
        since=args.since,
        until=args.until,
        limit=args.limit,
    )
    if not rows:
        print("No matching events.")
        return
    print(f"{len(rows)} event(s) (limit={args.limit}):\n")
    for r in rows:
        line = f"#{r['id']:<5}  {r['timestamp']}  {r['event_type']:<25}"
        if r["correlation_id"]:
            line += f"  corr={r['correlation_id']}"
        if r["agent_id"]:
            line += f"  agent={r['agent_id']}"
        if r["intent"]:
            line += f"  intent={r['intent']}"
        if r["message_id"]:
            line += f"  msg={r['message_id']}"
        print(line)
        if args.full:
            print("    payload: " + json.dumps(r["payload"]))


def cmd_event_stats(args):
    log = EventLog()
    s = log.stats()
    print(f"Total events: {s['total']}\n")
    print("By event_type:")
    for k, v in s["by_event_type"].items():
        print(f"  {v:>6}  {k}")
    if s["top_correlations"]:
        print("\nTop correlation IDs (most events):")
        for k, v in s["top_correlations"].items():
            print(f"  {v:>6}  {k}")


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

    p_ev = sub.add_parser("events", help="Query the event log (SQLite)")
    p_ev.add_argument("--type", default=None, help="event_type filter")
    p_ev.add_argument("--corr", default=None, help="correlation_id filter")
    p_ev.add_argument("--agent", default=None, help="agent_id filter")
    p_ev.add_argument("--intent", default=None, help="intent filter")
    p_ev.add_argument("--message-id", default=None, help="message_id filter")
    p_ev.add_argument("--since", default=None, help="ISO8601 lower bound on ts_utc")
    p_ev.add_argument("--until", default=None, help="ISO8601 upper bound on ts_utc")
    p_ev.add_argument("--limit", type=int, default=50)
    p_ev.add_argument("--full", action="store_true", help="show full payload JSON for each event")
    p_ev.set_defaults(func=cmd_events)

    p_st = sub.add_parser("event-stats", help="Show event-log statistics")
    p_st.set_defaults(func=cmd_event_stats)

    p_sw = sub.add_parser("sweep-approvals", help="Auto-resolve expired pending approvals using their default_on_expiry policy")
    p_sw.set_defaults(func=cmd_sweep)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
