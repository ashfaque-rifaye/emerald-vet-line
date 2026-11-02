"""Lays out the film from a recorded take and the spoken lines: where each second comes from, where the camera looks,
and what is heard when. Writes data/film/edit.json, which film/film.js draws and film/score.py mixes.

  uv run --no-project --with boto3 --with numpy python film/edit.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import boto3
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "film"))
from lines import FARMER, NARRATION  # noqa: E402

FILM = ROOT / "data" / "film"
TAKE = FILM / "take"
VOICE = ROOT / "data" / "voice"
SPOKEN = FILM / "spoken"
FPS, W, H = 30, 1920, 1080
RATE = 16000
ev = json.loads((TAKE / "events.json").read_text(encoding="utf-8"))
times = json.loads((TAKE / "times.json").read_text(encoding="utf-8"))
M = ev["marks"]
R = ev["rects"]


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def seconds(path: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout)


TRIM = "silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.05,areverse,silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.08,areverse"


def spoken(key: str, text: str, voice_id: str) -> Path:
    """The owner's recording when there is one, otherwise a stand-in voice. Cleaned up and level-matched either way."""
    SPOKEN.mkdir(parents=True, exist_ok=True)
    out = SPOKEN / f"{key}.wav"
    mine = VOICE / f"{key}.wav"
    source = mine if mine.exists() else SPOKEN / f"{key}.standin.wav"
    if not mine.exists() and not source.exists():
        polly = boto3.client("polly", region_name="us-east-1")
        pcm = polly.synthesize_speech(Text=text, LanguageCode="en-IN", VoiceId=voice_id, Engine="generative", OutputFormat="pcm", SampleRate="16000")["AudioStream"].read()
        raw = SPOKEN / f"{key}.pcm"
        raw.write_bytes(pcm)
        ffmpeg("-f", "s16le", "-ar", "16000", "-ac", "1", "-i", str(raw), str(source))
        raw.unlink()
    if not out.exists() or out.stat().st_mtime < source.stat().st_mtime:
        ffmpeg("-i", str(source), "-af", f"highpass=f=80,{TRIM},loudnorm=I=-18:TP=-2:LRA=9", "-ar", "48000", "-ac", "1", str(out))
    return out


class Film:
    def __init__(self) -> None:
        self.clock = 0.0
        self.shots: list[dict] = []
        self.captions: list[dict] = []
        self.overlays: list[dict] = []
        self.tags: list[dict] = []
        self.flashes: list[dict] = []
        self.voices: list[dict] = []
        self.sound: dict = {"hits": [], "whoosh": [], "ticks": [], "errors": [], "bells": [], "plucks": []}

    def say(self, key: str, at: float | None = None, caption: bool = True) -> tuple[float, float]:
        path = spoken(key, NARRATION[key], "Kajal")
        at = self.clock if at is None else at
        length = seconds(path)
        self.voices.append({"file": path.relative_to(ROOT).as_posix(), "at": round(at, 3), "gain": 1.0, "bus": "narration"})
        if caption:
            self.caption(NARRATION[key], at, length)
        return at, at + length

    def caption(self, text: str, at: float, length: float, who: str | None = None) -> None:
        parts = re.split(r"(?<=[.?!])\s+", text)
        pieces: list[str] = []
        for part in parts:
            if len(part) > 74:
                # A long sentence shows a phrase at a time.
                mid = [m.start() for m in re.finditer(r",\s|\sand\s", part)]
                cut = min(mid, key=lambda i: abs(i - len(part) / 2)) if mid else len(part) // 2
                pieces += [part[:cut + 1].strip().rstrip(","), part[cut + 1:].strip()]
            else:
                pieces.append(part)
        total = sum(len(p) for p in pieces) or 1
        cursor = at
        for piece in pieces:
            share = length * len(piece) / total
            self.captions.append({"t0": round(cursor, 3), "t1": round(cursor + share, 3), "text": piece, **({"who": who} if who else {})})
            cursor += share

    def screen(self, length: float, windows: list[tuple[float, float]], cam: list[dict], cursor: bool = True, **extra) -> dict:
        """One shot of footage: source windows, fitted to length, and a camera path in shot time."""
        total = sum(b - a for a, b in windows)
        rows, film, t0 = [], self.clock, self.clock
        for a, b in windows:
            part = length * (b - a) / total
            rows.append([round(film, 3), round(a, 3), round(film + part, 3), round(b, 3)])
            film += part
        keys = [{**k, "t": round(t0 + k["t"], 3)} for k in cam]
        shot = {"kind": "screen", "t0": round(t0, 3), "t1": round(t0 + length, 3), "map": rows, "cam": keys, "cursor": cursor, **extra}
        self.shots.append(shot)
        self.clock += length
        return shot

    def card(self, kind: str, length: float, **extra) -> dict:
        shot = {"kind": kind, "t0": round(self.clock, 3), "t1": round(self.clock + length, 3), **extra}
        self.shots.append(shot)
        self.clock += length
        return shot

    def tag(self, text: str, t0: float, t1: float, color: str | None = None) -> None:
        self.tags.append({"text": text, "t0": round(t0, 3), "t1": round(t1, 3), **({"color": color} if color else {})})


