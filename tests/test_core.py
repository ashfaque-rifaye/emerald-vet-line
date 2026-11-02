"""The guarantees that must hold whatever a model says. No model is involved in these tests."""

import json

import pytest

from emerald import actions, db, dosing, knowledge, ledger, proof, registry, signoff, surveillance, triage


def lsd_passage():
    return next(p for p in knowledge.passages() if p["disease"] == "lsd" and p["section"] == "treatment")


# --- proof ---

def test_real_quote_passes():
    p = lsd_passage()
    check = proof.check_claim(proof.Claim(claim="There is no specific treatment for lumpy skin disease.",
                                          passage_id=p["id"], quote="There is no specific treatment for LSD"))
    assert check.ok and "PDF page" in check.citation


def test_invented_quote_is_rejected():
    p = lsd_passage()
    check = proof.check_claim(proof.Claim(claim="Ivermectin cures it.", passage_id=p["id"], quote="Ivermectin cures lumpy skin disease quickly"))
    assert not check.ok


def test_missing_passage_is_rejected():
    check = proof.check_claim(proof.Claim(claim="x", passage_id="nope", quote="There is no specific treatment"))
    assert not check.ok


def test_number_not_in_quote_is_rejected():
    p = lsd_passage()
    check = proof.check_claim(proof.Claim(claim="Give 50 mg per kg.", passage_id=p["id"], quote="There is no specific treatment for LSD"))
    assert not check.ok and "50" in check.reason


def test_search_finds_the_right_disease():
    top = knowledge.search("nodules on skin high fever", k=3)
    assert any(p["disease"] == "lsd" for p in top)


def test_lab_and_sampling_methods_are_not_in_the_knowledge_base():
    # Emerald's job ends at "call the vet". The store should hold nothing about lab handling of pathogens.
    banned = ("sample collection", "virus isolation", "viral transport", "biopsies", "culture medium")
    for p in knowledge.passages():
        if p["doc"] == "svtg":
            assert not any(term in p["text"].lower() for term in banned), (p["disease"], p["page"])


# --- dosing ---

def test_every_dose_quote_is_really_in_the_guidelines():
    for row in dosing.TABLE:
        text = " ".join(p["text"] for p in knowledge.passages() if p["disease"] == row.disease and p["section"] == "treatment")
        assert knowledge.normalise(row.quote) in knowledge.normalise(text), row.quote


def test_dose_is_arithmetic():
    assert dosing.compute("lsd", "oxytetracycline", 300)["total_dose"] == "3000 mg"
    assert dosing.compute("hs", "ceftiofur", 100)["total_dose"] == "110-220 mg"


def test_first_row_for_lsd_is_not_an_antibiotic():
    assert not next(r for r in dosing.TABLE if r.disease == "lsd").antibiotic


def test_unknown_pair_goes_to_the_vet():
    assert dosing.compute("rabies", "oxytetracycline", 300)["status"] == "vet_decides"
    assert dosing.compute("anthrax", "oxytetracycline", 300)["status"] == "vet_decides"


def test_absurd_weight_is_refused():
    assert dosing.compute("lsd", "oxytetracycline", 3000)["status"] == "refused"


# --- triage ---

def test_nodules_suggest_lsd():
    assert triage.assess(["skin_nodules", "fever"])["candidates"][0]["disease"] == "lsd"


def test_sudden_death_with_bleeding_raises_a_red_flag_and_calls_for_a_doctor():
    flags = triage.assess(["sudden_death", "bleeding_from_body_openings"])["red_flags"]
    assert flags[0]["code"] == "possible_anthrax" and flags[0]["pull_in_doctor"]


def test_notifiable_list_matches_the_act():
    schedule = next(p for p in knowledge.passages() if p["section"] == "schedule")["text"].lower()
    for name in ("anthrax", "rabies", "lumpy skin disease", "haemorrhagic septicaemia"):
        assert name in schedule


# --- sign-off ---

def make_case(farmer="F001", weight=300):
    return surveillance.record_case(farmer, ["skin_nodules", "fever"], weight_kg=weight)["case_id"]


def approved(case_id, tool, args):
    req = signoff.request(case_id, tool, args, "test")
    assert signoff.decide(req["id"], "V01", registry.DEMO_VET_PIN, True)["status"] == "approved"
    return req["id"]


def test_irreversible_tools_refuse_without_a_signature():
    case_id = make_case()
    assert actions.prescribe_treatment(case_id, "lsd", "oxytetracycline")["status"] == "refused"
    assert actions.pay_vet_consult(case_id, "V01", 300)["status"] == "refused"
    assert actions.file_outbreak_report(case_id, "lsd")["status"] == "refused"
    assert actions.start_ring_calls(case_id, "lsd")["status"] == "refused"


