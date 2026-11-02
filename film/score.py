"""The film's sound, synthesised here (no licensed music) and mixed on the edit's cue sheet.
Writes data/film/film.wav.

  uv run --no-project --with numpy --with scipy python film/score.py
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

ROOT = Path(__file__).resolve().parent.parent
FILM = ROOT / "data" / "film"
SR = 48000
rng = np.random.default_rng(5)
edit = json.loads((FILM / "edit.json").read_text(encoding="utf-8"))
S = edit["sound"]
DUR = edit["duration"]


def load(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def bus(dur: float) -> np.ndarray:
    return np.zeros((int(dur * SR), 2))


def put(b: np.ndarray, x: np.ndarray, t: float, gain: float = 1.0, pan: float = 0.0) -> None:
    i = int(t * SR)
    if i >= len(b) or i < 0:
        return
    x = x[: len(b) - i]
    b[i: i + len(x), 0] += x * gain * np.cos((pan + 1) * np.pi / 4)
    b[i: i + len(x), 1] += x * gain * np.sin((pan + 1) * np.pi / 4)


def tv(d: float) -> np.ndarray:
    return np.arange(int(d * SR)) / SR


def bandpass(x, lo, hi):
    return sosfilt(butter(4, [lo, hi], btype="band", fs=SR, output="sos"), x)


def lowpass(x, hi):
    return sosfilt(butter(2, hi, btype="low", fs=SR, output="sos"), x)


def thump(power=1.0):
    t = tv(1.3)
    f = 34 + 90 * np.exp(-t * 22)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 3.6)
    click = lowpass(rng.standard_normal(len(t)), 3500) * np.exp(-t * 90) * 0.35
    return np.tanh((body + click) * 1.6) * power


def tick():
    t = tv(0.03)
    return np.sin(2 * np.pi * 2400 * t) * np.exp(-t * 260)


def bell(f, d=2.6):
    t = tv(d)
    x = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * k) for r, a, k in [(1, 1, 2.2), (2.76, 0.45, 3.8), (5.4, 0.22, 6), (8.93, 0.1, 9)])
    return x * np.minimum(1, t / 0.002)


def pluck(f, d=0.9):
    t = tv(d)
    x = np.sin(2 * np.pi * f * t) + 0.4 * np.sin(4 * np.pi * f * t) * np.exp(-t * 6)
    return x * np.exp(-t * 4.5) * np.minimum(1, t / 0.003)


def pad(freqs, d, cutoff=900, attack=1.2, release=1.6):
    t = tv(d)
    x = np.zeros(len(t))
    for f in freqs:
        for det in (-0.35, 0.0, 0.42):
            ph = rng.uniform(0, 6.28)
            x += np.sign(np.sin(2 * np.pi * (f + det) * t + ph)) * 0.25 + np.sin(2 * np.pi * (f + det) * t + ph)
    x = lowpass(x, cutoff) / (len(freqs) * 3)
    return x * np.minimum(1, t / attack) * np.minimum(1, np.maximum(0, d - t) / release)


def riser(d):
    t = tv(d)
    n = rng.standard_normal(len(t))
    out = np.zeros(len(t))
    steps = 40
    for s in range(steps):
        a, b = int(s * len(t) / steps), int((s + 1) * len(t) / steps)
        fc = 300 * (40 ** (s / steps))
        out[a:b] = bandpass(n[a:b], fc * 0.7, min(fc * 1.3, 20000))
    return out * (t / d) ** 2.4


def whoosh(d=0.6):
    t = tv(d)
    n = rng.standard_normal(len(t))
    return bandpass(n, 500, 6000) * np.sin(np.pi * t / d) ** 2


def buzz(d=0.28):
    t = tv(d)
    return np.tanh(np.sign(np.sin(2 * np.pi * 110 * t)) * 0.6 + np.sin(2 * np.pi * 165 * t) * 0.6) * np.minimum(1, (d - t) / 0.05)


def ringback(d):
    # India: 400 Hz with 25 Hz modulation, 0.4 on, 0.2 off, 0.4 on.
    t = tv(d)
    x = np.sin(2 * np.pi * 400 * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 25 * t))
    gate = (((t >= 0) & (t < 0.4)) | ((t >= 0.6) & (t < 1.0))).astype(float)
    return x * np.convolve(gate, np.ones(240) / 240, mode="same")


def reverb(x, secs=2.6, wet=0.25):
    t = tv(secs)
    ir = np.stack([rng.standard_normal(len(t)), rng.standard_normal(len(t))], axis=1) * (np.exp(-t * 2.4))[:, None]
    ir = np.apply_along_axis(lambda c: lowpass(c, 6000), 0, ir)
    out = np.stack([fftconvolve(x[:, i], ir[:, i])[: len(x)] for i in range(2)], axis=1)
    out /= max(1e-9, np.abs(out).max())
    return x + out * np.abs(x).max() * wet * 3


D_MINOR = [73.42, 110.0, 146.83, 174.61, 220.0]
D_MAJOR = [73.42, 110.0, 146.83, 185.0, 220.0, 293.66, 369.99]
PENTA = [293.66, 329.63, 369.99, 440.0, 493.88, 587.33, 659.25, 739.99, 880.0, 987.77, 1174.66]
music, fx, voice = bus(DUR + 3), bus(DUR + 3), bus(DUR + 3)

# --- the opening: dread under the facts, the chord opening on the logo
put(music, pad(D_MINOR[:3], S["logo"] + 0.3, cutoff=520, attack=1.6, release=0.3), 0, 0.5)
for beat in np.arange(0.7, S["n03"], 0.86):
    put(fx, thump(0.16), float(beat))
for i in range(18):
    put(fx, tick(), S["n02"] + 1.4 * (1 - (1 - i / 18) ** 2), 0.14, pan=rng.uniform(-0.3, 0.3))
put(music, pad(D_MAJOR, S["ring"] - S["logo"] + 2.6, cutoff=2100, attack=0.08, release=1.6), S["logo"], 0.72)
for i, n in enumerate([587.33, 739.99, 880.0, 1174.66, 1479.98]):
    put(fx, bell(n, 3.0), S["logo"] + 0.06 * i, 0.16 - 0.02 * i, pan=-0.4 + 0.2 * i)

# --- the phone, then a warm bed under the call
for i in range(2):
    put(fx, bandpass(ringback(1.05), 300, 3400), S["ring"] + i * 1.3, 0.16, pan=0.3)
call0, call1 = S["call"]
put(music, pad([146.83, 220.0, 293.66, 369.99], call1 - call0 + 1.5, cutoff=800, attack=2.0, release=1.0), call0, 0.24)
t = tv(0.04)
put(fx, lowpass(rng.standard_normal(len(t)), 5000) * np.exp(-t * 150), S["hangup"], 0.3, pan=0.3)

# --- proof: quiet pulse, thinking
stop = S["stop"]
put(music, pad([146.83, 220.0, 293.66], stop - S["proof"] + 0.6, cutoff=1000, attack=0.6, release=0.4), S["proof"], 0.3)
for i, at in enumerate(np.arange(S["proof"] + 0.4, stop - 0.2, 0.3)):
    put(music, pluck(PENTA[[0, 3, 5, 3, 2, 4][i % 6]]), float(at), 0.07, pan=np.sin(i * 1.3) * 0.5)

# --- "everything stops": the music drops out, leaving the low tone under the signature
put(music, pad(D_MINOR[:2], S["hold"] + 1.35 - stop, cutoff=380, attack=0.05, release=0.2), stop, 0.5)
put(fx, riser(1.25), S["hold"], 0.42)
for i, n in enumerate([587.33, 880.0, 1174.66]):
    put(fx, bell(n, 2.6), S["hold"] + 1.25 + 0.05 * i, 0.2, pan=-0.2 + i * 0.2)

# --- the outbreak: a driving pulse that builds to the ring
out0 = S["outbreak"]
ring0, ring1 = S["ring_homes"]
beat = 0.42
put(music, pad([98.0, 146.83, 196.0, 233.08], ring0 - out0 + 0.5, cutoff=850, attack=0.4, release=0.3), out0, 0.45)
for at in np.arange(out0, ring0, beat):
    put(fx, thump(0.22), float(at))
put(fx, riser(1.25), S["hold2"], 0.36)
put(music, pad(D_MAJOR, ring1 - ring0 + 2.0, cutoff=1900, attack=0.05, release=1.8), ring0, 0.55)
homes = np.arange(ring0 + 0.1, ring0 + 3.0, 3.0 / 13)
for i, at in enumerate(homes):
    put(fx, pluck(PENTA[i % len(PENTA)]), float(at), 0.17, pan=np.sin(i * 1.7) * 0.7)

# --- night: everything low and dark, then the dawn on "signal returns"
night, day = S["night"], S["day"]
put(music, pad([55.0, 82.41, 110.0], day - night + 1.0, cutoff=320, attack=0.2, release=1.0), night, 0.7)
put(music, pad(D_MAJOR, S["stack"] - day + 1.0, cutoff=1500, attack=1.4, release=0.5), day, 0.5)

# --- stack, stats and the end: the whole chord, opening up
end = S["end"]
put(music, pad([146.83, 220.0, 293.66, 369.99, 440.0], end - S["stack"] + 0.5, cutoff=1500, attack=0.2, release=0.3), S["stack"], 0.55)
for i, at in enumerate(np.arange(S["stack"], end, 0.2)):
    put(music, pluck(PENTA[int((i / 6) % 9)]), float(at), 0.07, pan=np.sin(i * 1.3) * 0.6)
put(fx, riser(1.1), end - 1.0, 0.26)
put(music, pad(D_MAJOR, DUR - end + 1.5, cutoff=2400, attack=0.08, release=2.6), end, 0.9)
for i, n in enumerate([587.33, 739.99, 880.0, 1174.66, 1479.98]):
    put(fx, bell(n, 3.4), end + 0.1 + 0.06 * i, 0.22 - 0.03 * i, pan=-0.4 + 0.2 * i)

# --- one-shots from the edit
for h in S["hits"]:
    put(fx, thump(h["p"]), h["t"])
for at in S["whoosh"]:
    put(fx, whoosh(), at - 0.1, 0.1)
for at in S["ticks"]:
    put(fx, bell(1760, 0.7), at, 0.12, pan=0.2)
for at in S["errors"]:
    put(fx, buzz(), at, 0.14)
for b in S["bells"]:
    put(fx, bell(b["f"], 1.6), b["t"], b["g"], pan=0.4)

# --- voices
agent = np.frombuffer((FILM / "take" / "agent.pcm").read_bytes(), dtype=np.int16).astype(np.float64) / 32768
speech = np.zeros(len(voice))
for v in edit["voices"]:
    if "pcm" in v:
        clip = agent[v["pcm"][0] // 2: (v["pcm"][0] + v["pcm"][1]) // 2]
        clip = np.interp(np.arange(0, len(clip) * 3) / 3, np.arange(len(clip)), clip)  # 16 kHz to 48 kHz
        clip = bandpass(clip, 240, 3800)  # the phone line
        clip = np.tanh(clip * 2.0) / 2.0
        clip = clip / max(1e-6, np.abs(clip).max()) * 0.5
        put(voice, clip, v["at"], 0.95, pan=0.08)
    else:
        clip = load(ROOT / v["file"]).astype(np.float64)
        if v["bus"] == "farmer":
            clip = bandpass(clip, 180, 6500)
        clip = clip / max(1e-6, np.abs(clip).max()) * 0.5
        put(voice, clip, v["at"], 1.0 if v["bus"] == "narration" else 0.95, pan=-0.05 if v["bus"] == "farmer" else 0)
    i = int(v["at"] * SR)
    speech[i: i + len(clip)] = 1

# --- mix: music and effects step back whenever anyone speaks
ramp = int(0.18 * SR)
duck = np.convolve(speech, np.ones(ramp) / ramp, mode="same")
music *= (1 - 0.68 * duck)[:, None]
fx *= (1 - 0.3 * duck)[:, None]
mix = reverb(music, 3.0, 0.24) + reverb(fx, 1.8, 0.14) + reverb(voice, 0.35, 0.012)
n = int(DUR * SR)
mix = mix[:n]
mix *= np.minimum(1, (n - np.arange(n)) / (0.8 * SR))[:, None]
mix = np.tanh(mix * 1.05)
mix /= np.abs(mix).max() / 0.92
raw = FILM / "film.raw.wav"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ac", "2", "-ar", str(SR), "-i", "-", str(raw)], input=(mix * 32767).astype(np.int16).tobytes(), check=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(raw), "-af", "loudnorm=I=-15:TP=-1.2:LRA=11", "-ar", str(SR), str(FILM / "film.wav")], check=True)
raw.unlink()
print("wrote", FILM / "film.wav", f"{DUR:.1f} s")
