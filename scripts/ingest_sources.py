"""Turn the official PDFs into a citable passage store: sources/passages.jsonl.

Only field-relevant subsections are kept (signs, differential, treatment, prevention, public health).
Laboratory methods, sample handling and pathogen culture are deliberately left out: Emerald's job
ends at "call the vet", so it has no use for them.

Run: python scripts/ingest_sources.py  (needs the PDFs in sources/raw, see sources/README.md)
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "sources" / "raw"
OUT = ROOT / "sources" / "passages.jsonl"

SVTG_TITLE = "Standard Veterinary Treatment Guidelines for Livestock and Poultry (DAHD, 2024)"
FAO_TITLE = "Lumpy skin disease: A field manual for veterinarians (FAO, 2017)"
ACT_TITLE = "Prevention and Control of Infectious and Contagious Diseases in Animals Act, 2009"

# SVTG chapter 2 (cattle and buffalo). Headings are matched in the body text, not the contents page.
SVTG_DISEASES = {
    "fmd": ("2.4", "2.5"),
    "lsd": ("2.5", "2.6"),
    "rabies": ("2.16", "2.17"),
    "hs": ("2.17", "2.18"),
    "anthrax": ("2.21", "2.22"),
    "bq": ("2.27", "2.28"),
    "mastitis": ("2.33", "2.34"),
}
SVTG_CHAPTER_PAGES = (92, 131)  # 0-indexed page range holding chapter 2

KEEP = {"clinical signs", "differential diagnosis", "treatment", "prevention and control", "biosecurity measures",
        "public health significance", "public health risk", "zoonotic", "zoonotic importance", "general management"}
DROP = {"etiology", "aetiology", "epidemiology", "transmission", "lesions", "diagnosis", "pathogenesis", "introduction",
        "host range", "pathology", "sample collection for diagnosis"}
HEADINGS = sorted(KEEP | DROP, key=len, reverse=True)
HEADING_RE = re.compile(r"^\s*(" + "|".join(re.escape(h) for h in HEADINGS) + r")\s*:?\s*$", re.I | re.M)
RUNNING_HEAD = re.compile(r"^\s*\d*\s*STANDARD VETERINARY TREATMENT GUIDELINES FOR LIVESTOCK AND POULTRY\s*$", re.M)


def clean(text: str) -> str:
    text = text.replace("\xa0", " ").replace("ﬁ", "fi").replace("ﬂ", "fl")
    return re.sub(r"[ \t]+", " ", text)


def flow(text: str) -> str:
    """Join hard-wrapped PDF lines into one line."""
    text = re.sub(r"-\n(?=[a-z])", "", text)
    return re.sub(r"\s*\n\s*", " ", text).strip()


def make(doc: str, title: str, disease: str, section: str, page: int, text: str) -> dict:
    body = flow(text)
    pid = hashlib.sha256(f"{doc}|{page}|{section}|{body}".encode()).hexdigest()[:12]
    return {"id": pid, "doc": doc, "title": title, "disease": disease, "section": section, "page": page, "text": body,
            "sha256": hashlib.sha256(body.encode()).hexdigest()}


def svtg_passages() -> list[dict]:
    reader = PdfReader(str(RAW / "svtg" / "svtg-2024.pdf"))
    first, last = SVTG_CHAPTER_PAGES
    pages = [(i + 1, RUNNING_HEAD.sub("", clean(reader.pages[i].extract_text() or ""))) for i in range(first, last)]
    out: list[dict] = []
    for disease, (start, stop) in SVTG_DISEASES.items():
        collecting, section = False, None
        for page_no, text in pages:
            # Numbered headings are reliable ("2.5 Lumpy Skin Disease (LSD)"); plain names also occur in body text.
            start_m = re.search(rf"^\s*{re.escape(start)}\s+[A-Z][^\n]*$", text, re.M)
            if not collecting:
                if not start_m:
                    continue
                collecting, text = True, text[start_m.end():]
            stop_m = re.search(rf"^\s*{re.escape(stop)}\s+[A-Z][^\n]*$", text, re.M)
            done = bool(stop_m)
            if stop_m:
                text = text[: stop_m.start()]
            pos, parts = 0, []
            for m in HEADING_RE.finditer(text):
                parts.append((section, text[pos: m.start()]))
                section, pos = m.group(1).lower(), m.end()
            parts.append((section, text[pos:]))
            for sec, chunk in parts:
                if sec in KEEP and len(flow(chunk)) > 30:
                    out.append(make("svtg", SVTG_TITLE, disease, sec, page_no, chunk))
            if done:
                break
    return out


def act_passages() -> list[dict]:
    reader = PdfReader(str(RAW / "act2009" / "act-2009.pdf"))
    out = []
    for i, page in enumerate(reader.pages):
        text = re.sub(r"@[^!\n]*!\s*", "", clean(page.extract_text() or ""))
        m = re.search(r"\n\s*4\. Reporting scheduled diseases.*?(?=\n\s*6\. )", text, re.S)
        if m:
            out.append(make("act2009", ACT_TITLE, "law", "sections 4-5", i + 1, m.group(0)))
        m = re.search(r"THE SCHEDULE.*", text, re.S)
        if m:
            out.append(make("act2009", ACT_TITLE, "law", "schedule", i + 1, m.group(0)))
    return out


def fao_passages() -> list[dict]:
    reader = PdfReader(str(RAW / "fao-lsd" / "fao-lsd-manual.pdf"))
    out = []
    for i, page in enumerate(reader.pages):
        text = clean(page.extract_text() or "")
        low = text.lower()
        if len(text) < 300 or "contents" in low[:200]:
            continue
        # Field recognition and control only; skip the laboratory chapters.
        if any(k in low for k in ("clinical signs", "vaccination", "movement", "vector", "differential")) and not any(
            k in low for k in ("pcr", "elisa", "laboratory", "sampling")
        ):
            out.append(make("fao-lsd", FAO_TITLE, "lsd", "field manual", i + 1, text))
    return out


def main() -> None:
    passages = svtg_passages() + fao_passages() + act_passages()
    OUT.write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in passages) + "\n", encoding="utf-8")
    counts: dict[tuple[str, str], int] = {}
    for p in passages:
        counts[(p["doc"], p["disease"])] = counts.get((p["doc"], p["disease"]), 0) + 1
    for key, n in sorted(counts.items()):
        print(key, n)
    print("total", len(passages))


if __name__ == "__main__":
    main()