def test_pending_or_declined_signoff_does_not_authorise():
    case_id = make_case()
    args = {"case_id": case_id, "disease": "lsd", "drug": "oxytetracycline"}
    req = signoff.request(case_id, "prescribe_treatment", args, "test")
    assert actions.prescribe_treatment(case_id, "lsd", "oxytetracycline", req["id"])["status"] == "refused"
    signoff.decide(req["id"], "V01", registry.DEMO_VET_PIN, False)
    assert actions.prescribe_treatment(case_id, "lsd", "oxytetracycline", req["id"])["status"] == "refused"


def test_wrong_pin_cannot_approve():
    case_id = make_case()
    req = signoff.request(case_id, "pay_vet_consult", {"case_id": case_id, "vet_id": "V01", "amount_inr": 300}, "test")
    assert signoff.decide(req["id"], "V01", "0000", True)["status"] == "refused"
    assert signoff.get(req["id"])["status"] == "pending"


def test_changing_the_action_voids_the_signature():
    case_id = make_case()
    sid = approved(case_id, "pay_vet_consult", {"case_id": case_id, "vet_id": "V01", "amount_inr": 300})
    assert actions.pay_vet_consult(case_id, "V01", 450, sid)["status"] == "refused"
    assert actions.pay_vet_consult(case_id, "V02", 300, sid)["status"] == "refused"
    assert actions.pay_vet_consult(case_id, "V01", 300, sid)["status"] == "ok"


def test_signature_cannot_be_reused_on_another_case():
    case_a, case_b = make_case("F001"), make_case("F002")
    sid = approved(case_a, "pay_vet_consult", {"case_id": case_a, "vet_id": "V01", "amount_inr": 300})
    assert actions.pay_vet_consult(case_b, "V01", 300, sid)["status"] == "refused"


def test_forged_status_in_the_database_is_caught():
    case_id = make_case()
    args = {"case_id": case_id, "vet_id": "V01", "amount_inr": 300}
    req = signoff.request(case_id, "pay_vet_consult", args, "test")
    with db.connect() as conn:
        conn.execute("UPDATE signoffs SET status='approved', vet_id='V01', signature='AAAA' WHERE id=?", (req["id"],))
    assert actions.pay_vet_consult(case_id, "V01", 300, req["id"])["status"] == "refused"


def test_one_signature_pays_only_once():
    case_id = make_case()
    sid = approved(case_id, "pay_vet_consult", {"case_id": case_id, "vet_id": "V01", "amount_inr": 300})
    assert actions.pay_vet_consult(case_id, "V01", 300, sid)["status"] == "ok"
    second = actions.pay_vet_consult(case_id, "V01", 300, sid)
    assert "already" in second["note"]
    assert sum(e["type"] == "vet_paid" for e in ledger.entries(case_id)) == 1


def test_concurrent_spends_of_one_signature_pay_once():
    from concurrent.futures import ThreadPoolExecutor

    case_id = make_case()
    sid = approved(case_id, "pay_vet_consult", {"case_id": case_id, "vet_id": "V01", "amount_inr": 300})
    with ThreadPoolExecutor(6) as pool:
        list(pool.map(lambda _: actions.pay_vet_consult(case_id, "V01", 300, sid), range(6)))
    assert sum(e["type"] == "vet_paid" for e in ledger.entries(case_id)) == 1


def test_one_signature_prescribes_only_once():
    case_id = make_case()
    sid = approved(case_id, "prescribe_treatment", {"case_id": case_id, "disease": "lsd", "drug": "meloxicam"})
    actions.prescribe_treatment(case_id, "lsd", "meloxicam", sid)
    actions.prescribe_treatment(case_id, "lsd", "meloxicam", sid)
    assert sum(e["type"] == "treatment_prescribed" for e in ledger.entries(case_id)) == 1


def test_a_refused_payment_does_not_spend_the_signature():
    case_id = make_case()
    sid = approved(case_id, "pay_vet_consult", {"case_id": case_id, "vet_id": "V01", "amount_inr": 5000})
    actions.pay_vet_consult(case_id, "V01", 5000, sid)
    assert signoff.get(sid)["used_at"] is None


def test_payment_cap_holds_even_with_a_signature():
    case_id = make_case()
    sid = approved(case_id, "pay_vet_consult", {"case_id": case_id, "vet_id": "V01", "amount_inr": 5000})
    assert actions.pay_vet_consult(case_id, "V01", 5000, sid)["status"] == "refused"


