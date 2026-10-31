"""Tamper-evident record of everything Emerald does: a signed hash chain anyone can re-check."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from . import config, db, keys

GENESIS = "0" * 64


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _entry_hash(device: str, ts: str, case_id: str | None, type_: str, payload: str, prev_hash: str) -> str:
    return hashlib.sha256(canonical([device, ts, case_id, type_, payload, prev_hash]).encode()).hexdigest()


def append(type_: str, payload: dict, case_id: str | None = None) -> dict:
    device = config.device_id()
    ts = now()
    body = canonical(payload)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        prev = row["hash"] if row else GENESIS
        digest = _entry_hash(device, ts, case_id, type_, body, prev)
        cur = conn.execute(
            "INSERT INTO ledger (device, ts, case_id, type, payload, prev_hash, hash, signature) VALUES (?,?,?,?,?,?,?,?)",
            (device, ts, case_id, type_, body, prev, digest, keys.sign(device, digest)),
        )
        return {"seq": cur.lastrowid, "hash": digest, "type": type_}


def entries(case_id: str | None = None) -> list[dict]:
    with db.connect() as conn:
        if case_id:
            rows = conn.execute("SELECT * FROM ledger WHERE case_id=? ORDER BY seq", (case_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM ledger ORDER BY seq").fetchall()
    return [dict(r) for r in rows]


def verify() -> dict:
    """Re-derive the entire chain. Any edited, removed or re-ordered entry breaks it."""
    prev = GENESIS
    rows = entries()
    for row in rows:
        digest = _entry_hash(row["device"], row["ts"], row["case_id"], row["type"], row["payload"], row["prev_hash"])
        if row["prev_hash"] != prev:
            return {"ok": False, "entries": len(rows), "broken_at": row["seq"], "reason": "chain link does not match"}
        if digest != row["hash"]:
            return {"ok": False, "entries": len(rows), "broken_at": row["seq"], "reason": "entry content was changed"}
        if not keys.verify(keys.public_key_for(row["device"]), digest, row["signature"]):
            return {"ok": False, "entries": len(rows), "broken_at": row["seq"], "reason": "device signature is invalid"}
        prev = digest
    return {"ok": True, "entries": len(rows), "head": prev}
