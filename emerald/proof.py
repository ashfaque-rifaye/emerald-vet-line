"""The proof rules. A clinical claim is only allowed through if its evidence survives these checks."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from . import knowledge

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_DISEASE_NAMES = {
    "lsd": "lumpy skin disease", "fmd": "foot and mouth disease", "hs": "haemorrhagic septicaemia", "anthrax": "anthrax",
    "bq": "black quarter", "rabies": "rabies", "mastitis": "mastitis",
}


class Claim(BaseModel):
    claim: str = Field(description="One plain sentence the caller or vet will hear")
    passage_id: str = Field(description="id of the source passage")
    quote: str = Field(description="Exact words copied from that passage which support the claim")


class ClaimCheck(BaseModel):
    claim: Claim
    ok: bool
    reason: str
    citation: str = ""


def context_of(passage_id: str) -> str:
    """Where a sentence sits. "Nodules appear on the skin" is about lumpy skin disease only because of its section."""
    passage = knowledge.get(passage_id)
    if passage is None:
        return "unknown section"
    subject = "the 2009 animal diseases Act" if passage["disease"] == "law" else _DISEASE_NAMES.get(passage["disease"], passage["disease"])
    return f'the "{passage["section"]}" section on {subject}'


def check_claim(claim: Claim) -> ClaimCheck:
    """Plain-code checks, run before any model gets an opinion."""
    passage = knowledge.get(claim.passage_id)
    if passage is None:
        return ClaimCheck(claim=claim, ok=False, reason=f"passage {claim.passage_id} does not exist")
    if not knowledge.quote_in_passage(claim.passage_id, claim.quote):
        return ClaimCheck(claim=claim, ok=False, reason="the quote is not in the cited passage")
    # Numbers are where a confident wrong answer does the most harm: each one must appear in the quote itself.
    quote_digits = set(_NUMBER.findall(claim.quote))
    invented = [n for n in _NUMBER.findall(claim.claim) if n not in quote_digits]
    if invented:
        return ClaimCheck(claim=claim, ok=False, reason=f"number(s) {invented} are not in the quote")
    return ClaimCheck(claim=claim, ok=True, reason="quote found in source", citation=knowledge.citation(claim.passage_id))
