"""Turns what a farmer said into the fixed list of signs the triage rules understand."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field
from strands import Agent

from . import models, triage

PROMPT = f"""You take notes for a veterinary phone line. The farmer may speak Hindi, Hinglish or English.
Pick signs ONLY from this list, and only ones the farmer actually described:
{", ".join(sorted(triage.SIGNS))}

Examples of how farmers say things: "gaanth" or "daane" on the skin means skin_nodules; "bukhar" means fever;
"doodh kam" means reduced_milk; "munh mein chhale" means mouth_blisters; "laar" means drooling;
"achanak mar gayi" means sudden_death; "khoon" from the nose or mouth means bleeding_from_body_openings;
"thann mein sujan" means swollen_udder; "kutte ne kaata" means bitten_by_animal.

Reply with only JSON: {{"signs": ["..."], "species": "cattle or buffalo", "weight_kg": number or null, "people_exposed": true or false}}
Use a weight only if the farmer states one. Never guess a weight."""


class Intake(BaseModel):
    signs: list[str] = Field(default_factory=list)
    species: str = "cattle"
    weight_kg: float | None = None
    people_exposed: bool = False


def from_transcript(transcript: str) -> Intake:
    reply = str(Agent(model=models.reasoner(), system_prompt=PROMPT, callback_handler=None)(transcript))
    data = json.loads(reply[reply.find("{"): reply.rfind("}") + 1])
    intake = Intake.model_validate(data)
    # Anything outside the fixed list is dropped here, so a made-up sign can't reach the triage rules.
    intake.signs = [s for s in intake.signs if s in triage.SIGNS]
    return intake
