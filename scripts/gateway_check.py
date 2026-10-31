"""Calls the deployed gateway: an allowed search, an allowed dose, and a dose its Cedar policy must refuse.

Run: python scripts/gateway_check.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from emerald import gateway  # noqa: E402

URL = (ROOT / "data" / "gateway-url.txt").read_text().strip()


def main() -> int:
    print("tools:", [t["name"] for t in gateway.rpc("tools/list", gateway_url=URL).get("result", {}).get("tools", [])])
    found = gateway.call_tool("search_guidelines", {"query": "skin nodules fever", "disease": "lsd"}, URL)
    print("search:", [(p["disease"], p["section"], p["page"]) for p in found][:2])
    dose = gateway.call_tool("compute_dose", {"disease": "lsd", "drug": "meloxicam", "weight_kg": 320}, URL)
    print("dose:", dose["total_dose"], dose["route"])
    try:
        print("NOT REFUSED:", gateway.call_tool("compute_dose", {"disease": "lsd", "drug": "meloxicam", "weight_kg": 5000}, URL))
        return 1
    except gateway.GatewayDenied as refused:
        print("Cedar refused a 5000 kg dose request:", str(refused)[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
