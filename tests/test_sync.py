"""The return-to-signal path, with a fake S3 and a scripted second-opinion model."""

import json

import pytest

from emerald import ledger, surveillance, sync

from .test_gate import ScriptedModel


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    def put_object(self, **kwargs) -> None:
        self.objects[kwargs["Key"]] = kwargs


@pytest.fixture(autouse=True)
def bucket(monkeypatch):
    monkeypatch.setenv("EMERALD_LEDGER_BUCKET", "test-bucket")


def offline_case() -> str:
    case_id = surveillance.record_case("F001", ["skin_nodules"])["case_id"]
    ledger.append("evidence_checked", {"attempt": 1, "passed": 2, "rejected": [], "verified": [
        {"claim": "It could be lumpy skin disease.", "quote": "Firm, round nodules appear on the skin", "citation": "x"},
        {"claim": "It is definitely fatal.", "quote": "Firm, round nodules appear on the skin", "citation": "x"},
    ]}, case_id)
    ledger.append("second_opinion_deferred", {"claims": 2}, case_id)
    return case_id


def test_push_uploads_each_entry_once_with_a_lock():
    offline_case()
    s3 = FakeS3()
    first = sync.push(s3)
    assert first["uploaded"] == len(ledger.entries()) and first["uploaded"] > 0
    entry = next(v for k, v in s3.objects.items() if k.startswith("ledger/"))
    assert entry["ObjectLockMode"] == "GOVERNANCE" and "ObjectLockRetainUntilDate" in entry
    assert sync.push(s3)["uploaded"] == 0


def test_uploaded_record_is_enough_to_recheck_the_chain():
    offline_case()
    s3 = FakeS3()
    sync.push(s3)
    rows = [json.loads(v["Body"]) for k, v in sorted(s3.objects.items()) if k.startswith("ledger/")]
    assert [r["prev_hash"] for r in rows[1:]] == [r["hash"] for r in rows[:-1]]


def test_second_opinion_failure_reaches_the_vet():
    case_id = offline_case()
    model = ScriptedModel([json.dumps({"failed": [{"index": 1, "reason": "overstates the quote"}]})])
    results = sync.run_second_opinions(model)
    assert results[0]["failed"][0]["claim"] == "It is definitely fatal."
    assert any(e["type"] == "vet_told_of_correction" for e in ledger.entries(case_id))


def test_second_opinions_run_once_per_case():
    offline_case()
    sync.run_second_opinions(ScriptedModel(['{"failed": []}']))
    assert sync.run_second_opinions(ScriptedModel(['{"failed": []}'])) == []


def test_clean_second_opinion_does_not_bother_the_vet():
    case_id = offline_case()
    sync.run_second_opinions(ScriptedModel(['{"failed": []}']))
    assert not any(e["type"] == "vet_told_of_correction" for e in ledger.entries(case_id))
