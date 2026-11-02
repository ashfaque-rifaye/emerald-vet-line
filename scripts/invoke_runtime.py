"""Exercises the deployed runtime: a farmer's words, then a vet signing, within one session.

Run: python scripts/invoke_runtime.py    (needs a deployed runtime, see deploy_runtime.py)
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import boto3
from botocore.config import Config

ROOT = Path(__file__).resolve().parent.parent
ARN = (ROOT / "data" / "runtime-arn.txt").read_text().strip()
client = boto3.client("bedrock-agentcore", region_name="us-east-1", config=Config(read_timeout=600, retries={"max_attempts": 0}))
SESSION = "emerald-check-" + uuid.uuid4().hex  # a session id must be at least 33 characters


def invoke(payload: dict) -> dict:
    reply = client.invoke_agent_runtime(agentRuntimeArn=ARN, runtimeSessionId=SESSION, payload=json.dumps(payload).encode(), contentType="application/json")
    return json.loads(reply["response"].read())


def main() -> int:
    out = invoke({"action": "call", "farmer_id": "F010", "transcript": "My cow has high fever and lumps have come up all over her body. She weighs about 320 kilos."})
    print(json.dumps({k: out.get(k) for k in ("case_id", "status", "summary")}, ensure_ascii=False)[:500])
    print(f"verified {len(out.get('verified', []))}, rejected {len(out.get('rejected', []))}")
    rounds = 0
    while out.get("waiting_for_vet") and rounds < 6:
        rounds += 1
        for item in out["waiting_for_vet"]:
            print("vet asked:", item["summary"][:110])
            signed = invoke({"action": "sign", "signoff_id": item["signoff_id"], "vet_id": "V01", "pin": "4321", "approve": True})
            if signed.get("status") == "refused":
                print("refused:", signed)
                return 1
            out = signed
    print("final:", out.get("status"), out.get("final_text", "")[:200])
    state = invoke({"action": "state"})
    print("ledger:", state["ledger"], [e["type"] for e in state["recent"]])
    return 0 if state["ledger"]["ok"] and out.get("status") == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
