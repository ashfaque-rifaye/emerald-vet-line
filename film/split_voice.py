"""Splits one recording of film/VOICE_SCRIPT.md into a file per line, on the 2-second pauses.

  python film/split_voice.py data/voice/take.m4a
Writes data/voice/f1.wav ... n20.wav. Separate re-takes named data/voice/<id>.<ext> win over the split.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "film"))
from lines import FARMER, NARRATION  # noqa: E402

VOICE = ROOT / "data" / "voice"
KEYS = [k for k, _ in FARMER] + list(NARRATION)


def speech_segments(path: Path, noise: str = "-36dB", gap: float = 1.2) -> list[tuple[float, float]]:
    log = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", f"silencedetect=n={noise}:d={gap}", "-f", "null", "-"], capture_output=True, text=True).stderr
    hours, minutes, secs = re.findall(r"time=(\d+):(\d+):([\d.]+)", log)[-1]
    total = int(hours) * 3600 + int(minutes) * 60 + float(secs)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    segments, cursor = [], 0.0
    for a, b in zip(starts, ends + [total]):
        if a > cursor + 0.2:
            segments.append((cursor, a))
        cursor = b
    if total > cursor + 0.2:
        segments.append((cursor, total))
    return [s for s in segments if s[1] - s[0] > 0.35]


def main() -> int:
    take = Path(sys.argv[1])
    for noise in ("-36dB", "-40dB", "-32dB", "-44dB", "-28dB"):
        segments = speech_segments(take, noise)
        print(f"{noise}: {len(segments)} lines found, expected {len(KEYS)}")
        if len(segments) == len(KEYS):
            break
    else:
        print("The count doesn't match, so nothing was written. Listen for an extra pause or a missed line.")
        for i, (a, b) in enumerate(segments):
            print(f"  {i + 1:2d}  {a:7.1f} to {b:7.1f}  ({b - a:.1f} s)")
        return 1
    for key, (a, b) in zip(KEYS, segments):
        retake = [p for p in VOICE.glob(f"{key}.*") if p.suffix != ".wav"]
        args = ["-i", str(retake[0])] if retake else ["-ss", f"{max(0, a - 0.1):.3f}", "-to", f"{b + 0.15:.3f}", "-i", str(take)]
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args, "-ac", "1", "-ar", "48000", str(VOICE / f"{key}.wav")], check=True)
        print(f"{key}: {b - a:.1f} s{'  (re-take)' if retake else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