def view(t: float, cx: float, cy: float, s: float, d: float = 0.9) -> dict:
    return {"t": t, "cx": round(cx, 1), "cy": round(cy, 1), "s": round(s, 3), "d": d}


def wide(t: float = 0.0, d: float = 0.9) -> dict:
    return view(t, 720, 396, 1.2, d)


def beside_phone(t: float = 0.0, d: float = 0.9) -> dict:
    s = 1.03
    return view(t, (W / 2 - 34) / s, 400, s, d)


def on(rect: list[float], t: float, frac: float = 0.82, at_x: float = 0.5, at_y: float = 0.5, cap: float = 2.7, d: float = 0.9) -> dict:
    x, y, w, h = rect
    s = min(W * frac / w, H * frac / h, cap)
    return view(t, x + w / 2 - (at_x - 0.5) * W / s, y + h / 2 - (at_y - 0.5) * H / s, s, d)


def rect(mark: str, name: str, fallback: list[float] | None = None) -> list[float]:
    return R.get(mark, {}).get(name) or fallback or [0, 0, 1440, 810]


def panel_top(mark: str) -> list[float]:
    x, y, w, h = rect(mark, "side")
    return [x, y, w, h * 0.62]


def call_timeline() -> tuple[list[list[float]], list[dict], list[dict]]:
    """Which stretches of the call are speech, as (source start, source end, who: 1 agent, 2 farmer)."""
    bursts: list[list[float]] = []
    for begin, offset, size in ev["agent"]:
        end = begin + size / (2 * RATE)
        if bursts and begin - bursts[-1][1] < 0.7:
            bursts[-1][1] = end
            bursts[-1][3] += size
        else:
            bursts.append([begin, end, offset, size])
    turns = [{"key": t["key"], "text": t["text"], "a": t["at"], "b": t["at"] + t["seconds"]} for t in ev["turns"]]
    return bursts, turns, []


film = Film()

# ------------------------------------------------------------ the opening: big type on the project's own landscape
film.clock = 0.4
a1, b1 = film.say("n01", caption=False)
a2, b2 = film.say("n02", at=b1 + 0.4, caption=False)
a3, b3 = film.say("n03", at=b2 + 0.45, caption=False)
advice = (b3 - a3) * len("Most farm AI gives advice.") / len(NARRATION["n03"]) + 0.1
film.clock = 0
film.card("open", b3 + 0.8, cues={"n01": [a1, b1], "n02": [a2, b2], "n03": [a3, b3], "adviceLen": advice})
film.sound.update(open=0.0, n02=a2, n03=a3, logo=a3 + advice)
film.sound["hits"] += [{"t": a1 + 0.02, "p": 0.55}, {"t": a1 + 0.95, "p": 0.35}, {"t": a1 + 2.0, "p": 0.45}, {"t": a2, "p": 0.75}, {"t": a3, "p": 0.45}, {"t": a3 + advice, "p": 0.95}]
film.flashes.append({"t": a3 + advice, "d": 0.28, "color": "#c9f26c", "a": 0.35})

