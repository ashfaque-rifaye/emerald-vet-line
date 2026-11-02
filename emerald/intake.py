"""Turns what a farmer said into the fixed list of signs the triage rules understand."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field
from strands import Agent

from . import models, triage

PROMPT = f"""You take notes for a veterinary phone line. The farmer speaks everyday Indian English.
Pick signs ONLY from this list, and only ones the farmer actually described:
{", ".join(sorted(triage.SIGNS))}

Examples of how farmers say things: "lumps" or "boils" on the skin means skin_nodules; "body is hot" means fever;
"giving less milk" means reduced_milk; "sores in the mouth" means mouth_blisters; "saliva dripping" means drooling;
"dropped dead" means sudden_death; "blood" from the nose or mouth means bleeding_from_body_openings;
"udder is swollen" means swollen_udder; "a dog bit her" means bitten_by_animal.

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
