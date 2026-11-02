"""Records one take of the real running system for the film. Nothing is mocked: the farmer's lines are played into
the page's microphone, the live agent answers, and the tools run for real. The screen is captured at double
resolution, so the film's camera can move in without going soft.

Needs the console and the local model server running.
  uv run --no-project --with playwright --with boto3 --with websockets python film/record.py
Writes data/film/take/: frames/, times.json, events.json, agent.pcm
"""

from __future__ import annotations

import base64
import ctypes
import faulthandler
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import boto3
from playwright.sync_api import Error as PlaywrightError, sync_playwright
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "film"))
from lines import FARMER  # noqa: E402

TAKE = ROOT / "data" / "film" / "take"
VOICE = ROOT / "data" / "voice"
URL = "http://localhost:8765"
RATE = 16000
SIZE = {"width": 1440, "height": 810}
DEBUG_PORT = 9333
TARGETS = {"callBtn": "#callBtn", "call": ".call", "side": ".side", "panel": ".panel", "vet": "#vet", "hold": "#holdBtn", "callout": "#callout", "hero": ".hero",
           "numbers": ".numbers", "notch": ".notch", "signal": "#signal", "status": ".status", "verdict": ".verdict", "tamper": "#tamperBtn", "sync": "#syncBtn", "broken": ".block.broken"}
MIC = """
(() => {
  const ctx = new AudioContext({ sampleRate: 16000 }), dest = ctx.createMediaStreamDestination();
  const keep = ctx.createConstantSource(), quiet = ctx.createGain();
  quiet.gain.value = 0; keep.connect(quiet); quiet.connect(dest); keep.start();
  navigator.mediaDevices.getUserMedia = async () => { await ctx.resume(); return dest.stream; };
  window.__say = b64 => new Promise(done => {
    const raw = atob(b64), pcm = new Int16Array(raw.length / 2);
    for (let i = 0; i < pcm.length; i++) pcm[i] = (raw.charCodeAt(2 * i + 1) << 8 | raw.charCodeAt(2 * i)) << 16 >> 16;
    const buf = ctx.createBuffer(1, pcm.length, 16000), ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
    const src = ctx.createBufferSource();
    src.buffer = buf; src.connect(dest); src.onended = () => done(true); src.start();
  });
  const Native = window.WebSocket;
  window.WebSocket = function (url, protocols) {
    const ws = new Native(url, protocols);
    ws.addEventListener('message', e => { try { window.__wire(e.data, Date.now() / 1000); } catch {} });
    return ws;
  };
  Object.assign(window.WebSocket, Native);
  window.WebSocket.prototype = Native.prototype;
})();
"""
ATTEMPTS = """
import json, sys
from emerald import actions, signoff, db
with db.connect() as conn:
    row = conn.execute("SELECT * FROM signoffs WHERE tool='pay_vet_consult' AND status='approved' ORDER BY requested_at LIMIT 1").fetchone()
args = json.loads(row["args"])
out = {"args": args, "signoff_id": row["id"]}
out["changed"] = actions.pay_vet_consult(args["case_id"], args["vet_id"], 5000.0, row["id"])
out["forged"] = actions.pay_vet_consult(args["case_id"], args["vet_id"], args["amount_inr"], "approved")
out["replay"] = actions.pay_vet_consult(args["case_id"], args["vet_id"], args["amount_inr"], row["id"])
print(json.dumps(out))
"""


class Capture(threading.Thread):
    """The screen, over its own DevTools connection, so saving frames can never hold up the page."""

    def __init__(self, t0: float, times: list[float]) -> None:
        super().__init__(daemon=True)
        self.t0, self.times, self.stopping = t0, times, threading.Event()

    def run(self) -> None:
        targets = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json/list", timeout=10).read())
        url = next(t["webSocketDebuggerUrl"] for t in targets if t["type"] == "page" and "8765" in t["url"])
        with connect(url, max_size=None, proxy=None) as ws:
            ws.send(json.dumps({"id": 1, "method": "Page.startScreencast", "params": {"format": "jpeg", "quality": 82, "maxWidth": SIZE["width"] * 2, "maxHeight": SIZE["height"] * 2, "everyNthFrame": 3}}))
            sent = 2
            while not self.stopping.is_set():
                try:
                    message = json.loads(ws.recv(timeout=0.5))
                except TimeoutError:
                    continue
                except ConnectionClosed:
                    return
                if message.get("method") == "Page.screencastFrame":
                    frame = message["params"]
                    self.times.append(round(frame["metadata"]["timestamp"] - self.t0, 3))
                    (TAKE / "frames" / f"{len(self.times) - 1:06d}.jpg").write_bytes(base64.b64decode(frame["data"]))
                    ws.send(json.dumps({"id": sent, "method": "Page.screencastFrameAck", "params": {"sessionId": frame["sessionId"]}}))
                    sent += 1


