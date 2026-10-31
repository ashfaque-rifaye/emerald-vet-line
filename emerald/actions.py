"""What Emerald actually does in the world. Every irreversible action re-checks the vet's signature here,
inside the tool, so neither the model nor the agent code can skip it.

Providers: calls and payments start as clearly labelled simulations. Real adapters (Amazon Connect,
AgentCore Payments) plug in behind the same functions.
"""

from __future__ import annotations

import json
import os
import re
import uuid

from . import db, dosing, ledger, registry, signoff, surveillance, triage, twilio_line

MAX_CONSULT_INR = 500.0  # the village fund's per-case cap


def _telephony_provider() -> str:
    wanted = os.environ.get("EMERALD_TELEPHONY", "SIMULATED")
    return wanted if wanted == "TWILIO" and twilio_line.configured() else "SIMULATED"


# What a farmer may never hear from Emerald: a medicine's name or an amount. Only a vet gives those.
_DRUGS = sorted({row.drug for row in dosing.TABLE} | {"oxytetracyline", "flunixine", "sulphadimidine", "sulfa", "furosemide", "enrofloxacin",
                                                       "aminophylline", "aminophyline", "benzathine", "penicillin", "antibiotic", "antibiotics"})
_FORBIDDEN = re.compile(r"\b(" + "|".join(map(re.escape, _DRUGS)) + r")\b|\d+(?:\.\d+)?\s*(?:mg|ml|iu|gm?|tablets?|injections?)\b", re.I)


def _payment_provider() -> str:
    return os.environ.get("EMERALD_PAYMENTS", "SIMULATED")


def _refuse(case_id: str, tool: str, reason: str) -> dict:
    ledger.append("action_refused", {"tool": tool, "reason": reason}, case_id)
    return {"status": "refused", "reason": reason}


