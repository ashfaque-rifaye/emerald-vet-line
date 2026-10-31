"""Deterministic triage. A model can add to this result but can never remove a red flag.

The sign lists come from the clinical signs sections of the Standard Veterinary Treatment Guidelines.
"""

from __future__ import annotations

SIGNS = {
    "fever", "skin_nodules", "swollen_lymph_nodes", "reduced_milk", "nasal_discharge", "eye_discharge",
    "mouth_blisters", "hoof_lesions", "teat_blisters", "drooling", "lameness", "not_eating",
    "neck_or_throat_swelling", "breathing_difficulty", "sudden_death", "bleeding_from_body_openings",
    "muscle_swelling_crackling", "abnormal_behaviour", "aggression", "cannot_swallow", "bitten_by_animal",
    "swollen_udder", "abnormal_milk", "painful_udder",
}

# Disease -> signs that point to it, and the signs without which it is not suggested.
RULES = {
    "lsd": {"signs": {"skin_nodules", "fever", "swollen_lymph_nodes", "reduced_milk", "nasal_discharge", "eye_discharge", "lameness"}, "needs": {"skin_nodules"}},
    "fmd": {"signs": {"mouth_blisters", "hoof_lesions", "teat_blisters", "drooling", "fever", "lameness", "not_eating"}, "needs": {"mouth_blisters", "hoof_lesions", "teat_blisters"}},
    "hs": {"signs": {"neck_or_throat_swelling", "breathing_difficulty", "drooling", "fever", "nasal_discharge", "sudden_death"}, "needs": {"neck_or_throat_swelling", "breathing_difficulty"}},
    "anthrax": {"signs": {"sudden_death", "bleeding_from_body_openings", "fever", "breathing_difficulty"}, "needs": {"bleeding_from_body_openings", "sudden_death"}},
    "bq": {"signs": {"muscle_swelling_crackling", "lameness", "fever", "sudden_death", "not_eating"}, "needs": {"muscle_swelling_crackling"}},
    "rabies": {"signs": {"abnormal_behaviour", "aggression", "cannot_swallow", "bitten_by_animal", "drooling"}, "needs": {"abnormal_behaviour", "aggression", "cannot_swallow", "bitten_by_animal"}},
    "mastitis": {"signs": {"swollen_udder", "abnormal_milk", "painful_udder", "fever", "reduced_milk"}, "needs": {"swollen_udder", "abnormal_milk", "painful_udder"}},
}

NAMES = {
    "lsd": "Lumpy skin disease", "fmd": "Foot and mouth disease", "hs": "Haemorrhagic septicaemia",
    "anthrax": "Anthrax", "bq": "Black quarter", "rabies": "Rabies", "mastitis": "Mastitis",
}

# Scheduled under the 2009 Act, so reporting is a legal duty. Black quarter and mastitis are not on the schedule.
NOTIFIABLE = {"lsd", "fmd", "hs", "anthrax", "rabies"}


def assess(signs: list[str]) -> dict:
    reported = {s for s in signs if s in SIGNS}
    candidates = []
    for disease, rule in RULES.items():
        if reported & rule["needs"]:
            matched = sorted(reported & rule["signs"])
            candidates.append({"disease": disease, "name": NAMES[disease], "matched_signs": matched,
                               "notifiable": disease in NOTIFIABLE})
    candidates.sort(key=lambda c: len(c["matched_signs"]), reverse=True)

    flags = []
    if "bleeding_from_body_openings" in reported or "sudden_death" in reported:
        flags.append({
            "code": "possible_anthrax", "pull_in_doctor": True,
            "instruction": "Do not open or move the carcass, and keep people and animals away. A vet and a doctor are being called.",
            "passage_query": "no postmortem of suspected dead animals",
        })
    if reported & {"bitten_by_animal", "aggression"} or {"abnormal_behaviour", "cannot_swallow"} <= reported:
        flags.append({
            "code": "possible_rabies", "pull_in_doctor": True,
            "instruction": "Keep away from the animal and isolate it. Anyone bitten or scratched should wash the wound and see a doctor today.",
            "passage_query": "prompt first aid for bite wounds",
        })
    return {"reported_signs": sorted(reported), "unrecognised_signs": sorted(set(signs) - SIGNS),
            "candidates": candidates, "red_flags": flags}