# ------------------------------------------------------------ the call, at real speed, with the silences trimmed
bursts, turns, _ = call_timeline()
regions = sorted([[t["a"], t["b"]] for t in turns] + [[b[0], b[1]] for b in bursts])
merged: list[list[float]] = []
for a, b in regions:
    if merged and a - merged[-1][1] < 0.5:
        merged[-1][1] = max(merged[-1][1], b)
    else:
        merged.append([a, b])
GAP = 0.45

t_intro = film.clock
a4, b4 = film.say("n04", at=t_intro + 0.25)
intro_len = b4 - t_intro + 0.2
ring_len = 1.5
film.screen(intro_len + ring_len, [(max(times[0], M["idle"] - 3), M["call_start"] + 0.8)], [wide(0), beside_phone(intro_len - 0.2, 0.9)])
film.sound["whoosh"].append(film.clock - ring_len - 0.5)
phone_t0 = t_intro + intro_len - 0.3
film.sound["ring"] = phone_t0 + 0.2

call_base = film.clock
rows, cursor, src_prev = [], call_base, M["call_start"] + 0.8
for a, b in merged:
    gap = a - src_prev
    if gap > 0:
        part = min(gap, GAP)
        rows.append([round(cursor, 3), round(src_prev, 3), round(cursor + part, 3), round(a, 3)])
        cursor += part
    rows.append([round(cursor, 3), round(a, 3), round(cursor + (b - a), 3), round(b, 3)])
    cursor += b - a
    src_prev = b
call_len = cursor - call_base


def in_call(src: float) -> float:
    for f0, s0, f1, s1 in rows:
        if s0 <= src <= s1:
            return f0 + (src - s0) / (s1 - s0 or 1) * (f1 - f0)
    return rows[-1][2] if src > rows[-1][3] else rows[0][0]


tool_at = next((t for t, names in ev["tools"] if "record_case" in names), ev["turns"][3]["at"])
film_tool = in_call(tool_at)
# From here to the attacks the camera stays on the whole screen: a zoom hid what the rest of it was doing.
keys = [beside_phone(0, 0.6)]
call_shot = {"kind": "screen", "t0": round(call_base, 3), "t1": round(call_base + call_len, 3), "map": rows, "cam": [{**k, "t": round(call_base + k["t"], 3)} for k in keys], "cursor": False}
film.shots.append(call_shot)
film.clock = call_base + call_len

for t in turns:
    path = spoken(t["key"], t["text"], "Arjun")
    at, length = in_call(t["a"]), seconds(path)
    film.voices.append({"file": path.relative_to(ROOT).as_posix(), "at": round(at, 3), "gain": 1.0, "bus": "farmer"})
    film.caption(t["text"], at, length, who="Farmer")
# The agent's real words, placed against its real audio.
said = [x for x in ev["transcript"] if x[1] == "assistant"]
for i, b in enumerate(bursts):
    next_start = bursts[i + 1][0] if i + 1 < len(bursts) else 1e9
    prev_start = b[0] if i else 0
    words = " ".join(x[2].strip() for x in said if b[0] - 2.5 <= x[0] < next_start - 2.5).strip()
    b.append(words)
    at = in_call(b[0])
    film.voices.append({"pcm": [b[2], b[3]], "at": round(at, 3), "gain": 1.0, "bus": "agent"})
    if words:
        film.caption(words, at, b[1] - b[0], who="Emerald")

film.tag("LIVE  ·  Strands BidiAgent on Amazon Nova Sonic", phone_t0 + 1.2, film.clock - 0.2)
film.overlays.append({"type": "callout", "text": "record_case: the agent's one tool", "x": 760, "y": 150, "t0": round(film_tool, 3), "t1": round(film_tool + 3.4, 3), "size": 32})
film.sound["bells"].append({"t": film_tool, "f": 1174.66, "g": 0.14})
refusal = in_call(next(b[0] for b in bursts if b[0] > ev["turns"][4]["at"]))
film.overlays.append({"type": "callout", "text": "No medicine. No dose. Only a vet.", "x": 760, "y": 150, "t0": round(refusal + 1.0, 3), "t1": round(refusal + 4.2, 3), "size": 38, "bg": "#ff7050", "fg": "#fff"})
film.sound["hits"].append({"t": refusal + 1.0, "p": 0.5})

