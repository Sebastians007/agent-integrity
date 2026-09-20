#!/usr/bin/env python3
"""Small machine-readable claim/evidence ledger for Agent Integrity Runtime.

The hook automatically records verification evidence in evidence.jsonl. This CLI
lets an agent or human register important claims and invalidate dependent claims
when a premise is disproved.
"""
from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

ROOT = Path.cwd().resolve()
STATE_DIR = ROOT / ".ai-integrity"
CLAIMS = STATE_DIR / "claims.json"
EVIDENCE = STATE_DIR / "evidence.jsonl"


def load_claims():
    try:
        data = json.loads(CLAIMS.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"schema": 1, "claims": []}
    except Exception:
        return {"schema": 1, "claims": []}


def save_claims(data):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CLAIMS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(CLAIMS)


def claim_map(data):
    return {c["id"]: c for c in data.get("claims", [])}


def cmd_add(args):
    data = load_claims()
    known = claim_map(data)
    for dep in args.depends_on:
        if dep not in known:
            raise SystemExit(f"Unknown dependency claim: {dep}")
    cid = args.id or f"cl-{uuid.uuid4().hex[:8]}"
    if cid in known:
        raise SystemExit(f"Claim already exists: {cid}")
    item = {
        "id": cid,
        "claim": args.claim,
        "status": args.status,
        "depends_on": args.depends_on,
        "evidence": args.evidence,
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
        "invalidated_by": None,
        "reason": None,
    }
    data.setdefault("claims", []).append(item)
    save_claims(data)
    print(cid)


def descendants(data, root_id):
    by_dep = {}
    for c in data.get("claims", []):
        for dep in c.get("depends_on", []):
            by_dep.setdefault(dep, []).append(c["id"])
    out, stack = set(), [root_id]
    while stack:
        cur = stack.pop()
        for child in by_dep.get(cur, []):
            if child not in out:
                out.add(child)
                stack.append(child)
    return out


def cmd_invalidate(args):
    data = load_claims()
    known = claim_map(data)
    if args.id not in known:
        raise SystemExit(f"Unknown claim: {args.id}")
    now = int(time.time())
    known[args.id]["status"] = "invalidated"
    known[args.id]["reason"] = args.reason
    known[args.id]["updated_at"] = now
    for cid in descendants(data, args.id):
        c = known[cid]
        if c.get("status") != "invalidated":
            c["status"] = "suspect"
            c["invalidated_by"] = args.id
            c["reason"] = f"Dependency {args.id} was invalidated"
            c["updated_at"] = now
    save_claims(data)
    print(json.dumps({"invalidated": args.id, "suspect_dependents": sorted(descendants(data, args.id))}))


def cmd_set_status(args):
    data = load_claims()
    known = claim_map(data)
    if args.id not in known:
        raise SystemExit(f"Unknown claim: {args.id}")
    known[args.id]["status"] = args.status
    known[args.id]["updated_at"] = int(time.time())
    if args.evidence:
        known[args.id]["evidence"] = list(dict.fromkeys((known[args.id].get("evidence") or []) + args.evidence))
    save_claims(data)
    print(args.id)


def cmd_show(args):
    data = load_claims()
    if args.id:
        item = claim_map(data).get(args.id)
        if not item:
            raise SystemExit(f"Unknown claim: {args.id}")
        print(json.dumps(item, indent=2, sort_keys=True))
    else:
        print(json.dumps(data, indent=2, sort_keys=True))


def cmd_evidence(args):
    if not EVIDENCE.exists():
        print("[]")
        return
    rows = []
    for line in EVIDENCE.read_text(encoding="utf-8").splitlines()[-args.limit:]:
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    print(json.dumps(rows, indent=2, sort_keys=True))


def main():
    ap = argparse.ArgumentParser(description="Agent Integrity evidence/claim ledger")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add-claim")
    p.add_argument("claim")
    p.add_argument("--id")
    p.add_argument("--status", choices=["unverified", "inferred", "verified", "observed", "suspect", "invalidated"], default="unverified")
    p.add_argument("--depends-on", action="append", default=[])
    p.add_argument("--evidence", action="append", default=[])
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("invalidate")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_invalidate)

    p = sub.add_parser("set-status")
    p.add_argument("id")
    p.add_argument("status", choices=["unverified", "inferred", "verified", "observed", "suspect", "invalidated"])
    p.add_argument("--evidence", action="append", default=[])
    p.set_defaults(fn=cmd_set_status)

    p = sub.add_parser("show")
    p.add_argument("id", nargs="?")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("evidence")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_evidence)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
