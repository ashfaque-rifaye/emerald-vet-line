"""Doses are computed by this code, never by a model. Each row quotes the guideline it came from.

Only cattle and buffalo, only the drugs named in each disease's treatment section. If a drug and disease
pair is not in this table the answer is "vet decides". The guidelines give no milk withdrawal figures for
these entries, so that field is left for the vet to fill in at sign-off rather than guessed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dose:
    disease: str
    drug: str
    low_per_kg: float
    high_per_kg: float
    unit: str
    route: str
    days: str
    quote: str
    antibiotic: bool = True


# Non-antibiotic rows come first for each disease. An empty days value means the guideline gives no
# duration, so the vet sets it.
TABLE = [
    Dose("fmd", "oxytetracycline", 10, 10, "mg", "IV", "3-5", "oxytetracyline @10 mg/ kg BW IV for 3-5 days"),
    Dose("fmd", "dihydrostreptomycin", 10, 10, "mg", "IM", "3-5", "dihydrostreptomycin @ 10 mg/kg BW IM"),
    Dose("lsd", "meloxicam", 0.2, 0.5, "mg", "IM", "", "meloxicam @ 0.2-0.5 mg/ kg BW IM", antibiotic=False),
    Dose("lsd", "flunixin", 1.1, 2.2, "mg", "IM", "", "flunixine meglumine @ 1.1-2.2 mg/kg BW IM", antibiotic=False),
    Dose("lsd", "oxytetracycline", 10, 10, "mg", "IM", "", "oxytetracyline @ 10 mg/kg BW IM"),
    Dose("lsd", "dihydrostreptomycin", 10, 10, "mg", "IM", "", "dihydrostreptomycin @ 10 mg/kg BW IM"),
    Dose("hs", "sulphatrimethoprim", 30, 30, "mg", "IM/IV", "3-5", "Sulphatrimethoprim @ 30 mg/Kg BW IM/IV SID"),
    Dose("hs", "ceftiofur", 1.1, 2.2, "mg", "IM", "3-5", "Ceftiofur @ 1.1-2.2 mg/ Kg BW SID IM for 3-5 days"),
    Dose("bq", "penicillin g", 22000, 44000, "IU", "IM", "4-5", "Penicillin G @dose of 22,000-44,000 IU / kg BW IM may be administered for 4-5 days"),
]


def compute(disease: str, drug: str, weight_kg: float) -> dict:
    if not 20 <= weight_kg <= 1200:
        return {"status": "refused", "reason": f"weight {weight_kg} kg is not plausible for cattle or buffalo"}
    wanted = drug.strip().lower()
    for row in TABLE:
        if row.disease == disease and row.drug == wanted:
            low, high = row.low_per_kg * weight_kg, row.high_per_kg * weight_kg
            total = f"{low:g} {row.unit}" if low == high else f"{low:g}-{high:g} {row.unit}"
            return {
                "status": "ok", "disease": disease, "drug": row.drug, "weight_kg": weight_kg, "total_dose": total,
                "route": row.route, "days": row.days or "vet to set", "antibiotic": row.antibiotic, "source_quote": row.quote,
                "milk_withdrawal": "not stated in the guideline entry; vet must specify",
            }
    return {"status": "vet_decides", "reason": f"{drug} for {disease} has no dose in the source table"}