# Env for the phone's waveform, from the audio as heard.
length_f = int((call_len + 2) * FPS)
agent_pcm = np.frombuffer((TAKE / "agent.pcm").read_bytes(), dtype=np.int16).astype(np.float32) / 32768
env, who = [0.0] * length_f, [0] * length_f
for b in bursts:
    at = in_call(b[0]) - call_base
    clip = agent_pcm[b[2] // 2: (b[2] + b[3]) // 2]
    for i in range(0, len(clip), RATE // FPS):
        f = int(at * FPS) + i // (RATE // FPS)
        if 0 <= f < length_f:
            env[f] = float(np.sqrt(np.mean(clip[i: i + RATE // FPS] ** 2)))
            who[f] = 1
for t in turns:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(SPOKEN / f"{t['key']}.wav"), "-f", "f32le", "-ac", "1", "-ar", str(RATE), "-"], capture_output=True, check=True).stdout
    clip = np.frombuffer(raw, dtype=np.float32)
    at = in_call(t["a"]) - call_base
    for i in range(0, len(clip), RATE // FPS):
        f = int(at * FPS) + i // (RATE // FPS)
        if 0 <= f < length_f:
            env[f] = float(np.sqrt(np.mean(clip[i: i + RATE // FPS] ** 2)))
            who[f] = 2
peak = max(env) or 1
# After the farmer's "thank you" and the goodbye: the point of the refusal.
a5, b5 = film.say("n05", at=film.clock + 0.25)
film.screen(b5 - film.clock + 0.3, [(M["after_f6"] - 0.2, M["call_end"] + 1.5)], [beside_phone(0), wide(0.9, 0.9)], cursor=True)
hangup = call_base + call_len
film.sound["hangup"] = hangup
film.sound["call"] = [call_base, hangup]
phone = {"t0": round(phone_t0, 3), "t1": round(hangup + 1.2, 3), "x": 1530, "y": 172, "answered": round(call_base + 0.3, 3), "hangup": round(hangup, 3), "envAt": round(call_base, 3),
         "env": [round((v / peak) ** 0.6, 3) for v in env], "who": who, "captionX": 760}

# ------------------------------------------------------------ the proof loop
proof_start = tool_at
a6, b6 = film.say("n06", at=film.clock + 0.1)
a7, b7 = film.say("n07", at=b6 + 0.2)
length = b7 - film.clock + 0.4
t_proof = film.clock
film.sound["proof"] = t_proof
film.sound["whoosh"].append(t_proof - 0.25)
film.screen(length, [(proof_start, M["vet"] - 1.5)], [wide(0)], cursor=False, fade=0.3)
film.overlays.append({"type": "graph", "x": 866, "y": 190, "w": 400, "t0": round(t_proof + 0.3, 3), "t1": round(film.clock - 0.1, 3)})
film.tag("Strands Graph  ·  custom verifier node  ·  7 MCP servers", t_proof + 0.2, film.clock - 0.1)

# ------------------------------------------------------------ the vet
sign = ev["signatures"][0]
a8, b8 = film.say("n08", at=film.clock + 0.3)
a9, b9 = film.say("n09", at=b8 + 0.25)
hold_lead = 0.9
talk = b9 - film.clock + 0.1
t_vet = film.clock
film.sound["stop"] = a8
film.sound["hits"].append({"t": a8 + 0.45, "p": 0.8})
film.screen(talk + hold_lead + 1.25 + 1.1, [(M["vet"] - 0.5, sign - hold_lead), (sign - hold_lead, sign + 1.25 + 1.1)],
            [wide(0)])
# The take's hold starts here, so the fill plays at real speed.
real_rows = film.shots[-1]["map"]
real_rows[0][2] = round(t_vet + talk, 3)
real_rows[1][0] = round(t_vet + talk, 3)
signed = t_vet + talk + hold_lead + 1.25
film.tag("Strands interrupt  ·  the agent is paused, and it survives a restart", t_vet + 0.8, signed)
film.sound["hold"] = signed - 1.25
film.sound["hits"].append({"t": signed, "p": 1.0})
film.flashes.append({"t": signed, "d": 0.3, "color": "#c9f26c", "a": 0.4})
film.overlays.append({"type": "callout", "text": "Signed. This exact action, once.", "x": 960, "y": 930, "t0": round(signed + 0.05, 3), "t1": round(film.clock + 0.1, 3), "size": 46})

# ------------------------------------------------------------ try to break it, with the real results
a10, b10 = film.say("n10", at=film.clock + 0.2, caption=False)
attempts = ev.get("attempts", {})
args = attempts.get("args", {"amount_inr": 300, "vet_id": "V01"})
sid = attempts.get("signoff_id", "SO-")
text = NARRATION["n10"]
when = lambda phrase, after=False: a10 + (b10 - a10) * ((text.index(phrase) + (len(phrase) if after else 0)) / len(text))
rows_term = [
    {"cmd": f'pay_vet_consult(case, "{args["vet_id"]}", amount_inr=5000, signoff="{sid}")', "at": when("Change"), "result": when("Refused."), "label": "REFUSED", "reason": attempts.get("changed", {}).get("reason", ""), "good": False},
    {"cmd": f'pay_vet_consult(case, "{args["vet_id"]}", amount_inr={args["amount_inr"]:g}, signoff="approved")', "at": when("Fake"), "result": when("Refused. Use"), "label": "REFUSED", "reason": attempts.get("forged", {}).get("reason", ""), "good": False},
    {"cmd": f'pay_vet_consult(case, "{args["vet_id"]}", amount_inr={args["amount_inr"]:g}, signoff="{sid}")   # again', "at": when("Use"), "result": when("Nothing"), "label": "NOT REPEATED", "reason": "already carried out, so nothing moved", "good": True},
]
length = b10 - film.clock + 1.3
film.screen(length, [(M["first_done"] - 0.6, M["first_done"])], [wide(0)], cursor=False)
film.overlays.append({"type": "terminal", "t0": round(a10 - 0.05, 3), "t1": round(film.clock, 3), "rows": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()} for r in rows_term]})
for r in rows_term:
    film.sound["errors" if not r["good"] else "ticks"].append(r["result"])

# ------------------------------------------------------------ the outbreak
a11, b11 = film.say("n11", at=film.clock + 0.15)
a12, b12 = film.say("n12", at=b11 + 0.35)
ring_centre = [585, 440]  # the cluster sits here for this take's farmers
ring_circle = {"cx": 598, "cy": 418, "r": 118}
ring_view = [ring_centre[0] - 340, ring_centre[1] - 192, 680, 384]
length = b12 - film.clock + 0.3
t_out = film.clock
film.sound["outbreak"] = t_out
film.sound["whoosh"].append(t_out)
ask = M["outbreak_ask"]
film.screen(length, [(M["neighbours"], ask)], [wide(0, 0.5), on(ring_view, b11 - t_out + 0.2, frac=0.98, cap=2.8, d=1.2), on(rect("outbreak_ask", "vet"), length - 1.4, frac=0.72, cap=2.4, d=1.2)], cursor=False, fade=0.25)
film.tag("Cluster detector  ·  plain code, no model", t_out + 0.2, film.clock - 0.1, "#ff7050")
film.overlays.append({"type": "spot", **ring_circle, "t0": round(b11 + 0.2, 3), "t1": round(film.clock - 1.5, 3)})
for offset in (0.2, 1.5):
    film.sound["hits"].append({"t": t_out + offset, "p": 0.35})

after = M["outbreak_signed"]
sign2 = next(s for s in ev["signatures"] if s >= ask)
film.screen(sign2 + 1.25 + 0.4 - (sign2 - 0.7), [(sign2 - 0.7, sign2 + 1.65)], [on(rect("outbreak_ask", "vet"), 0, frac=0.72, cap=2.4, d=0.3)])
film.sound["hits"].append({"t": film.clock - 0.4, "p": 0.85})
film.sound["hold2"] = film.clock - 1.65
a13, b13 = film.say("n13", at=film.clock + 0.2)
ring_mark = M["ring"]
length = b13 - film.clock + 1.6
t_ring = film.clock
film.sound["ring_homes"] = [t_ring + 0.2, t_ring + length]
film.flashes.append({"t": t_ring, "d": 0.3, "color": "#ffffff", "a": 0.25})
film.screen(length, [(after, ring_mark - 2.0), (ring_mark - 2.0, M["ring_done"] + 2)], [on(ring_view, 0, frac=0.98, cap=2.8, d=0.5), wide(length - 0.7, 0.7)], cursor=False)
film.overlays.append({"type": "spot", **ring_circle, "t0": round(t_ring, 3), "t1": round(film.clock - 0.6, 3)})
film.overlays.append({"type": "callout", "text": f'{ev["ring_homes"]} homes warned', "x": 960, "y": 96, "t0": round(film.clock - 3.0, 3), "t1": round(film.clock - 0.5, 3), "size": 54})
film.sound["hits"].append({"t": film.clock - 3.0, "p": 0.6})

# ------------------------------------------------------------ the record
a14, b14 = film.say("n14", at=film.clock + 0.15)
tamper = M["tamper"]
lead = 2.0
real = lead + 3.0
talk = b14 - film.clock + 0.1
t_led = film.clock
film.sound["whoosh"].append(t_led)
film.screen(max(talk, real), [(M["ledger"] - 1.5, tamper + 3.6)], [on(panel_top("ledger"), 0, frac=0.86, cap=2.3, d=0.5)], fade=0.2)
broke = t_led + (tamper - (M["ledger"] - 1.5)) / (tamper + 3.6 - (M["ledger"] - 1.5)) * (film.clock - t_led)
film.sound["errors"].append(broke)
film.sound["hits"].append({"t": broke, "p": 0.8})
film.flashes.append({"t": broke, "d": 0.32, "color": "#e0452b", "a": 0.4})
film.tag("Ed25519 signatures  ·  hash chain", t_led + 0.2, film.clock - 0.1)

# ------------------------------------------------------------ no signal
a15, b15 = film.say("n15", at=film.clock + 0.3)
talk = b15 - film.clock + 0.2
night = M["night"]
film.sound["whoosh"].append(film.clock)
film.screen(talk + 1.2, [(night - 1.6, night - 0.5), (night - 0.5, night + 1.4)], [on(rect("night", "status"), 0, frac=0.5, at_y=0.42, cap=2.4, d=0.3)])
night_hit = film.clock - 1.2 + 0.5
film.sound["night"] = night_hit
film.sound["hits"].append({"t": night_hit, "p": 1.0})
film.flashes.append({"t": night_hit, "d": 0.4, "color": "#000000", "a": 0.9})
a16, b16 = film.say("n16", at=film.clock + 0.1)
length = b16 - film.clock + 0.4
t_night = film.clock
film.screen(length, [(night + 1.4, M["offline_vet"] + 1.5)], [wide(0, 0.7), on(panel_top("offline_vet"), length - 1.4, frac=0.86, cap=2.3, d=1.1)], cursor=False)
film.tag("qwen2.5:7b on Ollama  ·  same graph, same MCP tools", t_night + 0.2, film.clock - 0.1, "#f2b84b")
a17, b17 = film.say("n17", at=film.clock + 0.1)
length = b17 - film.clock + 0.6
t_day = film.clock
film.sound["day"] = t_day
film.sound["bells"].append({"t": t_day, "f": 880.0, "g": 0.16})
film.screen(length, [(M["day"] - 0.3, M["end"])], [wide(0, 0.4), on(panel_top("seal"), 1.0, frac=0.86, cap=2.3, d=1.0)], cursor=True, fade=0.2)
film.tag("S3 Object Lock  ·  Bedrock second opinions", t_day + 0.2, film.clock - 0.1)

# ------------------------------------------------------------ what it's built with, what was measured, and the door
a18, b18 = film.say("n18", at=film.clock + 0.15, caption=False)
text = NARRATION["n18"]
gat = lambda phrase: a18 + (b18 - a18) * text.index(phrase) / len(text) - film.clock
t_stack = film.clock
film.card("stack", b18 - film.clock + 0.35, groups=[
    {"title": "Strands Agents SDK", "at": round(gat("Strands"), 3), "items": ["Graph with a cycle", "Durable interrupts", "BidiAgent live voice"]},
    {"title": "Tools", "at": round(gat("Seven"), 3), "items": ["7 MCP servers", "Ollama, offline", "Nova and Llama"]},
    {"title": "Amazon Bedrock AgentCore", "at": round(gat("AgentCore"), 3), "items": ["Runtime", "Gateway", "Cedar policy"]},
])
for phrase in ("Strands", "Seven", "AgentCore"):
    film.sound["hits"].append({"t": t_stack + gat(phrase), "p": 0.55})
film.sound["stack"] = t_stack

results = json.loads((ROOT / "eval" / "results-cloud.json").read_text(encoding="utf-8"))
offline = json.loads((ROOT / "eval" / "results-offline.json").read_text(encoding="utf-8"))
results_md = (ROOT / "eval" / "RESULTS.md").read_text(encoding="utf-8")
cost = re.search(r"about \$([0-9.]+)", results_md).group(1)
a19, b19 = film.say("n19", at=film.clock + 0.1, caption=False)
text = NARRATION["n19"]
sat = lambda phrase: a19 + (b19 - a19) * text.index(phrase) / len(text) - film.clock
t_stats = film.clock
attacks = results["attacks"]
assert attacks["breaches"] == 0 and offline["attacks"]["breaches"] == 0, "the film says no attack got through"
assert results["story"]["misquotes"] == 0 and offline["story"]["misquotes"] == 0, "the film says no misquotes"
assert 0.002 < float(cost) < 0.005, "the film says about a third of a cent"
film.card("stats", b19 - film.clock + 1.3, noteAt=round(b19 - film.clock - 1.0, 3), stats=[
    {"at": round(sat("fifteen"), 3), "big": f"0 / {attacks['attacks']}", "small": "attacks got through", "note": "both lanes, cloud and offline"},
    {"at": round(sat("No misquotes"), 3), "big": "0", "small": "misquotes", "note": "re-checked outside the pipeline"},
    {"at": round(sat("about"), 3), "big": f"${float(cost):.3f}", "small": "model cost per case", "note": "cloud lane, excluding voice"},
])
for phrase in ("fifteen", "No misquotes", "about"):
    film.sound["hits"].append({"t": t_stats + sat(phrase), "p": 0.7})

a20, b20 = film.say("n20", at=film.clock + 0.3, caption=False)
t_end = film.clock
film.sound["end"] = t_end
film.sound["hits"].append({"t": t_end + 0.1, "p": 1.0})
film.card("end", max(b20 - film.clock + 2.4, 6.0))

aerial = next(i for i, t in enumerate(times) if t >= M["idle"] - 1)
duration = round(film.clock, 3)
edit = {"fps": FPS, "duration": duration, "times": times, "cursor": ev["cursor"], "aerialFrame": aerial, "shots": film.shots, "captions": film.captions, "overlays": film.overlays,
        "tags": film.tags, "flashes": film.flashes, "phone": phone, "voices": film.voices, "sound": film.sound}
(FILM / "edit.json").write_text(json.dumps(edit), encoding="utf-8")
print(f"film: {duration:.1f} s, call {call_len:.1f} s, {len(film.shots)} shots, {len(film.captions)} captions")
for shot in film.shots:
    print(f"  {shot['t0']:7.2f}-{shot['t1']:7.2f}  {shot['kind']}")
print("agent said:")
for b in bursts:
    print(f"  {in_call(b[0]):7.2f}  {b[4]}")
if duration >= 180:
    print("TOO LONG: must be under 3 minutes")
    raise SystemExit(1)