def test_signed_prescription_uses_code_computed_dose():
    case_id = make_case(weight=320)
    sid = approved(case_id, "prescribe_treatment", {"case_id": case_id, "disease": "lsd", "drug": "oxytetracycline"})
    result = actions.prescribe_treatment(case_id, "lsd", "oxytetracycline", sid)
    assert result["status"] == "ok" and result["total_dose"] == "3200 mg"


# --- what a farmer may hear ---

def test_farmer_message_naming_a_drug_is_refused():
    case_id = make_case()
    for text in ("Please treat them with meloxicam as prescribed.", "Give 500 mg now.", "An ANTIBIOTIC should help.", "Use 10 ml twice a day."):
        assert actions.tell_farmer(case_id, text)["status"] == "refused", text
    assert not any(e["type"] == "farmer_told" for e in ledger.entries(case_id))


def test_ordinary_farmer_advice_passes():
    case_id = make_case()
    assert actions.tell_farmer(case_id, "Keep this animal away from others. The vet is being called, and 3 nearby farms are affected.")["status"] == "ok"


# --- cluster ---

def nearby_farmers(n):
    base = registry.farmer("F001")
    near = [f for f in registry.world()["farmers"] if registry.distance_km(base["lat"], base["lon"], f["lat"], f["lon"]) < 5]
    assert len(near) >= n
    return near[:n]


def test_two_cases_are_not_a_cluster_three_are():
    farmers = nearby_farmers(3)
    first, second = make_case(farmers[0]["id"]), make_case(farmers[1]["id"])
    assert surveillance.find_cluster(second) is None and first != second
    cluster = surveillance.find_cluster(make_case(farmers[2]["id"]))
    assert cluster["disease"] == "lsd" and len(cluster["cases"]) == 3


def test_old_cases_do_not_count():
    farmers = nearby_farmers(3)
    surveillance.record_case(farmers[0]["id"], ["skin_nodules"], reported_at="2020-01-01T00:00:00+00:00")
    surveillance.record_case(farmers[1]["id"], ["skin_nodules"], reported_at="2020-01-02T00:00:00+00:00")
    assert surveillance.find_cluster(make_case(farmers[2]["id"])) is None


def test_report_is_refused_without_a_real_cluster_even_if_signed():
    case_id = make_case()
    sid = approved(case_id, "file_outbreak_report", {"case_id": case_id, "disease": "lsd"})
    assert actions.file_outbreak_report(case_id, "lsd", sid)["status"] == "refused"


def test_signed_ring_calls_reach_households():
    ids = [make_case(f["id"]) for f in nearby_farmers(3)]
    sid = approved(ids[2], "start_ring_calls", {"case_id": ids[2], "disease": "lsd"})
    result = actions.start_ring_calls(ids[2], "lsd", sid)
    assert result["status"] == "ok" and result["households_called"] > 0 and result["provider"] == "SANDBOX"


def test_one_outbreak_gets_one_report_and_one_round_of_calls():
    ids = [make_case(f["id"]) for f in nearby_farmers(4)]
    for tool, fn in (("file_outbreak_report", actions.file_outbreak_report), ("start_ring_calls", actions.start_ring_calls)):
        assert fn(ids[2], "lsd", approved(ids[2], tool, {"case_id": ids[2], "disease": "lsd"}))["status"] == "ok"
        second = fn(ids[3], "lsd", approved(ids[3], tool, {"case_id": ids[3], "disease": "lsd"}))
        assert "already" in second["note"]
    assert sum(e["type"] == "outbreak_report_filed" for e in ledger.entries()) == 1
    assert sum(e["type"] == "ring_calls_started" for e in ledger.entries()) == 1


def test_only_one_of_many_concurrent_claims_wins():
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(8) as pool:
        wins = list(pool.map(lambda i: surveillance.claim_outbreak_action("lsd", "start_ring_calls", f"C-{i}"), range(8)))
    assert sum(wins) == 1


# --- ledger ---

def test_ledger_chain_verifies():
    make_case()
    assert ledger.verify()["ok"]


@pytest.mark.parametrize("sql", [
    "UPDATE ledger SET payload='{}' WHERE seq=1",
    "DELETE FROM ledger WHERE seq=1",
    "UPDATE ledger SET ts='2000-01-01' WHERE seq=2",
])
def test_ledger_detects_tampering(sql):
    make_case("F001")
    make_case("F002")
    with db.connect() as conn:
        conn.execute(sql)
    assert not ledger.verify()["ok"]


def test_refused_actions_are_logged():
    case_id = make_case()
    actions.pay_vet_consult(case_id, "V01", 300)
    assert any(e["type"] == "action_refused" for e in ledger.entries(case_id))


def test_ledger_never_holds_location():
    case_id = make_case()
    assert all("lat" not in json.loads(e["payload"]) for e in ledger.entries(case_id))
