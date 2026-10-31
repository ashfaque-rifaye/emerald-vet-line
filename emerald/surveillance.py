"""Case store and outbreak detection. Plain code, so a model can't talk it out of raising an alert."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

from . import db, ledger, registry, triage

CLUSTER_MIN_CASES = 3
CLUSTER_RADIUS_KM = 10.0
CLUSTER_WINDOW_DAYS = 7
RING_RADIUS_KM = 10.0


def record_case(farmer_id: str, signs: list[str], species: str = "cattle", weight_kg: float | None = None,
                reported_at: str | None = None) -> dict:
    person = registry.farmer(farmer_id)
    if person is None:
        raise ValueError(f"unknown farmer {farmer_id}")
    assessment = triage.assess(signs)
    case_id = "C-" + uuid.uuid4().hex[:8]
    when = reported_at or ledger.now()
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO cases (id, farmer_id, reported_at, lat, lon, species, signs, weight_kg, candidates, red_flags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (case_id, farmer_id, when, person["lat"], person["lon"], species, json.dumps(assessment["reported_signs"]),
             weight_kg, json.dumps(assessment["candidates"]), json.dumps(assessment["red_flags"])),
        )
    # Location is left out of the ledger: it is the one record meant to be shared, and it should not map households.
    ledger.append("case_recorded", {"farmer_id": farmer_id, "signs": assessment["reported_signs"],
                                    "candidates": [c["disease"] for c in assessment["candidates"]],
                                    "red_flags": [f["code"] for f in assessment["red_flags"]]}, case_id)
    return {"case_id": case_id, "farmer": person, **assessment, "weight_kg": weight_kg, "species": species, "reported_at": when}


def get_case(case_id: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
    if row is None:
        return None
    case = dict(row)
    for field in ("signs", "candidates", "red_flags"):
        case[field] = json.loads(case[field])
    return case


def outbreak_actions_done(disease: str) -> set[str]:
    """Which outbreak actions already happened for this disease this week, across all cases, so a cluster
    of three calls produces one report and one round of ring calls."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=CLUSTER_WINDOW_DAYS)
    done: set[str] = set()
    for entry in ledger.entries():
        if entry["type"] in ("outbreak_report_filed", "ring_calls_started") and _parse(entry["ts"]) >= cutoff:
            if json.loads(entry["payload"]).get("disease") == disease:
                done.add("file_outbreak_report" if entry["type"] == "outbreak_report_filed" else "start_ring_calls")
    return done


def claim_outbreak_action(disease: str, action: str, case_id: str) -> bool:
    """Atomic: if several cases reach this at once, exactly one wins, so a household is never called twice."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=CLUSTER_WINDOW_DAYS)).isoformat(timespec="seconds")
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        taken = conn.execute("SELECT 1 FROM outbreak_claims WHERE disease=? AND action=? AND claimed_at>=?",
                             (disease, action, cutoff)).fetchone()
        if taken:
            return False
        conn.execute("INSERT INTO outbreak_claims (disease, action, case_id, claimed_at) VALUES (?,?,?,?)",
                     (disease, action, case_id, ledger.now()))
    return True


def _parse(ts: str) -> datetime:
    value = datetime.fromisoformat(ts)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def find_cluster(case_id: str) -> dict | None:
    """Same suspected disease, close together, within the time window. Open to inspection by design."""
    case = get_case(case_id)
    if case is None:
        return None
    start = _parse(case["reported_at"]) - timedelta(days=CLUSTER_WINDOW_DAYS)
    notifiable = [c["disease"] for c in case["candidates"] if c["notifiable"]]
    with db.connect() as conn:
        others = [dict(r) for r in conn.execute("SELECT * FROM cases")]
    for disease in notifiable:
        members = []
        for other in others:
            if disease not in {c["disease"] for c in json.loads(other["candidates"])}:
                continue
            if not start <= _parse(other["reported_at"]) <= _parse(case["reported_at"]):
                continue
            km = registry.distance_km(case["lat"], case["lon"], other["lat"], other["lon"])
            if km <= CLUSTER_RADIUS_KM:
                members.append({"case_id": other["id"], "farmer_id": other["farmer_id"], "km": round(km, 1),
                                "reported_at": other["reported_at"]})
        if len(members) >= CLUSTER_MIN_CASES:
            ring = registry.households_within(case["lat"], case["lon"], RING_RADIUS_KM)
            affected = {m["farmer_id"] for m in members}
            result = {
                "disease": disease, "disease_name": triage.NAMES[disease], "cases": members,
                "rule": f"{CLUSTER_MIN_CASES}+ cases within {CLUSTER_RADIUS_KM:g} km in {CLUSTER_WINDOW_DAYS} days",
                "ring_households": len([h for h in ring if h["id"] not in affected]),
            }
            if not any(e["type"] == "cluster_detected" for e in ledger.entries(case_id)):
                ledger.append("cluster_detected", {"disease": disease, "case_ids": [m["case_id"] for m in members],
                                                   "rule": result["rule"]}, case_id)
            return result
    return None
