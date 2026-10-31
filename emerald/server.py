"""The console: farmer's call, proof, vet sign-off, outbreak map and ledger, all on one local page.

Run: python -m emerald.server   then open http://localhost:8765
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from strands.bidi.types.events import BidiAudioDeltaEvent, BidiBargeInEvent, BidiToolUseBlocksEvent, BidiTranscriptBlockEvent

from . import config, db, ledger, pipeline, registry, signoff, surveillance, sync, triage, twilio_line, voice

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Emerald")
app.mount("/web", StaticFiles(directory=WEB), name="web")
_jobs: dict[str, str] = {}
_tampered: dict[str, str] = {}


def _rows(sql: str) -> list[dict]:
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql)]


def _evidence(case_id: str) -> dict:
    verified: list[dict] = []
    rejected: list[dict] = []
    deferred = False
    for entry in ledger.entries(case_id):
        payload = json.loads(entry["payload"])
        if entry["type"] == "evidence_checked":
            verified += payload.get("verified", [])
            rejected += payload.get("rejected", [])
        elif entry["type"] == "second_opinion_deferred":
            deferred = True
    return {"verified": verified, "rejected": rejected, "second_opinion_deferred": deferred}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/docs/scenes.html")
def scenes() -> FileResponse:
    return FileResponse(config.ROOT / "docs" / "scenes.html")


@app.get("/api/world")
def world() -> dict:
    return {**registry.world(), "centre": registry.CENTRE, "ring_km": surveillance.RING_RADIUS_KM, "signs": sorted(triage.SIGNS),
            "demo_vet_pin": registry.DEMO_VET_PIN}


@app.get("/api/state")
def state() -> dict:
    cases = _rows("SELECT * FROM cases ORDER BY reported_at DESC, rowid DESC")
    for case in cases:
        for field in ("signs", "candidates", "red_flags"):
            case[field] = json.loads(case[field])
        case["farmer"] = registry.farmer(case["farmer_id"])
        case["evidence"] = _evidence(case["id"])
        case["cluster"] = surveillance.find_cluster(case["id"])
        case["job"] = _jobs.get(case["id"], "idle")
    entries = ledger.entries()
    for entry in entries:
        entry["payload"] = json.loads(entry["payload"])
    return {
        "lane": config.lane(), "device": config.device_id(),
        "telephony_provider": os.environ.get("EMERALD_TELEPHONY", "SIMULATED"),
        "payment_provider": os.environ.get("EMERALD_PAYMENTS", "SIMULATED"),
        "cases": cases, "pending": signoff.pending(), "signoffs": _rows("SELECT * FROM signoffs ORDER BY requested_at DESC"),
        "calls": _rows("SELECT * FROM calls ORDER BY placed_at DESC, rowid DESC"),
        "payments": _rows("SELECT * FROM payments ORDER BY paid_at DESC"),
        "prescriptions": _rows("SELECT * FROM prescriptions ORDER BY created_at DESC"),
        "reports": _rows("SELECT * FROM reports ORDER BY filed_at DESC"),
        "ledger": entries[-60:][::-1], "ledger_total": len(entries), "verification": ledger.verify(),
        "tampered": bool(_tampered), "unsynced": sum(e["synced"] == 0 for e in entries),
        "can_sync": bool(os.environ.get("EMERALD_LEDGER_BUCKET")),
    }


def _process(case: dict) -> None:
    _jobs[case["case_id"]] = "proving"
    try:
        pipeline.process_case(case)
    finally:
        _jobs[case["case_id"]] = "idle"


def _resume(case_id: str) -> None:
    _jobs[case_id] = "acting"
    try:
        pipeline.resume(case_id)
    except Exception as exc:  # the vet has the case either way; record it rather than stall silently
        ledger.append("resume_failed", {"error": type(exc).__name__}, case_id)
    finally:
        _jobs[case_id] = "idle"


class CallIn(BaseModel):
    farmer_id: str
    signs: list[str]
    weight_kg: float | None = None


@app.post("/api/calls")
def typed_call(body: CallIn) -> dict:
    """A case entered by a field worker, for when there is no voice line."""
    case = pipeline.open_case(body.farmer_id, body.signs, body.weight_kg)
    _jobs[case["case_id"]] = "proving"
    threading.Thread(target=_process, args=(case,), daemon=True).start()
    return {"case_id": case["case_id"]}


class Decision(BaseModel):
    vet_id: str
    pin: str
    approve: bool
    note: str = ""


@app.post("/api/signoffs/{signoff_id}")
def decide(signoff_id: str, body: Decision):
    result = signoff.decide(signoff_id, body.vet_id, body.pin, body.approve, body.note)
    if result["status"] == "refused":
        return JSONResponse(result, status_code=403)
    case_id = signoff.get(signoff_id)["case_id"]
    if not any(s["case_id"] == case_id for s in signoff.pending()):
        threading.Thread(target=_resume, args=(case_id,), daemon=True).start()
    return result


class Lane(BaseModel):
    lane: str


@app.post("/api/lane")
def set_lane(body: Lane) -> dict:
    """Signal on or off. Agents read this per run, so the same graph and tools move to the local model."""
    if body.lane not in ("cloud", "offline"):
        return JSONResponse({"status": "refused", "reason": "unknown lane"}, status_code=400)
    os.environ["EMERALD_LANE"] = body.lane
    return {"lane": body.lane}


@app.post("/api/sync")
def run_sync():
    """Back in signal: upload the signed record, then run the second opinions that had to wait."""
    if not os.environ.get("EMERALD_LEDGER_BUCKET"):
        return JSONResponse({"status": "refused", "reason": "no ledger bucket is configured"}, status_code=400)
    if _tampered or not ledger.verify()["ok"]:
        return JSONResponse({"status": "refused", "reason": "a broken record is never uploaded"}, status_code=409)
    uploaded = sync.push()
    opinions = sync.run_second_opinions()
    sync.push()
    return {"status": "ok", "uploaded": uploaded["uploaded"], "bucket": uploaded["bucket"], "second_opinions": opinions}


@app.post("/api/demo/tamper")
def tamper() -> dict:
    """For showing the proof: quietly edits one past record, exactly as an attacker would."""
    with db.connect() as conn:
        # A payment makes the point best: someone quietly changes who got paid, or how much.
        row = conn.execute("SELECT seq, payload FROM ledger WHERE type IN ('vet_paid','treatment_prescribed','case_recorded') "
                           "ORDER BY type='vet_paid' DESC, seq DESC LIMIT 1").fetchone()
        if row is None:
            return {"status": "nothing_to_change"}
        _tampered[str(row["seq"])] = row["payload"]
        payload = json.loads(row["payload"])
        if "amount_inr" in payload:
            payload["amount_inr"] = payload["amount_inr"] * 10
        else:
            payload["edited_by"] = "someone with database access"
        conn.execute("UPDATE ledger SET payload=? WHERE seq=?", (json.dumps(payload), row["seq"]))
    return {"status": "changed", "seq": row["seq"]}


@app.post("/api/demo/restore")
def restore() -> dict:
    with db.connect() as conn:
        for seq, payload in _tampered.items():
            conn.execute("UPDATE ledger SET payload=? WHERE seq=?", (payload, int(seq)))
    _tampered.clear()
    return {"status": "restored"}


@app.post("/api/demo/reset")
def reset() -> dict:
    """Clears demo records for a clean take. Keys and the synthetic registry stay."""
    with db.connect() as conn:
        for table in ("ledger", "cases", "signoffs", "calls", "payments", "reports", "prescriptions", "outbreak_claims"):
            conn.execute(f"DELETE FROM {table}")
    _jobs.clear()
    _tampered.clear()
    return {"status": "ok"}


@app.websocket("/ws/call/{farmer_id}")
async def phone_line(ws: WebSocket, farmer_id: str) -> None:
    """Browser microphone in, Nova Sonic out: 16 kHz, 16-bit mono PCM both ways."""
    await ws.accept()
    if config.lane() == "offline":
        # Nova Sonic needs a connection. With no signal, cases are entered by the field worker instead.
        await ws.send_json({"type": "no_signal"})
        await ws.close()
        return

    def on_case(case: dict) -> None:
        _jobs[case["case_id"]] = "proving"

    def on_done(case: dict) -> None:
        _jobs[case["case_id"]] = "idle"

    call = voice.PhoneCall(farmer_id, on_case=on_case, on_done=on_done)
    await call.agent.start()

    line_number = 0

    async def send_gloss(number: int, text: str) -> None:
        gloss = await asyncio.to_thread(voice.english_gloss, text)
        if gloss:
            try:
                await ws.send_json({"type": "gloss", "line": number, "text": gloss})
            except (WebSocketDisconnect, RuntimeError):
                pass  # the caller hung up before the translation arrived

    async def speak_out() -> None:
        nonlocal line_number
        async for event in call.agent.receive():
            if isinstance(event, BidiAudioDeltaEvent):
                await ws.send_json({"type": "audio", "audio": event.audio})
            elif isinstance(event, BidiTranscriptBlockEvent):
                line_number += 1
                await ws.send_json({"type": "transcript", "role": event.role, "text": event.transcript, "line": line_number})
                asyncio.create_task(send_gloss(line_number, event.transcript))
            elif isinstance(event, BidiBargeInEvent):
                await ws.send_json({"type": "barge_in"})
            elif isinstance(event, BidiToolUseBlocksEvent):
                await ws.send_json({"type": "tool", "names": [t["name"] for t in event.tool_uses]})

    speaker = asyncio.create_task(speak_out())
    try:
        while True:
            pcm = await ws.receive_bytes()
            await call.agent.send({"audio_delta": {"format": "pcm", "source": {"bytes": pcm}}})
    except WebSocketDisconnect:
        pass
    finally:
        speaker.cancel()
        await call.agent.stop()


@app.post("/twilio/voice")
async def twilio_voice(request: Request) -> Response:
    """Twilio asks what to do with an incoming call. The caller's number picks the farmer, or a demo farmer."""
    form = await request.form()
    caller = str(form.get("From", ""))
    farmer = next((f for f in registry.world()["farmers"] if f["phone"] == caller), None)
    return Response(twilio_line.stream_twiml(str(request.url), farmer["id"] if farmer else os.environ.get("EMERALD_DEMO_FARMER", "F010")), media_type="application/xml")


