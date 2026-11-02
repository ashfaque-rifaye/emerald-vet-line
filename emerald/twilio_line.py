"""A real phone number, using Twilio. Telephone audio is 8 kHz mu-law, Nova Sonic takes 8 kHz PCM.

Inbound: Twilio streams the call over a WebSocket to /twilio/stream, and it reaches the same PhoneCall the
browser uses. Outbound: vet calls and ring calls are placed through Twilio's REST API and spoken in English.
Needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER and a public URL (see README).
EMERALD_DEMO_PHONE sends every outbound call to one number you own, since the registry's people are synthetic.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request
from xml.sax.saxutils import escape


def _build_decode_table() -> list[int]:
    table = []
    for value in range(256):
        inverted = ~value & 0xFF
        magnitude = (((inverted & 0x0F) << 3) + 0x84) << ((inverted & 0x70) >> 4)
        table.append(0x84 - magnitude if inverted & 0x80 else magnitude - 0x84)
    return table


_DECODE = _build_decode_table()


def mulaw_to_pcm16(data: bytes) -> bytes:
    return b"".join(_DECODE[byte].to_bytes(2, "little", signed=True) for byte in data)


def _encode_sample(sample: int) -> int:
    sign = 0x80 if sample < 0 else 0
    magnitude = min(abs(sample), 32635) + 0x84
    exponent = 7
    for bit in range(14, 7, -1):
        if magnitude & (1 << bit):
            break
        exponent -= 1
    return ~(sign | (exponent << 4) | ((magnitude >> (exponent + 3)) & 0x0F)) & 0xFF


def pcm16_to_mulaw(data: bytes) -> bytes:
    return bytes(_encode_sample(int.from_bytes(data[i: i + 2], "little", signed=True)) for i in range(0, len(data) - 1, 2))


def media_message(stream_sid: str, pcm: bytes) -> str:
    return json.dumps({"event": "media", "streamSid": stream_sid, "media": {"payload": base64.b64encode(pcm16_to_mulaw(pcm)).decode()}})


def clear_message(stream_sid: str) -> str:
    """Stops what the caller is hearing, when they talk over the agent."""
    return json.dumps({"event": "clear", "streamSid": stream_sid})


def stream_twiml(public_url: str, farmer_id: str) -> str:
    host = urllib.parse.urlparse(public_url).netloc
    return (f'<?xml version="1.0" encoding="UTF-8"?><Response><Connect><Stream url="wss://{escape(host)}/twilio/stream">'
            f'<Parameter name="farmer_id" value="{escape(farmer_id)}"/></Stream></Connect></Response>')


def say_twiml(text: str) -> str:
    return f'<Response><Say language="en-IN" voice="Polly.Raveena">{escape(text)}</Say></Response>'


def configured() -> bool:
    return all(os.environ.get(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER", "EMERALD_DEMO_PHONE"))


def place_call(text: str) -> str:
    """Speaks text to the demo phone. Real people are never dialled from the synthetic registry."""
    sid, token = os.environ["TWILIO_ACCOUNT_SID"], os.environ["TWILIO_AUTH_TOKEN"]
    form = urllib.parse.urlencode({"To": os.environ["EMERALD_DEMO_PHONE"], "From": os.environ["TWILIO_FROM_NUMBER"], "Twiml": say_twiml(text)}).encode()
    request = urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json", data=form, method="POST")
    request.add_header("Authorization", "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode())
    with urllib.request.urlopen(request, timeout=20) as reply:
        return json.loads(reply.read())["sid"]
