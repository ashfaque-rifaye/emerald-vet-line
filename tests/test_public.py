"""The hosted demo's limits: a public link must not be able to run up a bill or reach the laptop-only lane."""

import pytest
from fastapi.testclient import TestClient

from emerald import public, server


@pytest.fixture(autouse=True)
def hosted(monkeypatch):
    monkeypatch.setenv("EMERALD_PUBLIC", "1")
    monkeypatch.setenv("EMERALD_LANE", "cloud")
    public._mine.clear()
    public._everyone.clear()


def test_a_visitor_is_limited_per_hour():
    per_visitor = public.LIMITS["case"][0]
    assert all(public.allow("case", "1.2.3.4", now=100.0) is None for _ in range(per_visitor))
    assert public.allow("case", "1.2.3.4", now=100.0)
    assert public.allow("case", "5.6.7.8", now=100.0) is None
    assert public.allow("case", "1.2.3.4", now=100.0 + 3601) is None


def test_everyone_together_is_limited_per_day():
    per_day = public.LIMITS["sync"][2]
    for i in range(per_day):
        assert public.allow("sync", f"10.0.0.{i}", now=0.0) is None
    assert public.allow("sync", "10.9.9.9", now=0.0)


def test_the_address_cloudfront_saw_is_used_not_one_the_visitor_wrote():
    assert public.visitor({"x-forwarded-for": "6.6.6.6, 203.0.113.9"}, "10.0.0.1") == "203.0.113.9"
    assert public.visitor({}, "10.0.0.1") == "10.0.0.1"


def test_limits_are_off_on_a_laptop(monkeypatch):
    monkeypatch.delenv("EMERALD_PUBLIC")
    assert all(public.allow("voice", "1.2.3.4") is None for _ in range(50))


def test_the_hosted_demo_refuses_the_offline_lane_and_the_phone_line():
    client = TestClient(server.app)
    refused = client.post("/api/lane", json={"lane": "offline"})
    assert refused.status_code == 403 and "laptop" in refused.json()["reason"]
    assert client.post("/twilio/voice").status_code == 404
    assert client.get("/api/state").json()["lane"] == "cloud"
