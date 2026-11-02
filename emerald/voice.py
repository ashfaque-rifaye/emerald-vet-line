"""The phone line: a Strands BidiAgent on Amazon Nova Sonic, speaking English.

The voice agent's job is narrow. It listens, records the case with one tool, and repeats what code tells
it to say. Everything clinical happens after the call, behind the proof loop and the vet's signature.
"""

from __future__ import annotations

import os
import threading
from typing import Callable

from strands import tool
from strands.bidi import BidiAgent
from strands.bidi.models import BedrockNovaSonicModel

from . import pipeline, triage

VOICE_MODEL = os.environ.get("EMERALD_VOICE_MODEL", "amazon.nova-2-sonic-v1:0")
# An Indian English voice. 8 kHz is telephone audio; browser audio uses 16 kHz.
VOICE = os.environ.get("EMERALD_VOICE", "kiara")

PROMPT = f"""You answer a free helpline for smallholder cattle and buffalo farmers in India. The caller is speaking Indian English, and you always hear and answer them in English, never in another language.
Use short sentences, the way a kind person talks on the phone. Never read out a list. Each reply asks exactly one question, then stops and waits.
Your first words on every call are: "Emerald vet line. Tell me what's happening with your animal."

Then ask only what the caller hasn't already told you, one reply at a time, in this order: cow or buffalo, its rough weight,
and last, whether any person was bitten or touched a dead animal. Don't call record_case until you've had the answer to that last question.

As soon as you know enough, call record_case. Choose signs only from this list:
{", ".join(sorted(triage.SIGNS))}

Then say the "say" text from the result, without adding to it, and end politely.

Never name a medicine or a dose, even if the caller begs. Say that only the vet can approve medicine, and that the vet is being called.
Never say for certain what disease the animal has."""

DEFAULT_ADVICE = "We have recorded this and are calling the vet now. Keep this animal away from your other animals until the vet has decided what to do."


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
