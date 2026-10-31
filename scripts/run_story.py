"""The demo story from the terminal: three nearby calls, one vet, one outbreak response.

Run: python scripts/run_story.py [--offline] [--no-second-opinion]
Uses a fresh data folder per run. All people are synthetic; calls and payments are labelled simulations.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--no-second-opinion", action="store_true")
    parser.add_argument("--data", default=str(ROOT / "data" / "story"))
    args = parser.parse_args()
    if args.offline:
        os.environ["EMERALD_LANE"] = "offline"
    shutil.rmtree(args.data, ignore_errors=True)
    os.environ["EMERALD_DATA"] = args.data

    from emerald import db, ledger, pipeline, registry, signoff

    def line(text: str = "") -> None:
        print(text, flush=True)

    base = registry.farmer("F001")
    near = [f for f in registry.world()["farmers"] if registry.distance_km(base["lat"], base["lon"], f["lat"], f["lon"]) < 6]
    signs = ["fever", "skin_nodules", "reduced_milk", "nasal_discharge"]
    semantic = not args.no_second_opinion
    started = time.time()
    last = None

    for number, farmer in enumerate(near[:3], 1):
        line(f"\n=== Call {number}: {farmer['name']}, {farmer['village']} ===")
        outcome = pipeline.handle_case(farmer["id"], signs, weight_kg=320, semantic=semantic)
        last = outcome
        line(f"Case {outcome.case_id}, candidates: {[c['disease'] for c in outcome.assessment['candidates']]}")
        line(f"Evidence: {len(outcome.verified)} verified, {len(outcome.rejected)} rejected")
        for claim in outcome.verified:
            line(f"  OK   {claim['claim']}\n       \"{claim['quote']}\"\n       {claim['citation']}")
        for bad in outcome.rejected:
            line(f"  FAIL {bad['claim']}: {bad['reason']}")
        if outcome.cluster:
            line(f"CLUSTER: {outcome.cluster['disease_name']}, {len(outcome.cluster['cases'])} cases, {outcome.cluster['ring_households']} households in the ring")
        rounds = 0
        while outcome.status == "waiting_for_vet" and rounds < 6:
            rounds += 1
            for item in outcome.pending:
                line(f"  VET ASKED: {item['summary']}")
                decision = signoff.decide(item["signoff_id"], "V01", registry.DEMO_VET_PIN, True)
                line(f"  VET: {decision['status']}")
            outcome = pipeline.resume(outcome.case_id)
        line(f"Result: {outcome.status}. {outcome.final_text}")

    line("\n=== What actually happened ===")
    with db.connect() as conn:
        for table in ("calls", "payments", "prescriptions", "reports"):
            line(f"{table}: {conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]}")
        for row in conn.execute("SELECT detail FROM prescriptions LIMIT 1"):
            detail = json.loads(row["detail"])
            line(f"sample prescription: {detail['drug']} {detail['total_dose']} {detail['route']}")
        for row in conn.execute("SELECT body FROM reports LIMIT 1"):
            line(f"report: {row['body']}")
    types: dict[str, int] = {}
    for entry in ledger.entries():
        types[entry["type"]] = types.get(entry["type"], 0) + 1
    line(f"ledger: {types}")
    line(f"ledger verification: {ledger.verify()}")
    line(f"elapsed: {time.time() - started:.0f}s, lane: {os.environ.get('EMERALD_LANE', 'cloud')}")
    return 0 if last else 1


if __name__ == "__main__":
    sys.exit(main())
