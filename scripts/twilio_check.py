"""Tests the phone bridge without a Twilio account: this script behaves as Twilio does, sending a synthetic
caller as 8 kHz mu-law Media Stream messages to the running console.

Run with the console running: python scripts/twilio_check.py [farmer_id]
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
import urllib.request
from pathlib import Path

import boto3
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from emerald import twilio_line  # noqa: E402

RATE = 8000
FRAME = 160  # 20 ms of mu-law, the size Twilio sends
TURNS = [
    "Hello, my cow has had high fever for three days and lumps have come up all over her body. Her milk has also gone down.",
    "It is a cow, about three hundred and twenty kilos. Nobody was bitten.",
]


def speak(text: str) -> bytes:
    polly = boto3.client("polly", region_name="us-east-1")
    reply = polly.synthesize_speech(Text=text, LanguageCode="en-IN", VoiceId="Kajal", Engine="neural", OutputFormat="pcm", SampleRate=str(RATE))
    return twilio_line.pcm16_to_mulaw(reply["AudioStream"].read())


def media(payload: bytes) -> str:
    return json.dumps({"event": "media", "media": {"payload": base64.b64encode(payload).decode()}})


def cases() -> list[dict]:
    with urllib.request.urlopen("http://127.0.0.1:8765/api/state", timeout=30) as reply:
        return json.loads(reply.read())["cases"]


async def main(farmer: str) -> int:
    before = len(cases())
    received = {"media": 0, "bytes": 0}
    async with websockets.connect("ws://127.0.0.1:8765/twilio/stream", max_size=None) as ws:
        await ws.send(json.dumps({"event": "start", "start": {"streamSid": "MZcheck", "customParameters": {"farmer_id": farmer}}}))

        async def listen() -> None:
            async for raw in ws:
                message = json.loads(raw)
                if message["event"] == "media":
                    received["media"] += 1
                    received["bytes"] += len(base64.b64decode(message["media"]["payload"]))

        listener = asyncio.create_task(listen())
        silence = bytes([0xFF]) * FRAME
        for text in TURNS:
            audio = await asyncio.to_thread(speak, text)
            for start in range(0, len(audio), FRAME):
                await ws.send(media(audio[start: start + FRAME]))
                await asyncio.sleep(0.02)
            for _ in range(900):  # about 18 s of open line while the agent replies
                await ws.send(media(silence))
                await asyncio.sleep(0.02)
        await ws.send(json.dumps({"event": "stop"}))
        listener.cancel()
    after = cases()
    print(f"reply audio from the agent: {received['bytes'] / RATE:.1f} s in {received['media']} messages")
    if len(after) <= before:
        print("RESULT: no case was recorded")
        return 1
    case = after[0]
    print(f"RESULT: case {case['id']}, signs {case['signs']}, weight {case['weight_kg']}, could be {[c['disease'] for c in case['candidates']]}")
    return 0 if received["bytes"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "F020")))
