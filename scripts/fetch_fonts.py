"""Downloads the console's fonts next to the page, so it looks the same with no internet on a field kit.

All four families are under the SIL Open Font License. Run: python scripts/fetch_fonts.py
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
from pathlib import Path

CSS_URL = ("https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..800"
           "&family=Figtree:wght@400..700&family=JetBrains+Mono:wght@400;500&family=Noto+Sans+Devanagari:wght@400..600&display=swap")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
OUT = Path(__file__).resolve().parent.parent / "web" / "fonts"
KEEP = {"latin", "devanagari"}


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as reply:
        return reply.read()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    css = get(CSS_URL).decode()
    blocks = re.findall(r"/\* ([\w-]+) \*/\s*(@font-face \{.*?\})", css, re.S)
    out = []
    for subset, block in blocks:
        family = re.search(r"font-family: '([^']+)'", block).group(1)
        if subset not in KEEP or (subset == "devanagari") != (family == "Noto Sans Devanagari"):
            continue
        url = re.search(r"url\((https://[^)]+\.woff2)\)", block).group(1)
        name = hashlib.sha256(url.encode()).hexdigest()[:16] + ".woff2"
        if not (OUT / name).exists():
            (OUT / name).write_bytes(get(url))
        out.append(block.replace(url, name))
    (OUT / "fonts.css").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{len(out)} font faces in {OUT}")


if __name__ == "__main__":
    main()
