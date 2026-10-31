"""Synthetic people and places. No real farmer, vet or doctor appears anywhere in this project."""

from __future__ import annotations

import json
import math
import random
from functools import lru_cache

from . import config, keys

CENTRE = (26.45, 74.64)  # a fictional dairy cluster in the Ajmer area of Rajasthan
GIVEN = ["Sunita", "Ramesh", "Geeta", "Mohan", "Kamla", "Bhanwar", "Lali", "Suresh", "Pushpa", "Hemraj", "Santosh", "Kishan"]
FAMILY = ["Devi", "Lal", "Meena", "Gurjar", "Jat", "Rawat", "Kumawat", "Bai"]
VILLAGES = ["Rampura", "Kishanpura", "Bhojpur", "Mandawar", "Nayagaon", "Sarwar Khera"]
DEMO_VET_PIN = "4321"  # synthetic vets only; printed in the demo on purpose


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat, dlon = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(a))


def _scatter(rng: random.Random, spread: float) -> tuple[float, float]:
    return round(CENTRE[0] + rng.uniform(-spread, spread), 4), round(CENTRE[1] + rng.uniform(-spread, spread), 4)


def _build() -> dict:
    rng = random.Random(1962)
    farmers = []
    for i in range(60):
        lat, lon = _scatter(rng, 0.14)
        farmers.append({"id": f"F{i + 1:03d}", "name": f"{rng.choice(GIVEN)} {rng.choice(FAMILY)}", "village": rng.choice(VILLAGES),
                        "lat": lat, "lon": lon, "cattle": rng.randint(1, 6), "phone": f"+91-90000-{i + 1:05d}", "language": "hi"})
    vets = [
        {"id": "V01", "name": "Dr. A. Sharma (synthetic)", "lat": 26.47, "lon": 74.70, "phone": "+91-90001-00001", "fee_inr": 300},
        {"id": "V02", "name": "Dr. N. Khan (synthetic)", "lat": 26.31, "lon": 74.52, "phone": "+91-90001-00002", "fee_inr": 300},
        {"id": "V03", "name": "Dr. R. Verma (synthetic)", "lat": 26.60, "lon": 74.81, "phone": "+91-90001-00003", "fee_inr": 300},
    ]
    doctors = [{"id": "D01", "name": "Primary Health Centre, Rampura (synthetic)", "lat": 26.46, "lon": 74.62, "phone": "+91-90002-00001"}]
    return {"farmers": farmers, "vets": vets, "doctors": doctors}


@lru_cache(maxsize=1)
def world() -> dict:
    file = config.data_dir() / "registry.json"
    if file.exists():
        return json.loads(file.read_text(encoding="utf-8"))
    built = _build()
    file.write_text(json.dumps(built, indent=1), encoding="utf-8")
    for vet in built["vets"]:
        keys.set_pin(vet["id"], DEMO_VET_PIN)
    return built


def farmer(farmer_id: str) -> dict | None:
    return next((f for f in world()["farmers"] if f["id"] == farmer_id), None)


def vet(vet_id: str) -> dict | None:
    return next((v for v in world()["vets"] if v["id"] == vet_id), None)


def nearest(kind: str, lat: float, lon: float) -> dict:
    return min(world()[kind], key=lambda p: distance_km(lat, lon, p["lat"], p["lon"]))


def households_within(lat: float, lon: float, km: float) -> list[dict]:
    return [f for f in world()["farmers"] if distance_km(lat, lon, f["lat"], f["lon"]) <= km]
