"""Records the demo footage from the real running system. Nothing here is mocked: the caller's voice is a
synthetic Hindi voice fed in as a microphone, and everything after that is the live agent.

Needs the console running. Run with Playwright available:
  uv run --no-project --with playwright --with boto3 python scripts/video_record.py
Writes data/video/footage.webm, marks.json and agent_audio.json.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import wave
from pathlib import Path

import boto3
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "video"
URL = "http://localhost:8765"
RATE = 16000
GAP_S = 26
TURNS = [
    "नमस्ते, मेरी गाय को तीन दिन से तेज़ बुखार है, पूरे शरीर पर गांठें निकल आई हैं और दूध कम हो गया है। गाय का वज़न करीब तीन सौ बीस किलो है। किसी आदमी को कुछ नहीं हुआ।",
    "ठीक है। क्या मैं उसे कोई दवाई दे दूं? आप मुझे दवाई और उसकी मात्रा बता दीजिए।",
]
TAP = """
const NativeWS = window.WebSocket;
window.WebSocket = function (url, protocols) {
  const ws = new NativeWS(url, protocols);
  ws.addEventListener('message', e => {
    try { const m = JSON.parse(e.data); if (m.type === 'audio') window.__saveAudio(m.audio); } catch {}
  });
  return ws;
};
Object.assign(window.WebSocket, NativeWS);
window.WebSocket.prototype = NativeWS.prototype;
"""


def caller_wav() -> tuple[Path, list[float]]:
    polly = boto3.client("polly", region_name="us-east-1")
    pcm, starts = b"", []
    pcm += bytes(int(RATE * 2 * 1.5))
    for text in TURNS:
        starts.append(len(pcm) / (2 * RATE))
        pcm += polly.synthesize_speech(Text=text, LanguageCode="hi-IN", VoiceId="Kajal", Engine="neural", OutputFormat="pcm", SampleRate=str(RATE))["AudioStream"].read()
        pcm += bytes(int(RATE * 2 * GAP_S))
    path = OUT / "caller.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm)
    return path, starts


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    wav, turn_starts = caller_wav()
    marks: dict[str, float] = {"caller_turns": turn_starts}
    quiet_path = Path(tempfile.gettempdir()) / "emerald_caller.wav"  # Chromium's flag doesn't take paths with spaces
    shutil.copy(wav, quiet_path)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True, args=[
            "--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", f"--use-file-for-fake-audio-capture={quiet_path}%noloop", "--autoplay-policy=no-user-gesture-required"])
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, record_video_dir=str(OUT), record_video_size={"width": 1920, "height": 1080}, permissions=["microphone"])
        page = context.new_page()
        audio_chunks: list = []
        started = time.monotonic()
        marks["epoch"] = time.time()
        page.expose_function("__saveAudio", lambda audio: audio_chunks.append([round(time.monotonic() - started, 3), audio]))
        page.add_init_script(TAP)

        def mark(name: str) -> None:
            marks[name] = round(time.monotonic() - started, 2)
            (OUT / "marks.json").write_text(json.dumps(marks, indent=1), encoding="utf-8")
            print(f"{marks[name]:7.1f}  {name}", flush=True)

        def state() -> dict:
            return page.evaluate("fetch('/api/state').then(r => r.json())")

        def wait_for(check, seconds: float, label: str) -> bool:
            limit = time.monotonic() + seconds
            while time.monotonic() < limit:
                if check():
                    return True
                page.wait_for_timeout(400)
            print("timed out:", label, flush=True)
            return False

        def hold_sign() -> None:
            box = page.locator("#holdBtn").bounding_box() if page.locator("#holdBtn").count() else None
            if not box:
                return
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=8)
            page.wait_for_timeout(300)
            page.mouse.down()
            page.wait_for_timeout(1250)
            page.mouse.up()

        def sign_all(until, seconds: float = 150, pause: int = 700) -> None:
            limit = time.monotonic() + seconds
            while time.monotonic() < limit and not until():
                if page.locator("#holdBtn").count():
                    hold_sign()
                    page.wait_for_timeout(pause)
                else:
                    page.wait_for_timeout(500)

        page.goto(URL)
        page.evaluate("fetch('/api/lane',{method:'POST',headers:{'Content-Type':'application/json'},body:'{\"lane\":\"cloud\"}'})")
        page.evaluate("fetch('/api/demo/reset',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})")
        page.wait_for_timeout(3000)
        mark("idle")
        page.wait_for_timeout(7000)

        # The call.
        page.click("#callBtn")
        mark("call_start")
        wait_for(lambda: page.locator(".say.tool").count() > 0, 70, "case recorded on the call")
        mark("case_recorded")
        wait_for(lambda: page.locator(".say.assistant").count() >= 2 or time.monotonic() - started > marks["call_start"] + 2 * GAP_S + 30, 2 * GAP_S + 20, "second reply")
        page.wait_for_timeout(9000)
        mark("call_end")
        page.click("#callBtn")

        # Proof, then the vet.
        wait_for(lambda: page.locator(".proof").count() > 0, 60, "claims")
        mark("proof")
        page.wait_for_timeout(5000)
        wait_for(lambda: page.locator("#holdBtn").count() > 0, 60, "vet card")
        page.wait_for_timeout(3000)
        mark("vet")
        page.wait_for_timeout(5000)
        hold_sign()
        mark("first_signature")
        sign_all(lambda: not state()["pending"] and all(c["job"] == "idle" for c in state()["cases"]), 60)
        page.wait_for_timeout(1500)
        page.click('.tab[data-tab="actions"]')
        mark("actions")
        page.wait_for_timeout(5000)

        # Two more calls nearby make a cluster.
        page.click('.tab[data-tab="proof"]')
        mark("story_start")
        page.evaluate("""async () => {
          const taken = new Set(S.cases.map(c => c.farmer_id));
          for (const f of nearbyFarmers(8).filter(f => !taken.has(f.id)).slice(0, 2)) {
            await post('/api/calls', {farmer_id: f.id, signs: SCENARIOS.lsd.signs, weight_kg: SCENARIOS.lsd.weight});
            await tick();
            await new Promise(r => setTimeout(r, 2500));
          }
        }""")
        wait_for(lambda: any(c["cluster"] for c in state()["cases"]), 40, "cluster")
        mark("cluster")
        sign_all(lambda: any(p["tool"] in ("file_outbreak_report", "start_ring_calls") for p in state()["pending"]), 150, 1200)
        wait_for(lambda: page.locator("#holdBtn").count() > 0, 20, "outbreak card")
        mark("outbreak_ask")
        page.wait_for_timeout(5000)
        sign_all(lambda: any(c["purpose"] == "ring_alert" for c in state()["calls"]), 150, 1200)
        mark("ring")
        page.wait_for_timeout(9000)
        sign_all(lambda: not state()["pending"] and all(c["job"] == "idle" for c in state()["cases"]), 60, 1200)
        mark("ring_done")
        page.click('.tab[data-tab="actions"]')
        page.wait_for_timeout(3500)

        # Try to change history.
        page.click('.tab[data-tab="ledger"]')
        mark("ledger")
        page.wait_for_timeout(3500)
        page.click("#tamperBtn")
        mark("tamper")
        page.wait_for_timeout(6000)
        page.click("#restoreBtn")
        page.wait_for_timeout(1500)

        # No signal: same agents, on this laptop.
        page.click("#signal")
        mark("night")
        page.wait_for_timeout(4000)
        page.click('.tab[data-tab="proof"]')
        page.locator("#caller").select_option(page.evaluate("world.farmers.filter(f => !S.cases.some(c => c.farmer_id === f.id))[9].id"))
        page.click('.pill[data-s="anthrax"]')
        mark("offline_case")
        before = len(state()["cases"])
        wait_for(lambda: bool(state()["cases"][0]["evidence"]["verified"]) and len(state()["cases"]) >= before, 90, "offline claims")
        mark("offline_proof")
        wait_for(lambda: page.locator("#holdBtn").count() > 0, 60, "offline vet card")
        mark("offline_vet")
        page.wait_for_timeout(3000)
        sign_all(lambda: not state()["pending"] and all(c["job"] == "idle" for c in state()["cases"]), 120)
        page.wait_for_timeout(3000)
        mark("offline_done")

        # Signal back: seal it.
        page.click("#signal")
        mark("day")
        page.wait_for_timeout(3000)
        page.click('.tab[data-tab="ledger"]')
        page.wait_for_timeout(1500)
        page.click("#syncBtn")
        mark("seal")
        wait_for(lambda: "sealed" in page.locator("#pane").inner_text(), 60, "sealed")
        page.wait_for_timeout(6000)
        mark("end")

        (OUT / "agent_audio.json").write_text(json.dumps(audio_chunks), encoding="utf-8")
        video = page.video
        context.close()
        browser.close()
        final = OUT / "footage.webm"
        Path(video.path()).replace(final)
    print("footage:", final, f"{final.stat().st_size / 1e6:.0f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
