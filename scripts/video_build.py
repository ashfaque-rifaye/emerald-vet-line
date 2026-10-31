"""Cuts the demo video from real footage (scripts/video_record.py), explainer cards (docs/scenes.html) and narration.

Narration: Amazon Polly. Agent and caller audio in the call scene are the real audio from the recording.
No music. Output: data/video/emerald-demo.mp4 and .srt

  uv run --no-project --with playwright --with boto3 python scripts/video_build.py
"""

from __future__ import annotations

import base64
import json
import subprocess
import wave
from pathlib import Path

import boto3
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "video"
WORK = OUT / "build"
FOOTAGE = OUT / "footage.webm"
SCENES_URL = "http://localhost:8765/docs/scenes.html"
VOICE, ENGINE, LANG = "Kajal", "neural", "en-IN"
RATE = 16000
FPS = 30
LABEL_SPED = "Sped up"


def run(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], capture_output=True, check=True, text=True).stdout
    return float(out.strip())


def narrate(name: str, lines: list[str]) -> tuple[Path, list[tuple[str, float]]]:
    """Speaks each sentence separately, so captions can follow the real timing."""
    polly = boto3.client("polly", region_name="us-east-1")
    pcm, timing = b"", []
    for line in lines:
        audio = polly.synthesize_speech(Text=line, VoiceId=VOICE, Engine=ENGINE, LanguageCode=LANG, OutputFormat="pcm", SampleRate=str(RATE))["AudioStream"].read()
        pcm += audio + bytes(int(RATE * 2 * 0.16))
        timing.append((line, (len(audio) / (2 * RATE)) + 0.16))
    path = WORK / f"{name}.wav"
    write_wav(path, pcm)
    return path, timing


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(pcm)


def render_cards(params: dict) -> None:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        for scene in ("title", "arch", "results", "end"):
            page.goto(f"{SCENES_URL}?scene={scene}&{query}")
            page.wait_for_timeout(600)
            page.screenshot(path=str(WORK / f"card-{scene}.png"))
        page.set_content('<body style="margin:0;background:transparent"><div style="display:inline-block;padding:8px 16px;border-radius:99px;background:rgba(5,20,14,.78);color:#fff;font:600 22px Segoe UI,sans-serif">Sped up</div></body>')
        page.locator("div").screenshot(path=str(WORK / "sped.png"), omit_background=True)
        browser.close()


def card_clip(name: str, audio: Path, card: str) -> Path:
    out = WORK / f"{name}.mp4"
    seconds = duration(audio) + 0.5
    frames = int(seconds * FPS)
    zoom = f"zoompan=z='1+0.035*on/{frames}':d={frames}:s=1920x1080:fps={FPS}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    run("-loop", "1", "-i", str(WORK / f"card-{card}.png"), "-i", str(audio), "-filter_complex", f"[0:v]{zoom},format=yuv420p[v];[1:a]apad[a]", "-map", "[v]", "-map", "[a]",
        "-t", f"{seconds:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS), "-c:a", "aac", "-ar", "48000", str(out))
    return out


