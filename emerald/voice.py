"""The phone line: a Strands BidiAgent on Amazon Nova Sonic, speaking Hindi.

The voice agent's job is narrow. It listens, records the case with one tool, and repeats what code tells
it to say. Everything clinical happens after the call, behind the proof loop and the vet's signature.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Callable

import boto3
from strands import tool
from strands.bidi import BidiAgent
from strands.bidi.models import BedrockNovaSonicModel

from . import pipeline, triage

VOICE_MODEL = os.environ.get("EMERALD_VOICE_MODEL", "amazon.nova-2-sonic-v1:0")
# Nova Sonic's polyglot voices can speak Hindi. 8 kHz is telephone audio; browser audio uses 16 kHz.
VOICE = os.environ.get("EMERALD_VOICE", "tiffany")

PROMPT = f"""You answer a free helpline for smallholder cattle and buffalo farmers in India. Speak Hindi unless the caller speaks English.
Use short, simple sentences. Ask one question at a time. Be calm and kind.

Find out, in at most four questions: what is wrong with the animal, since when, cow or buffalo, its rough weight if they know it,
and whether any person was bitten or touched a dead animal.

As soon as you know enough, call record_case. Choose signs only from this list:
{", ".join(sorted(triage.SIGNS))}

Then say the "say" text from the result in Hindi, without adding to it, and end politely.

Never name a medicine or a dose, even if the caller begs. Say that only the vet can approve medicine, and that the vet is being called.
Never say for certain what disease the animal has."""

DEFAULT_ADVICE = "We have recorded this and are calling the vet now. Keep this animal away from your other animals until the vet has decided what to do."


def english_gloss(text: str) -> str | None:
    """A running English line under the Hindi, for vets and reviewers who don't read it. Empty if it fails or isn't needed."""
    if not re.search(r"[\u0900-\u097F]", text):
        return None
    try:
        reply = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1")).converse(
            modelId=os.environ.get("EMERALD_REASONER", "us.amazon.nova-2-lite-v1:0"),
            system=[{"text": "Translate the Hindi into plain, natural English. Reply with only the translation."}],
            messages=[{"role": "user", "content": [{"text": text}]}], inferenceConfig={"maxTokens": 300, "temperature": 0.0})
        return "".join(block.get("text", "") for block in reply["output"]["message"]["content"]).strip() or None
    except Exception:  # a missing gloss must never disturb the call
        return None


def spoken_advice(case: dict) -> str:
    """Written by code, so what the farmer is told first can't be improvised."""
    parts = [flag["instruction"] for flag in case["red_flags"]]
    return " ".join(parts + [DEFAULT_ADVICE])


class PhoneCall:
    """One farmer's call. When the case is recorded, the rest of the work starts in the background."""

    def __init__(self, farmer_id: str, on_case: Callable[[dict], None] | None = None, sample_rate: int = 16000,
                 on_done: Callable[[dict], None] | None = None) -> None:
        self.farmer_id = farmer_id
        self.on_case = on_case
        self.on_done = on_done
        self.case: dict | None = None
        self.outcome: pipeline.Outcome | None = None
        self.worker: threading.Thread | None = None
        self.agent = BidiAgent(
            model=BedrockNovaSonicModel(
                model_id=VOICE_MODEL, region=os.environ.get("AWS_REGION", "us-east-1"), voice=VOICE,
                audio={"input": {"sample_rate": sample_rate}, "output": {"sample_rate": sample_rate}},
            ),
            tools=[self._record_case_tool()],
            system_prompt=PROMPT,
        )

    def _record_case_tool(self):
        call = self

        @tool
        def record_case(signs: list[str], species: str = "cattle", weight_kg: float = 0, people_exposed: bool = False) -> dict:
            """Record the farmer's case. Call this once, as soon as you know the signs."""
            if call.case is not None:
                return {"case_id": call.case["case_id"], "say": spoken_advice(call.case)}
            if people_exposed and "bitten_by_animal" not in signs:
                signs = [*signs, "bitten_by_animal"]
            call.case = pipeline.open_case(call.farmer_id, signs, weight_kg or None, species)
            if call.on_case:
                call.on_case(call.case)
            call.worker = threading.Thread(target=call._process, daemon=True)
            call.worker.start()
            return {"case_id": call.case["case_id"], "say": spoken_advice(call.case)}

        return record_case

    def _process(self) -> None:
        try:
            self.outcome = pipeline.process_case(self.case)
        finally:
            if self.on_done:
                self.on_done(self.case)
