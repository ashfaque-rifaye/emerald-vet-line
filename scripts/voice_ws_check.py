"""Tests the console's browser call route: a synthetic caller over the same WebSocket the page uses.

Run with the console running: python scripts/voice_ws_check.py [farmer_id]
"""

from __future__ import annotations

import asyncio
import json
import sys

import boto3
import websockets

RATE = 16000
CHUNK = 3200
TURNS = [
    "Hello, my cow has had high fever for three days and lumps have come up all over her body. Her milk has also gone down.",
    "It is a cow, about three hundred and twenty kilos. Nobody was bitten.",
]


def speak(text: str) -> bytes:
    polly = boto3.client("polly", region_name="us-east-1")
    reply = polly.synthesize_speech(Text=text, LanguageCode="en-IN", VoiceId="Kajal", Engine="neural", OutputFormat="pcm", SampleRate=str(RATE))
    return reply["AudioStream"].read()


async def main(farmer: str) -> int:
    seen = {"audio_chunks": 0, "transcripts": 0, "tools": []}
    async with websockets.connect(f"ws://127.0.0.1:8765/ws/call/{farmer}", max_size=None) as ws:
        async def listen() -> None:
            async for raw in ws:
                message = json.loads(raw)
                if message["type"] == "audio":
                    seen["audio_chunks"] += 1
                elif message["type"] == "transcript":
                    seen["transcripts"] += 1
                    print(f"[{message['role']}] {message['text'][:120]}", flush=True)
                elif message["type"] == "tool":
                    seen["tools"] += message["names"]
                    print("[tool]", message["names"], flush=True)

        listener = asyncio.create_task(listen())
        for text in TURNS:
            pcm = await asyncio.to_thread(speak, text)
            for start in range(0, len(pcm), CHUNK):
                await ws.send(pcm[start: start + CHUNK])
                await asyncio.sleep(0.1)
            for _ in range(25):
                await ws.send(bytes(CHUNK))
                await asyncio.sleep(0.1)
            for _ in range(180):  # keep sending silence while the reply plays, as an open microphone would
                await ws.send(bytes(CHUNK))
                await asyncio.sleep(0.1)
                if "record_case" in seen["tools"] and text is TURNS[-1]:
                    break
        for _ in range(60):
            await ws.send(bytes(CHUNK))
            await asyncio.sleep(0.1)
        listener.cancel()
    print("RESULT:", seen)
    return 0 if "record_case" in seen["tools"] and seen["audio_chunks"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "F010")))
