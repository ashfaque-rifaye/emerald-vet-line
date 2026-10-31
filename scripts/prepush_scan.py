"""Run before pushing. Exits 1 and prints only the file and the rule, never the match, if anything staged
looks like a credential, this AWS account's id, a private note, or a stray binary.

Run: python scripts/prepush_scan.py
"""

from __future__ import annotations

import re
import subprocess
import sys

RULES = {
    "aws_access_key_id": re.compile(rb"\b(AKIA|ASIA)[A-Z0-9]{16}\b"),
    # Patterns are split so this file does not match itself.
    "aws_secret_key_field": re.compile(rb"aws_secret" + rb"_access_key\s*[=:]", re.I),
    "private_key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE" + rb" KEY-----"),
    "github_token": re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "twilio_sid": re.compile(rb"\bAC[0-9a-f]{32}\b"),
    "personal_email": re.compile(rb"[\w.+-]+@(gmail|outlook)\.com", re.I),
}
FORBIDDEN_PATHS = (".env", "HACKATHON_BRIEF.md", "data/", "sources/raw/")
BINARY_ALLOWED = (".woff2", ".png")
MAX_BYTES = 2_000_000


def account_id() -> bytes | None:
    try:
        import boto3

        return boto3.client("sts").get_caller_identity()["Account"].encode()
    except Exception:
        return None


def main() -> int:
    files = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=d", "-z"], capture_output=True, check=True).stdout.decode().split("\0")
    account = account_id()
    problems = []
    for name in filter(None, files):
        if name.startswith(FORBIDDEN_PATHS):
            problems.append((name, "path must never be published"))
            continue
        blob = subprocess.run(["git", "show", f":{name}"], capture_output=True, check=True).stdout
        if len(blob) > MAX_BYTES and name != "sources/passages.jsonl":
            problems.append((name, "file is unexpectedly large"))
        if b"\0" in blob[:4096] and not name.endswith(BINARY_ALLOWED):
            problems.append((name, "unexpected binary"))
        if name == "scripts/prepush_scan.py":
            continue
        for rule, pattern in RULES.items():
            if pattern.search(blob):
                problems.append((name, rule))
        if account and account in blob:
            problems.append((name, "aws_account_id"))
    for name, rule in problems:
        print(f"BLOCKED {name}: {rule}")
    print(f"scanned {len([f for f in files if f])} files, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
