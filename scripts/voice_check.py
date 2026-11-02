"""Proves the phone line end to end with no microphone: a caller is synthesised with Amazon Polly
and streamed in as real audio, turn by turn. The caller's voice is synthetic and the farmer is fictional.

Run: python scripts/voice_check.py
"""

from __future__ import annotations

import asyncio
import base64
import os
import shutil
import sys
import wave
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "voice-check"
shutil.rmtree(DATA, ignore_errors=True)
os.environ["EMERALD_DATA"] = str(DATA)

from strands.bidi.types.events import (  # noqa: E402
    BidiAudioDeltaEvent, BidiResponseStopEvent, BidiToolUseBlocksEvent, BidiTranscriptBlockEvent,
)
from strands.bidi.types.media import AudioDelta  # noqa: E402

from emerald import ledger, voice  # noqa: E402

RATE = 16000
CHUNK = 3200  # 100 ms of 16-bit mono
CALLER_TURNS = [
    "Hello, my cow has had high fever for three days and lumps have come up all over her body. Her milk has also gone down.",
    "It is a cow, about three hundred and twenty kilos. Nobody was bitten.",
    "Okay. Can I give her some medicine now? Just tell me which medicine and how much.",
]


def speak(text: str) -> bytes:
    polly = boto3.client("polly", region_name="us-east-1")
    reply = polly.synthesize_speech(Text=text, LanguageCode="en-IN", VoiceId="Kajal", Engine="neural", OutputFormat="pcm", SampleRate=str(RATE))
    return reply["AudioStream"].read()


async def stream_audio(agent, pcm: bytes) -> None:
    for start in range(0, len(pcm), CHUNK):
        delta = {"audio_delta": {"format": "pcm", "source": {"bytes": pcm[start: start + CHUNK]}}}
        await agent.send(delta)
        await asyncio.sleep(0.1)
    silence = bytes(CHUNK)
    for _ in range(25):  # voice activity detection needs to hear the caller stop
        await agent.send({"audio_delta": {"format": "pcm", "source": {"bytes": silence}}})
        await asyncio.sleep(0.1)


async def run() -> int:
    call = voice.PhoneCall("F001")
    agent = call.agent
    await agent.start()
    replies: list[bytes] = []
    done = asyncio.Event()
    turn_ended = asyncio.Event()

    async def listen() -> None:
        async for event in agent.receive():
            if isinstance(event, BidiTranscriptBlockEvent):
                print(f"[{event.role}] {event.transcript}", flush=True)
            elif isinstance(event, BidiToolUseBlocksEvent):
                print(f"[tool] {[t['name'] for t in event.tool_uses]} {[t['input'] for t in event.tool_uses]}", flush=True)
            elif isinstance(event, BidiAudioDeltaEvent):
                replies.append(base64.b64decode(event.audio))
            elif isinstance(event, BidiResponseStopEvent):
                turn_ended.set()
            if done.is_set():
                return

    listener = asyncio.create_task(listen())
    try:
        for text in CALLER_TURNS:
            print(f"\n[caller, Polly] {text}", flush=True)
            turn_ended.clear()
            await stream_audio(agent, await asyncio.to_thread(speak, text))
            try:
                await asyncio.wait_for(turn_ended.wait(), timeout=40)
            except asyncio.TimeoutError:
                print("[no reply within 40 s]", flush=True)
            await asyncio.sleep(6)  # let the reply finish speaking
    finally:
        done.set()
        await agent.stop()
        listener.cancel()

    with wave.open(str(DATA / "reply.wav"), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(b"".join(replies))
    print(f"\nreply audio: {DATA / 'reply.wav'} ({sum(map(len, replies)) / (2 * RATE):.1f} s)")
    if call.case is None:
        print("RESULT: no case was recorded")
        return 1
    print(f"RESULT: case {call.case['case_id']}, signs {call.case['reported_signs']}, weight {call.case['weight_kg']}, "
          f"candidates {[c['disease'] for c in call.case['candidates']]}")
    if call.worker:
        call.worker.join(timeout=240)
    if call.outcome:
        print(f"after the call: {call.outcome.status}, {len(call.outcome.verified)} claims verified, waiting on {[p['summary'] for p in call.outcome.pending]}")
    print("ledger:", [e["type"] for e in ledger.entries()])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
