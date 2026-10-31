"""Emerald on Amazon Bedrock AgentCore Runtime. The same graph, gate and MCP servers as the laptop.

A session keeps its cases on the microVM's disk for its lifetime, so a pause for the vet survives
between invocations. Telephony and payments stay labelled simulations here too.

Payloads:
  {"action": "call", "farmer_id": "F010", "transcript": "..."}           a farmer's words, in Hindi or English
  {"action": "call", "farmer_id": "F010", "signs": [...], "weight_kg": 320}
  {"action": "sign", "signoff_id": "SO-...", "vet_id": "V01", "pin": "...", "approve": true}
  {"action": "state"}
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("EMERALD_DATA", "/tmp/emerald")

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402

from emerald import intake, ledger, pipeline, registry, signoff  # noqa: E402

app = BedrockAgentCoreApp()


def _outcome(outcome: pipeline.Outcome) -> dict:
    return {
        "case_id": outcome.case_id, "status": outcome.status, "summary": outcome.summary, "verified": outcome.verified,
        "rejected": outcome.rejected, "cluster": outcome.cluster, "final_text": outcome.final_text,
        "waiting_for_vet": [{"signoff_id": p["signoff_id"], "summary": p["summary"]} for p in outcome.pending],
    }


def _call(payload: dict) -> dict:
    farmer_id = payload["farmer_id"]
    if payload.get("transcript"):
        heard = intake.from_transcript(payload["transcript"])
        return _outcome(pipeline.handle_case(farmer_id, heard.signs, heard.weight_kg, heard.species))
    return _outcome(pipeline.handle_case(farmer_id, payload.get("signs", []), payload.get("weight_kg")))


def _sign(payload: dict) -> dict:
    decision = signoff.decide(payload["signoff_id"], payload["vet_id"], payload["pin"], bool(payload.get("approve")), payload.get("note", ""))
    if decision["status"] == "refused":
        return decision
    case_id = signoff.get(payload["signoff_id"])["case_id"]
    return {"decision": decision, **_outcome(pipeline.resume(case_id))}


@app.entrypoint
def invoke(payload: dict) -> dict:
    registry.world()
    action = payload.get("action", "state")
    if action == "call":
        return _call(payload)
    if action == "sign":
        return _sign(payload)
    entries = ledger.entries()
    return {"ledger": ledger.verify(), "pending": [{"signoff_id": p["id"], "summary": p["summary"]} for p in signoff.pending()],
            "recent": [{"seq": e["seq"], "type": e["type"], "payload": json.loads(e["payload"])} for e in entries[-8:]]}


if __name__ == "__main__":
    app.run()
