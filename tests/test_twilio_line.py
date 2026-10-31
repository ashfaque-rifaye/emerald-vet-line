"""Telephone audio conversion and the call instructions. No Twilio account or network is involved."""

import json
import math
import struct

from emerald import actions, ledger, surveillance, twilio_line


def test_mulaw_round_trip_keeps_speech_shape():
    samples = [int(12000 * math.sin(i / 8)) for i in range(800)]
    pcm = struct.pack(f"<{len(samples)}h", *samples)
    back = struct.unpack(f"<{len(samples)}h", twilio_line.mulaw_to_pcm16(twilio_line.pcm16_to_mulaw(pcm)))
    assert max(abs(a - b) for a, b in zip(samples, back)) < 600


def test_known_mulaw_values():
    assert twilio_line.mulaw_to_pcm16(bytes([0xFF])) == (0).to_bytes(2, "little", signed=True)
    assert twilio_line.pcm16_to_mulaw((0).to_bytes(2, "little", signed=True)) == bytes([0xFF])


def test_stream_instructions_point_at_our_socket():
    xml = twilio_line.stream_twiml("https://abc.example.com/twilio/voice", "F010")
    assert 'wss://abc.example.com/twilio/stream' in xml and 'value="F010"' in xml


def test_spoken_text_is_escaped():
    assert "&lt;" in twilio_line.say_twiml("a <b>")


def test_media_message_shape():
    message = json.loads(twilio_line.media_message("MZ1", bytes(320)))
    assert message["event"] == "media" and message["streamSid"] == "MZ1" and message["media"]["payload"]


def test_outbound_stays_simulated_unless_configured(monkeypatch):
    monkeypatch.setenv("EMERALD_TELEPHONY", "TWILIO")
    monkeypatch.delenv("EMERALD_DEMO_PHONE", raising=False)
    case_id = surveillance.record_case("F001", ["skin_nodules"])["case_id"]
    assert actions.call_vet(case_id, "summary")["provider"] == "SIMULATED"


def test_real_calls_go_only_to_the_demo_phone(monkeypatch):
    placed = []
    monkeypatch.setenv("EMERALD_TELEPHONY", "TWILIO")
    monkeypatch.setattr(twilio_line, "configured", lambda: True)
    monkeypatch.setattr(twilio_line, "place_call", lambda text: placed.append(text) or "CA1")
    case_id = surveillance.record_case("F001", ["skin_nodules"])["case_id"]
    result = actions.call_vet(case_id, "summary")
    assert result["provider"] == "TWILIO" and placed == ["summary"]


def test_a_failed_real_call_is_recorded_not_fatal(monkeypatch):
    def down(text):
        raise OSError("no network")

    monkeypatch.setenv("EMERALD_TELEPHONY", "TWILIO")
    monkeypatch.setattr(twilio_line, "configured", lambda: True)
    monkeypatch.setattr(twilio_line, "place_call", down)
    case_id = surveillance.record_case("F001", ["skin_nodules"])["case_id"]
    assert actions.call_vet(case_id, "summary")["status"] == "ok"
    assert any(e["type"] == "real_call_failed" for e in ledger.entries(case_id))