def commit_free_gb() -> float:
    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(n, ctypes.c_ulonglong) for n in ("phys", "phys_free", "page", "page_free", "virt", "virt_free", "ext")]

    status = Status(length=ctypes.sizeof(Status))
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.page_free / 2**30


def load_local_model() -> None:
    """Loads the offline model, retrying while graphics memory the browser just gave back is freed."""
    def generate(body: dict) -> None:
        request = urllib.request.Request("http://127.0.0.1:11435/api/generate", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(request, timeout=180).read()

    for other in json.loads(urllib.request.urlopen("http://127.0.0.1:11435/api/ps", timeout=10).read())["models"]:
        if other["name"] != "qwen2.5:7b":
            generate({"model": other["name"], "keep_alive": 0})
    for attempt in range(4):
        try:
            return generate({"model": "qwen2.5:7b", "keep_alive": "30m", "options": {"num_ctx": 8192}})
        except urllib.error.HTTPError as error:
            print(f"model load failed ({error.code}), retrying", flush=True)
            time.sleep(10)
    raise RuntimeError("the local model would not load")


def farmer_pcm(key: str, text: str) -> bytes:
    """The owner's recording when there is one, otherwise a stand-in voice."""
    mine = VOICE / f"{key}.wav"
    if mine.exists():
        return subprocess.run(["ffmpeg", "-v", "error", "-i", str(mine), "-f", "s16le", "-ac", "1", "-ar", str(RATE), "-"], capture_output=True, check=True).stdout
    polly = boto3.client("polly", region_name="us-east-1")
    return polly.synthesize_speech(Text=text, LanguageCode="en-IN", VoiceId="Arjun", Engine="generative", OutputFormat="pcm", SampleRate=str(RATE))["AudioStream"].read()


def main() -> int:
    faulthandler.dump_traceback_later(1200, exit=True)  # a take is about 7 minutes: a stuck one says where, and stops
    shutil.rmtree(TAKE, ignore_errors=True)
    (TAKE / "frames").mkdir(parents=True)
    turns = [(k, t, farmer_pcm(k, t)) for k, t in FARMER]
    ev: dict = {"marks": {}, "rects": {}, "cursor": [], "turns": [], "agent": [], "transcript": [], "tools": [], "size": SIZE}
    times: list[float] = []
    problems: list[str] = []
    agent_pcm = bytearray()
    agent_end = [0.0]
    last_chunk = [0.0]

    with sync_playwright() as p:
        t0 = time.time()
        now = lambda: time.time() - t0

        def wire(raw: str, stamp: float) -> None:
            m = json.loads(raw)
            t = stamp - t0
            if m["type"] == "audio":
                pcm = base64.b64decode(m["audio"])
                begin = max(t, agent_end[0])
                ev["agent"].append([round(begin, 3), len(agent_pcm), len(pcm)])
                agent_pcm.extend(pcm)
                agent_end[0] = begin + len(pcm) / (2 * RATE)
                last_chunk[0] = t
            elif m["type"] == "transcript":
                ev["transcript"].append([round(t, 2), m["role"], m["text"]])
                print(f"{t:7.1f}  [{m['role']}] {m['text']}", flush=True)
            elif m["type"] == "tool":
                ev["tools"].append([round(t, 2), m["names"]])
                print(f"{t:7.1f}  [tool] {m['names']}", flush=True)

        def open_page():
            browser = p.chromium.launch(channel="msedge", headless=True, args=["--use-gl=angle", "--use-angle=d3d11", "--enable-gpu-rasterization", "--ignore-gpu-blocklist", "--autoplay-policy=no-user-gesture-required", f"--remote-debugging-port={DEBUG_PORT}", "--force-device-scale-factor=2", "--window-size=1466,903"])
            page = browser.new_context(no_viewport=True).new_page()
            page.expose_function("__wire", wire)
            page.add_init_script(MIC)
            page.goto(URL)
            print("page size:", page.evaluate("[innerWidth, innerHeight, devicePixelRatio]"), flush=True)
            return browser, page, Capture(t0, times)

        browser, page, capture = open_page()

        def api(path: str, body: dict | None = None):
            return page.evaluate("([p, b]) => fetch(p, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(b)}).then(r => r.json())", [path, body or {}])

        def state() -> dict:
            for attempt in range(5):
                try:
                    return page.evaluate("fetch('/api/state').then(r => r.json())")
                except PlaywrightError:  # a busy machine can drop one request
                    page.wait_for_timeout(2000)
            raise RuntimeError("the console stopped answering")

        def rects() -> dict:
            out = {}
            for name, selector in TARGETS.items():
                loc = page.locator(selector)
                if loc.count() and loc.first.is_visible():
                    box = loc.first.bounding_box()
                    if box:
                        out[name] = [round(box[k], 1) for k in ("x", "y", "width", "height")]
            return out

        def mark(name: str) -> None:
            ev["marks"][name] = round(now(), 2)
            ev["rects"][name] = rects()
            (TAKE / "events.json").write_text(json.dumps(ev), encoding="utf-8")
            (TAKE / "times.json").write_text(json.dumps(times), encoding="utf-8")
            (TAKE / "agent.pcm").write_bytes(bytes(agent_pcm))
            print(f"{now():7.1f}  == {name}  (commit free {commit_free_gb():.1f} GB)", flush=True)

        def wait_for(check, seconds: float, label: str) -> bool:
            limit = time.monotonic() + seconds
            while time.monotonic() < limit:
                if check():
                    return True
                page.wait_for_timeout(300)
            print("timed out:", label, flush=True)
            problems.append(label)
            return False

        def glide(selector: str) -> tuple[float, float] | None:
            loc = page.locator(selector)
            if not loc.count():
                return None
            box = loc.first.bounding_box()
            if not box:  # the card re-rendered under the pointer
                return None
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            ev["cursor"].append([round(now(), 2), round(x), round(y), "move"])
            page.mouse.move(x, y, steps=10)
            page.wait_for_timeout(650)
            return x, y

        def click(selector: str) -> None:
            spot = glide(selector)
            if spot:
                ev["cursor"].append([round(now(), 2), round(spot[0]), round(spot[1]), "click"])
                page.mouse.down()
                page.wait_for_timeout(70)
                page.mouse.up()

        def hold_sign() -> None:
            spot = glide("#holdBtn")
            if not spot:
                return
            ev["cursor"].append([round(now(), 2), round(spot[0]), round(spot[1]), "down"])
            ev.setdefault("signatures", []).append(round(now(), 2))
            page.mouse.down()
            page.wait_for_timeout(1250)
            page.mouse.up()
            ev["cursor"].append([round(now(), 2), round(spot[0]), round(spot[1]), "up"])

        def sign_all(until, seconds: float = 150, pause: int = 900) -> None:
            limit = time.monotonic() + seconds
            while time.monotonic() < limit and not until():
                if page.locator("#holdBtn").count():
                    hold_sign()
                    page.wait_for_timeout(pause)
                else:
                    page.wait_for_timeout(400)

        idle = lambda: not state()["pending"] and all(c["job"] == "idle" for c in state()["cases"])

        api("/api/lane", {"lane": "cloud"})
        api("/api/demo/reset")
        page.wait_for_timeout(3000)
        capture.start()
        page.wait_for_timeout(5000)
        mark("idle")

        # The call: each line waits for the agent to finish speaking, as a person would.
        click("#callBtn")
        mark("call_start")
        page.wait_for_timeout(1500)
        for key, text, pcm in turns:
            start = now()
            ev["turns"].append({"key": key, "text": text, "at": round(start, 3), "seconds": round(len(pcm) / (2 * RATE), 3)})
            before = len(ev["agent"])
            page.evaluate("b => window.__say(b)", base64.b64encode(pcm).decode())
            wait_for(lambda: len(ev["agent"]) > before, 30, f"a reply to {key}")
            wait_for(lambda: now() > agent_end[0] + 0.8 and now() > last_chunk[0] + 1.2, 45, f"the end of the reply to {key}")
            mark(f"after_{key}")
        click("#callBtn")
        mark("call_end")
        # Nova Sonic can take a short Indian-English line for Hindi and then mishear the rest. Such a take is retried.
        if any(role == "user" and any("ऀ" <= ch <= "ॿ" for ch in text) for _, role, text in ev["transcript"]):
            print("THIS TAKE IS NOT USABLE: the caller was heard as Hindi", flush=True)
            browser.close()
            return 3

        # Proof, then the vet.
        wait_for(lambda: page.locator("#holdBtn").count() > 0, 90, "vet card")
        page.wait_for_timeout(2500)
        mark("vet")
        page.wait_for_timeout(1500)
        hold_sign()
        mark("first_signature")
        sign_all(idle, 90)
        page.wait_for_timeout(2000)
        mark("first_done")

        # Real attacks on the real tool: a changed amount, a bare "approved", and the same signature again.
        reply = subprocess.run([str(ROOT / ".venv" / "Scripts" / "python.exe"), "-c", ATTEMPTS], capture_output=True, text=True, cwd=ROOT)
        ev["attempts"] = json.loads(reply.stdout) if reply.returncode == 0 else {"error": reply.stderr[-400:]}
        print("attempts:", json.dumps(ev["attempts"])[:600], flush=True)
        page.wait_for_timeout(1500)

        # Two more calls nearby make a cluster.
        page.click('.tab[data-tab="proof"]')
        mark("neighbours")
        page.evaluate("""async () => {
          const taken = new Set(S.cases.map(c => c.farmer_id));
          for (const f of nearbyFarmers(8).filter(f => !taken.has(f.id)).slice(0, 2)) {
            await post('/api/calls', {farmer_id: f.id, signs: SCENARIOS.lsd.signs, weight_kg: SCENARIOS.lsd.weight});
            await tick();
            await new Promise(r => setTimeout(r, 2500));
          }
        }""")
        wait_for(lambda: any(c["cluster"] for c in state()["cases"]), 60, "cluster")
        mark("cluster")
        sign_all(lambda: any(x["tool"] in ("file_outbreak_report", "start_ring_calls") for x in state()["pending"]), 180, 1200)
        wait_for(lambda: page.locator("#holdBtn").count() > 0, 30, "outbreak card")
        page.wait_for_timeout(1500)
        mark("outbreak_ask")
        page.wait_for_timeout(3500)
        hold_sign()
        mark("outbreak_signed")
        sign_all(lambda: any(c["purpose"] == "ring_alert" for c in state()["calls"]) or idle(), 180, 1200)
        mark("ring")
        page.wait_for_timeout(7000)
        sign_all(idle, 90, 1200)
        mark("ring_done")
        ev["ring_homes"] = sum(c["purpose"] == "ring_alert" for c in state()["calls"])
        page.wait_for_timeout(2500)

        # Try to change history.
        click('.tab[data-tab="ledger"]')
        page.wait_for_timeout(1800)
        mark("ledger")
        page.wait_for_timeout(1500)
        click("#tamperBtn")
        page.wait_for_timeout(600)
        mark("tamper")
        page.wait_for_timeout(5000)
        click("#restoreBtn")
        page.wait_for_timeout(1500)

        # A fresh browser, and the local model loaded while none is open: both at once are a lot for a laptop.
        capture.stopping.set()
        capture.join(timeout=5)
        browser.close()
        load_local_model()
        print(f"model loaded (commit free {commit_free_gb():.1f} GB)", flush=True)
        browser, page, capture = open_page()
        page.wait_for_timeout(3500)
        capture.start()
        page.wait_for_timeout(1500)

        # No signal: same agents, on this laptop.
        click("#signal")
        mark("night")
        page.wait_for_timeout(3000)
        page.click('.tab[data-tab="proof"]')
        page.locator("#caller").select_option(page.evaluate("world.farmers.filter(f => !S.cases.some(c => c.farmer_id === f.id))[9].id"))
        click('.pill[data-s="anthrax"]')
        mark("offline_case")
        before = len(state()["cases"])
        wait_for(lambda: bool(state()["cases"][0]["evidence"]["verified"]) and len(state()["cases"]) >= before, 120, "offline claims")
        mark("offline_proof")
        wait_for(lambda: page.locator("#holdBtn").count() > 0, 90, "offline vet card")
        mark("offline_vet")
        page.wait_for_timeout(2000)
        sign_all(idle, 150)
        page.wait_for_timeout(2000)
        mark("offline_done")

        # Signal back: seal it.
        click("#signal")
        mark("day")
        page.wait_for_timeout(2500)
        click('.tab[data-tab="ledger"]')
        page.wait_for_timeout(1200)
        click("#syncBtn")
        mark("seal")
        wait_for(lambda: "sealed" in page.locator("#pane").inner_text(), 90, "sealed")
        page.wait_for_timeout(5000)
        mark("end")
        ev["final_state"] = {k: v for k, v in state().items() if k in ("verification", "ledger_total")}

        capture.stopping.set()
        capture.join(timeout=5)
        browser.close()

    (TAKE / "times.json").write_text(json.dumps(times), encoding="utf-8")
    (TAKE / "events.json").write_text(json.dumps(ev), encoding="utf-8")
    (TAKE / "agent.pcm").write_bytes(bytes(agent_pcm))
    print(f"frames {len(times)}, {sum(f.stat().st_size for f in (TAKE / 'frames').iterdir()) / 1e9:.2f} GB, {now():.0f} s")
    if problems:
        print("THIS TAKE IS NOT USABLE, these steps timed out:", problems)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
