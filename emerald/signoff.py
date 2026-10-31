"""Vet sign-off. An approval is a signature over the exact action, so changing any detail voids it."""

from __future__ import annotations

import hashlib
import json
import uuid

from . import db, keys, ledger

# Everything that cannot be undone once done. These tools refuse to run without a valid signature.
IRREVERSIBLE = {"prescribe_treatment", "pay_vet_consult", "file_outbreak_report", "start_ring_calls"}


def action_hash(case_id: str, tool: str, args: dict) -> str:
    # 300 and 300.0 are the same amount, but models and tool schemas don't agree on which one they send.
    clean = {k: float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v
             for k, v in args.items() if k != "signoff_id"}
    return hashlib.sha256(ledger.canonical([case_id, tool, clean]).encode()).hexdigest()


def request(case_id: str, tool: str, args: dict, summary: str) -> dict:
    """Idempotent: asking again for an identical action returns the same request."""
    digest = action_hash(case_id, tool, args)
    clean = {k: v for k, v in args.items() if k != "signoff_id"}
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM signoffs WHERE case_id=? AND action_hash=?", (case_id, digest)).fetchone()
        if row:
            return dict(row)
        sid = "SO-" + uuid.uuid4().hex[:8]
        conn.execute(
            "INSERT INTO signoffs (id, case_id, tool, args, action_hash, summary, requested_at) VALUES (?,?,?,?,?,?,?)",
            (sid, case_id, tool, json.dumps(clean, sort_keys=True), digest, summary, ledger.now()),
        )
    ledger.append("signoff_requested", {"signoff_id": sid, "tool": tool, "args": clean, "action_hash": digest}, case_id)
    return get(sid)


def get(signoff_id: str) -> dict:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM signoffs WHERE id=?", (signoff_id,)).fetchone()
    if row is None:
        raise KeyError(signoff_id)
    return dict(row)


def pending() -> list[dict]:
    with db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM signoffs WHERE status='pending' ORDER BY requested_at")]


def decide(signoff_id: str, vet_id: str, pin: str, approve: bool, note: str = "") -> dict:
    """Called from the vet's channel (phone keypad or console). No agent tool leads here."""
    if not keys.check_pin(vet_id, pin):
        ledger.append("signoff_rejected_bad_pin", {"signoff_id": signoff_id, "vet_id": vet_id}, get(signoff_id)["case_id"])
        return {"status": "refused", "reason": "PIN does not match this vet"}
    item = get(signoff_id)
    if item["status"] != "pending":
        return {"status": "refused", "reason": f"this request is already {item['status']}"}
    status = "approved" if approve else "declined"
    signature = keys.sign(vet_id, item["action_hash"]) if approve else None
    with db.connect() as conn:
        conn.execute(
            "UPDATE signoffs SET status=?, vet_id=?, signature=?, note=?, decided_at=? WHERE id=?",
            (status, vet_id, signature, note, ledger.now(), signoff_id),
        )
    ledger.append(f"signoff_{status}", {"signoff_id": signoff_id, "vet_id": vet_id, "note": note,
                                        "action_hash": item["action_hash"], "signature": signature}, item["case_id"])
    return {"status": status, "signoff_id": signoff_id}


def consume(signoff_id: str) -> bool:
    """A signature authorises one action, once. Atomic, so two callers can't both spend it."""
    with db.connect() as conn:
        done = conn.execute("UPDATE signoffs SET used_at=? WHERE id=? AND used_at IS NULL", (ledger.now(), signoff_id))
        return done.rowcount == 1


def is_valid(signoff_id: str, case_id: str, tool: str, args: dict) -> tuple[bool, str]:
    """Run by the tool itself. Does not trust the agent, the hook, or the status column alone."""
    try:
        item = get(signoff_id)
    except KeyError:
        return False, "no such sign-off"
    if item["status"] != "approved" or not item["signature"]:
        return False, f"sign-off is {item['status']}"
    if item["case_id"] != case_id or item["tool"] != tool:
        return False, "sign-off is for a different action"
    digest = action_hash(case_id, tool, args)
    if digest != item["action_hash"]:
        return False, "the action changed after the vet approved it"
    if not keys.verify(keys.public_key_for(item["vet_id"]), digest, item["signature"]):
        return False, "vet signature is invalid"
    return True, "signed by " + item["vet_id"]
