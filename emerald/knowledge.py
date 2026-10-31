"""Search over the official passages, plus the check that a quoted sentence is really in its source."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache

from . import config

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"the", "and", "of", "to", "in", "a", "is", "for", "with", "or", "on", "be", "are", "as", "by", "at", "may"}


def _tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@lru_cache(maxsize=1)
def passages() -> tuple[dict, ...]:
    with open(config.PASSAGES, encoding="utf-8") as fh:
        return tuple(json.loads(line) for line in fh if line.strip())


def get(passage_id: str) -> dict | None:
    return next((p for p in passages() if p["id"] == passage_id), None)


def search(query: str, disease: str | None = None, k: int = 5) -> list[dict]:
    """BM25. Plain code with no embeddings service, so it behaves the same with or without a network."""
    pool = [p for p in passages() if not disease or p["disease"] in (disease, "law")]
    docs = [_tokens(f'{p["disease"]} {p["section"]} {p["text"]}') for p in pool]
    if not docs:
        return []
    avg = sum(map(len, docs)) / len(docs)
    freq = Counter(t for doc in docs for t in set(doc))
    scored = []
    for passage, doc in zip(pool, docs):
        counts, score = Counter(doc), 0.0
        for term in set(_tokens(query)):
            if term in counts:
                idf = math.log(1 + (len(docs) - freq[term] + 0.5) / (freq[term] + 0.5))
                tf = counts[term]
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * len(doc) / avg))
        if score > 0:
            scored.append((score, passage))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [p for _, p in scored[:k]]


def normalise(text: str) -> str:
    """Lower-case and strip everything but letters and digits, so PDF line breaks and spacing don't matter."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def quote_in_passage(passage_id: str, quote: str) -> bool:
    passage = get(passage_id)
    return bool(passage) and len(normalise(quote)) >= 15 and normalise(quote) in normalise(passage["text"])


def citation(passage_id: str) -> str:
    passage = get(passage_id)
    if not passage:
        return "unknown source"
    return f'{passage["title"]}, PDF page {passage["page"]}, {passage["section"]}'