def footage_clip(name: str, audio: Path | None, parts: list[tuple[float, float]], target: float | None = None) -> Path:
    """Cuts windows out of the footage and fits them to the narration, labelled when sped up by more than a little."""
    seconds = target if target else duration(audio) + 0.5
    total = sum(end - start for start, end in parts)
    factor = seconds / total
    chain, labels = [], []
    for i, (start, end) in enumerate(parts):
        chain.append(f"[0:v]trim={start}:{end},setpts=(PTS-STARTPTS)*{factor:.5f},fps={FPS},scale=1920:1080[p{i}]")
        labels.append(f"[p{i}]")
    graph = ";".join(chain) + ";" + "".join(labels) + f"concat=n={len(parts)}:v=1:a=0[c]"
    sped = factor < 0.8
    inputs = ["-i", str(FOOTAGE)]
    if sped:
        inputs += ["-i", str(WORK / "sped.png")]
        graph += ";[c][1:v]overlay=W-w-500:H-h-20,format=yuv420p[v]"
    else:
        graph += ";[c]format=yuv420p[v]"
    audio_index = 2 if sped else 1
    if audio:
        inputs += ["-i", str(audio)]
        graph += f";[{audio_index}:a]apad[a]"
        maps = ["-map", "[v]", "-map", "[a]"]
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono"]
        maps = ["-map", "[v]", "-map", f"{audio_index}:a"]
    out = WORK / f"{name}.mp4"
    run(*inputs, "-filter_complex", graph, *maps, "-t", f"{seconds:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS), "-c:a", "aac", "-ar", "48000", str(out))
    return out


def call_track(marks: dict, chunks: list) -> tuple[bytes, list[tuple[float, float]]]:
    """Rebuilds what was heard on the call: the caller's file and the agent's real replies, on the video's clock."""
    with wave.open(str(OUT / "caller.wav"), "rb") as source:
        caller = source.readframes(source.getnframes())
    start = marks["call_start"]
    length = int((marks["call_end"] - start + 2) * RATE) * 2
    track = bytearray(length)
    caller_part = caller[: length]
    track[: len(caller_part)] = caller_part
    cursor, windows = 0.0, []
    for at, audio in chunks:
        pcm = base64.b64decode(audio)
        place = max(at - start, cursor)
        begin = int(place * RATE) * 2
        end = begin + len(pcm)
        if end > len(track):
            break
        for i in range(0, len(pcm), 2):
            mixed = int.from_bytes(track[begin + i: begin + i + 2], "little", signed=True) + int.from_bytes(pcm[i: i + 2], "little", signed=True)
            track[begin + i: begin + i + 2] = max(-32768, min(32767, mixed)).to_bytes(2, "little", signed=True)
        if windows and place - windows[-1][1] < 1.2:
            windows[-1][1] = place + len(pcm) / (2 * RATE)
        else:
            windows.append([place, place + len(pcm) / (2 * RATE)])
        cursor = place + len(pcm) / (2 * RATE)
    return bytes(track), [(a, b) for a, b in windows]


def real_audio_clip(name: str, track: bytes, marks: dict, start: float, end: float) -> Path:
    """A stretch of the call at real speed, with its real audio."""
    pcm = track[int(start * RATE) * 2: int(end * RATE) * 2]
    wav = WORK / f"{name}.wav"
    write_wav(wav, pcm)
    begin = marks["call_start"] + start
    out = WORK / f"{name}.mp4"
    run("-ss", f"{begin:.3f}", "-t", f"{end - start:.3f}", "-i", str(FOOTAGE), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-vf", f"fps={FPS},scale=1920:1080,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-ar", "48000", "-shortest", str(out))
    return out


def stamp(seconds: float) -> str:
    h, rem = int(seconds // 3600), seconds % 3600
    return f"{h:02d}:{int(rem // 60):02d}:{rem % 60:06.3f}".replace(".", ",")


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    marks = json.loads((OUT / "marks.json").read_text(encoding="utf-8"))
    chunks = json.loads((OUT / "agent_audio.json").read_text(encoding="utf-8"))
    results = json.loads((ROOT / "eval" / "results-cloud.json").read_text(encoding="utf-8"))
    render_cards({"cost": "$0.003", "time": f'{results["story"]["median_third_call_to_vet_request_s"]:.0f} s', "recall": f'{results["intake"]["overall"]["recall"]:.2f}'})
    track, windows = call_track(marks, chunks)
    turns = marks["caller_turns"]
    print("reply windows:", [(round(a, 1), round(b, 1)) for a, b in windows], "caller turns:", turns)
    # First exchange: caller's words through the agent's first reply. Second: asks for a dose, and the refusal.
    first_reply = next(w for w in windows if w[0] > turns[0])
    second_reply = next((w for w in windows if w[0] > turns[1]), windows[-1])
    first_end = min(first_reply[1] + 0.6, turns[0] + 34)
    second_end = min(second_reply[1] + 0.6, turns[1] + 18)

    script = [
        ("hook", "card", "title", [
            "A sick cow is a health problem and a money problem at once.",
            "A 2022 report to India's Parliament put public-sector field vets at twenty-eight thousand, against thirty-six thousand approved posts.",
            "Most farm AI gives advice. Emerald makes the phone call, shows its sources, and waits for the vet."]),
        ("call-intro", "foot", [(marks["idle"], marks["call_start"] + 1)], [
            "A farmer dials in. No app, no reading. This is the live system, with a synthetic Hindi caller."]),
        ("call-1", "real", turns[0] - 0.3, first_end),
        ("call-2", "real", turns[1] - 0.3, second_end),
        ("proof", "foot", [(marks["proof"], marks["vet"])], [
            "Asked for a dose, it refused. Now a Strands graph checks the evidence.",
            "Models can only cite numbered sentences from official guidelines, and a second model rejects overreach."]),
        ("vet", "foot", [(marks["vet"], marks["first_signature"] + 3)], [
            "Nothing irreversible happens until a vet signs. A Strands interrupt pauses the agent, and the tool itself verifies a signature over that exact action.",
            "Change the amount, and it's void. Use it twice, and it's refused."]),
        ("cluster", "foot", [(marks["story_start"], marks["cluster"] + 6), (marks["outbreak_ask"] - 1, marks["outbreak_ask"] + 6)], [
            "Two more calls come in nearby. A plain-code detector sees three cases within ten kilometres.",
            "Emerald drafts the report required by section four of the 2009 Act, and waits for the vet again."]),
        ("ring", "foot", [(marks["ring"] - 2, marks["ring"] + 8)], [
            "Once it's signed, every registered home in the ring gets a warning call. The ring is drawn to true scale."]),
        ("ledger", "foot", [(marks["ledger"], marks["tamper"] + 6)], [
            "Every step goes into a signed hash chain. Try to change one past payment, and the chain breaks, in plain sight."]),
        ("night", "foot", [(marks["night"], marks["offline_proof"] + 6)], [
            "Now cut the signal. The same graph and the same MCP tools move to a local model on this laptop.",
            "These danger signs trigger code, not a model: don't open the carcass, and a doctor is called, because this disease can infect people."]),
        ("seal", "foot", [(marks["day"], marks["end"] - 1)], [
            "When signal returns, the record is sealed in S3 Object Lock, and Bedrock reviews what the local model decided. Anything weak goes back to the vet."]),
        ("arch", "card", "arch", [
            "It's deployed on AgentCore Runtime, with tools behind AgentCore Gateway, and a Cedar policy that denies by default."]),
        ("results", "card", "results", [
            "In tests on synthetic cases, none of fifteen attacks got through, with no misquotes.",
            "The evaluation also caught real bugs, like one signature paying a vet twice. Those are fixed.",
            "It hasn't been used with real farmers, and a vet still needs to review it. That's next."]),
        ("end", "card", "end", ["The code is open. Run it, and try to break it."]),
    ]

    clips, srt, clock, index = [], [], 0.0, 1
    for scene in script:
        name, kind = scene[0], scene[1]
        if kind == "real":
            clip = real_audio_clip(name, track, marks, scene[2], scene[3])
            srt.append(f"{index}\n{stamp(clock)} --> {stamp(clock + duration(clip))}\n[Live call in Hindi, with English shown on screen]\n")
            index += 1
        else:
            audio, timing = narrate(name, scene[-1])
            if kind == "card":
                clip = card_clip(name, audio, scene[2])
            else:
                clip = footage_clip(name, audio, scene[2])
            at = clock
            for line, seconds in timing:
                srt.append(f"{index}\n{stamp(at)} --> {stamp(at + seconds)}\n{line}\n")
                at += seconds
                index += 1
        clips.append(clip)
        clock += duration(clip)
        print(f"{name}: {duration(clip):.1f} s, total {clock:.1f} s", flush=True)

    listing = WORK / "list.txt"
    listing.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8")
    final = OUT / "emerald-demo.mp4"
    run("-f", "concat", "-safe", "0", "-i", str(listing), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-ar", "48000", "-movflags", "+faststart", str(final))
    (OUT / "emerald-demo.srt").write_text("\n".join(srt), encoding="utf-8")
    print(f"final: {duration(final):.1f} s, {final.stat().st_size / 1e6:.0f} MB")
    return 0 if duration(final) < 180 else 1


if __name__ == "__main__":
    raise SystemExit(main())
