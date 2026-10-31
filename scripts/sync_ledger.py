"""Run when a field kit is back online. Uploads its signed record and runs deferred second opinions.

Run: python scripts/sync_ledger.py --data data/story-offline
Needs EMERALD_LEDGER_BUCKET, set to an S3 bucket with Object Lock enabled.
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", help="the field kit's data folder")
    args = parser.parse_args()
    if args.data:
        os.environ["EMERALD_DATA"] = args.data
    os.environ["EMERALD_LANE"] = "cloud"

    from emerald import ledger, sync

    check = ledger.verify()
    print(f"local chain: {check}")
    if not check["ok"]:
        print("Not uploading a broken record.")
        return 1
    print(f"uploaded: {sync.push()}")
    for item in sync.run_second_opinions():
        print(f"second opinion on {item['case_id']}: {item['reviewed']} claims reviewed, {len(item['failed'])} failed")
        for bad in item["failed"]:
            print(f"  told the vet: {bad['claim']} ({bad['reason']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