def _log_call(case_id: str | None, person: str, role: str, purpose: str, script: str) -> dict:
    call_id = "CALL-" + uuid.uuid4().hex[:8]
    provider = _telephony_provider()
    status = "placed"
    if provider == "TWILIO":
        try:
            twilio_line.place_call(script)
        except OSError as exc:  # a dropped line is recorded, and never stops the rest of the case
            status = "failed"
            ledger.append("real_call_failed", {"call_id": call_id, "error": type(exc).__name__}, case_id)
    with db.connect() as conn:
        conn.execute("INSERT INTO calls (id, case_id, to_person, to_role, purpose, script, provider, status, placed_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (call_id, case_id, person, role, purpose, script, provider, status, ledger.now()))
    return {"call_id": call_id, "provider": provider, "to": person, "role": role}


def call_vet(case_id: str, evidence_summary: str) -> dict:
    """Reversible: a phone call. It carries the evidence pack but changes nothing by itself."""
    case = surveillance.get_case(case_id)
    if case is None:
        return {"status": "refused", "reason": "unknown case"}
    vet = registry.nearest("vets", case["lat"], case["lon"])
    if any(e["type"] == "vet_called" for e in ledger.entries(case_id)):
        return {"status": "ok", "note": "the vet has already been called for this case", "vet": {"id": vet["id"], "name": vet["name"], "fee_inr": vet["fee_inr"]}}
    call = _log_call(case_id, vet["id"], "vet", "evidence_pack", evidence_summary)
    ledger.append("vet_called", {"vet_id": vet["id"], "call_id": call["call_id"], "provider": call["provider"]}, case_id)
    return {"status": "ok", "vet": {"id": vet["id"], "name": vet["name"], "fee_inr": vet["fee_inr"]}, **call}


def notify_vet_of_correction(case_id: str, failed: list[dict]) -> dict:
    """A later check found that a claim the vet was given doesn't hold up. The vet must hear about it."""
    case = surveillance.get_case(case_id)
    if case is None:
        return {"status": "refused", "reason": "unknown case"}
    vet = registry.nearest("vets", case["lat"], case["lon"])
    script = "Correction on an earlier case: " + "; ".join(f'"{f["claim"]}" ({f["reason"]})' for f in failed)
    call = _log_call(case_id, vet["id"], "vet", "correction", script)
    ledger.append("vet_told_of_correction", {"vet_id": vet["id"], "call_id": call["call_id"], "failed": failed}, case_id)
    return {"status": "ok", **call}


def call_doctor(case_id: str, reason: str) -> dict:
    """One Health handoff, for diseases that can pass to people."""
    case = surveillance.get_case(case_id)
    if case is None:
        return {"status": "refused", "reason": "unknown case"}
    doctor = registry.nearest("doctors", case["lat"], case["lon"])
    if any(e["type"] == "doctor_called" for e in ledger.entries(case_id)):
        return {"status": "ok", "note": "the doctor has already been called for this case", "doctor": doctor["name"]}
    call = _log_call(case_id, doctor["id"], "doctor", "human_exposure", reason)
    ledger.append("doctor_called", {"doctor_id": doctor["id"], "call_id": call["call_id"], "reason": reason}, case_id)
    return {"status": "ok", "doctor": doctor["name"], **call}


def tell_farmer(case_id: str, message: str) -> dict:
    case = surveillance.get_case(case_id)
    if case is None:
        return {"status": "refused", "reason": "unknown case"}
    if _FORBIDDEN.search(message):
        return _refuse(case_id, "tell_farmer", "a farmer's message may not name a medicine or an amount. Rewrite it without them and say the vet will decide on treatment.")
    call = _log_call(case_id, case["farmer_id"], "farmer", "guidance", message)
    ledger.append("farmer_told", {"call_id": call["call_id"], "message": message}, case_id)
    return {"status": "ok", **call}


def prescribe_treatment(case_id: str, disease: str, drug: str, signoff_id: str = "") -> dict:
    args = {"case_id": case_id, "disease": disease, "drug": drug}
    ok, why = signoff.is_valid(signoff_id, case_id, "prescribe_treatment", args)
    if not ok:
        return _refuse(case_id, "prescribe_treatment", why)
    case = surveillance.get_case(case_id)
    if not case or not case["weight_kg"]:
        return _refuse(case_id, "prescribe_treatment", "animal weight is needed for a dose")
    dose = dosing.compute(disease, drug, case["weight_kg"])
    if dose["status"] != "ok":
        return _refuse(case_id, "prescribe_treatment", dose["reason"])
    if not signoff.consume(signoff_id):
        return {"status": "ok", "note": "this signed action has already been carried out, so it was not repeated"}
    rx_id = "RX-" + uuid.uuid4().hex[:8]
    with db.connect() as conn:
        conn.execute("INSERT INTO prescriptions (id, case_id, disease, drug, detail, created_at) VALUES (?,?,?,?,?,?)",
                     (rx_id, case_id, disease, drug, json.dumps(dose), ledger.now()))
    ledger.append("treatment_prescribed", {"rx_id": rx_id, "signoff_id": signoff_id, **dose}, case_id)
    return {"status": "ok", "rx_id": rx_id, "signed_by": why, **dose}


def pay_vet_consult(case_id: str, vet_id: str, amount_inr: float, signoff_id: str = "") -> dict:
    args = {"case_id": case_id, "vet_id": vet_id, "amount_inr": amount_inr}
    ok, why = signoff.is_valid(signoff_id, case_id, "pay_vet_consult", args)
    if not ok:
        return _refuse(case_id, "pay_vet_consult", why)
    if amount_inr <= 0 or amount_inr > MAX_CONSULT_INR:
        return _refuse(case_id, "pay_vet_consult", f"amount is outside the fund's cap of {MAX_CONSULT_INR:g} INR")
    if registry.vet(vet_id) is None:
        return _refuse(case_id, "pay_vet_consult", "unknown vet")
    if not signoff.consume(signoff_id):
        return {"status": "ok", "note": "this signed action has already been carried out, so it was not repeated"}
    pay_id = "PAY-" + uuid.uuid4().hex[:8]
    provider = _payment_provider()
    with db.connect() as conn:
        conn.execute("INSERT INTO payments (id, case_id, to_vet, amount, currency, provider, status, reference, paid_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (pay_id, case_id, vet_id, amount_inr, "INR", provider, "settled", None, ledger.now()))
    ledger.append("vet_paid", {"payment_id": pay_id, "vet_id": vet_id, "amount_inr": amount_inr, "provider": provider,
                               "signoff_id": signoff_id}, case_id)
    return {"status": "ok", "payment_id": pay_id, "provider": provider, "amount_inr": amount_inr, "signed_by": why}


def file_outbreak_report(case_id: str, disease: str, signoff_id: str = "") -> dict:
    args = {"case_id": case_id, "disease": disease}
    ok, why = signoff.is_valid(signoff_id, case_id, "file_outbreak_report", args)
    if not ok:
        return _refuse(case_id, "file_outbreak_report", why)
    cluster = surveillance.find_cluster(case_id)
    if not cluster or cluster["disease"] != disease:
        return _refuse(case_id, "file_outbreak_report", "the cluster detector does not support this report")
    if not signoff.consume(signoff_id):
        return {"status": "ok", "note": "this signed action has already been carried out, so it was not repeated"}
    if not surveillance.claim_outbreak_action(disease, "file_outbreak_report", case_id):
        return {"status": "ok", "note": "a report for this outbreak has already been filed"}
    report_id = "RPT-" + uuid.uuid4().hex[:8]
    body = (
        f"Report of suspected {triage.NAMES[disease].lower()} under section 4 of the Prevention and Control of Infectious "
        f"and Contagious Diseases in Animals Act, 2009. Cases: {len(cluster['cases'])}, {cluster['rule']}. "
        f"Case references: {', '.join(c['case_id'] for c in cluster['cases'])}. Reviewed and signed: {why}."
    )
    with db.connect() as conn:
        conn.execute("INSERT INTO reports (id, case_ids, disease, body, filed_at) VALUES (?,?,?,?,?)",
                     (report_id, json.dumps([c["case_id"] for c in cluster["cases"]]), disease, body, ledger.now()))
    ledger.append("outbreak_report_filed", {"report_id": report_id, "disease": disease, "signoff_id": signoff_id, "body": body}, case_id)
    return {"status": "ok", "report_id": report_id, "body": body, "signed_by": why}


def start_ring_calls(case_id: str, disease: str, signoff_id: str = "") -> dict:
    args = {"case_id": case_id, "disease": disease}
    ok, why = signoff.is_valid(signoff_id, case_id, "start_ring_calls", args)
    if not ok:
        return _refuse(case_id, "start_ring_calls", why)
    cluster = surveillance.find_cluster(case_id)
    case = surveillance.get_case(case_id)
    if not cluster or not case or cluster["disease"] != disease:
        return _refuse(case_id, "start_ring_calls", "the cluster detector does not support ring calls")
    if not signoff.consume(signoff_id):
        return {"status": "ok", "note": "this signed action has already been carried out, so it was not repeated"}
    if not surveillance.claim_outbreak_action(disease, "start_ring_calls", case_id):
        return {"status": "ok", "note": "ring calls for this outbreak have already been made"}
    affected = {c["farmer_id"] for c in cluster["cases"]}
    ring = [h for h in registry.households_within(case["lat"], case["lon"], surveillance.RING_RADIUS_KM) if h["id"] not in affected]
    script = (f"Suspected {triage.NAMES[disease].lower()} has been reported near you and a vet has reviewed it. Keep your animals "
              "apart from others, do not buy or sell cattle this week, control flies and ticks, and call back if an animal has fever or skin lumps.")
    for house in ring:
        _log_call(case_id, house["id"], "household", "ring_alert", script)
    ledger.append("ring_calls_started", {"disease": disease, "households": len(ring), "provider": _telephony_provider(),
                                         "signoff_id": signoff_id}, case_id)
    return {"status": "ok", "households_called": len(ring), "provider": _telephony_provider(), "signed_by": why}
