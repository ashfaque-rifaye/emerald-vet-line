"""When a field kit gets signal again: ship the signed record to S3, and run the second opinions it deferred.

The bucket uses S3 Object Lock, so once a record is uploaded it can't be overwritten or quietly removed
during its retention period. Anyone holding the device's public key can re-check the chain from S3 alone.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

import boto3
from strands import Agent
from strands.models import BedrockModel

from . import config, db, keys, ledger, models, proof_graph

RETENTION_DAYS = 7


def _bucket() -> str:
    name = os.environ.get("EMERALD_LEDGER_BUCKET", "")
    if not name:
        raise RuntimeError("set EMERALD_LEDGER_BUCKET to the Object Lock bucket")
    return name


def push(client=None) -> dict:
    """Upload entries not yet shipped. Safe to re-run: keys are fixed per entry, and synced rows are skipped."""
    s3 = client or boto3.client("s3", region_name=models.REGION)
    bucket, device = _bucket(), config.device_id()
    s3.put_object(Bucket=bucket, Key=f"devices/{device}.pub", Body=keys.public_key_for(device).encode())
    with db.connect() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM ledger WHERE synced=0 ORDER BY seq")]
    retain = datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)
    for row in rows:
        body = json.dumps({k: row[k] for k in ("seq", "device", "ts", "case_id", "type", "payload", "prev_hash", "hash", "signature")},
                          ensure_ascii=False)
        s3.put_object(Bucket=bucket, Key=f"ledger/{row['device']}/{row['seq']:08d}.json", Body=body.encode("utf-8"),
                      ContentType="application/json", ObjectLockMode="GOVERNANCE", ObjectLockRetainUntilDate=retain)
        with db.connect() as conn:
            conn.execute("UPDATE ledger SET synced=1 WHERE seq=?", (row["seq"],))
    return {"uploaded": len(rows), "bucket": bucket, "device": device}


def _deferred_cases() -> list[str]:
    deferred, finished = set(), set()
    for entry in ledger.entries():
        if entry["type"] == "second_opinion_deferred":
            deferred.add(entry["case_id"])
        elif entry["type"] == "second_opinion_completed":
            finished.add(entry["case_id"])
    return sorted(deferred - finished)


def _verified_claims(case_id: str) -> list[dict]:
    claims: list[dict] = []
    for entry in ledger.entries(case_id):
        if entry["type"] == "evidence_checked":
            claims += json.loads(entry["payload"]).get("verified", [])
    return claims


def run_second_opinions(checker_model=None) -> list[dict]:
    """Bedrock's independent model now reviews what the local model decided offline. Any failure goes to the vet."""
    from . import actions

    results = []
    for case_id in _deferred_cases():
        claims = _verified_claims(case_id)
        listing = "\n".join(f'{i}. Claim: {c["claim"]}\n   Quote, from {c.get("context", "the source")}: {c["quote"]}' for i, c in enumerate(claims))
        model = checker_model or BedrockModel(model_id=models.CHECKER_ID, region_name=models.REGION, temperature=0.0, max_tokens=1000)
        reply = str(Agent(model=model, system_prompt=proof_graph.CHECKER_PROMPT, callback_handler=None)(listing))
        found = json.loads(reply[reply.find("{"): reply.rfind("}") + 1]).get("failed", [])
        failed = [{"claim": claims[int(f["index"])]["claim"], "reason": str(f.get("reason", ""))}
                  for f in found if 0 <= int(f["index"]) < len(claims)]
        ledger.append("second_opinion_completed", {"reviewed": len(claims), "failed": failed}, case_id)
        if failed:
            actions.notify_vet_of_correction(case_id, failed)
        results.append({"case_id": case_id, "reviewed": len(claims), "failed": failed})
    return results