@app.websocket("/twilio/stream")
async def twilio_stream(ws: WebSocket) -> None:
    """A real phone call: 8 kHz mu-law from Twilio, 8 kHz PCM to and from Nova Sonic."""
    await ws.accept()
    call, speaker, stream_sid = None, None, ""

    def on_case(case: dict) -> None:
        _jobs[case["case_id"]] = "proving"

    def on_done(case: dict) -> None:
        _jobs[case["case_id"]] = "idle"

    async def speak_out() -> None:
        async for event in call.agent.receive():
            if isinstance(event, BidiAudioDeltaEvent):
                await ws.send_text(twilio_line.media_message(stream_sid, base64.b64decode(event.audio)))
            elif isinstance(event, BidiBargeInEvent):
                await ws.send_text(twilio_line.clear_message(stream_sid))

    try:
        while True:
            message = json.loads(await ws.receive_text())
            if message["event"] == "start":
                stream_sid = message["start"]["streamSid"]
                farmer_id = message["start"].get("customParameters", {}).get("farmer_id", os.environ.get("EMERALD_DEMO_FARMER", "F010"))
                call = voice.PhoneCall(farmer_id, on_case=on_case, on_done=on_done, sample_rate=8000)
                await call.agent.start()
                speaker = asyncio.create_task(speak_out())
            elif message["event"] == "media" and call:
                pcm = twilio_line.mulaw_to_pcm16(base64.b64decode(message["media"]["payload"]))
                await call.agent.send({"audio_delta": {"format": "pcm", "source": {"bytes": pcm}}})
            elif message["event"] == "stop":
                break
    except WebSocketDisconnect:
        pass
    finally:
        if speaker:
            speaker.cancel()
        if call:
            await call.agent.stop()


def main() -> None:
    import uvicorn

    registry.world()
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("EMERALD_PORT", "8765")), log_level="warning")


if __name__ == "__main__":
    main()
