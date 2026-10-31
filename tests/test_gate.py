"""The pause, the vet's decision and the resume, using a scripted model so no network is needed."""

import json
from typing import Any, AsyncGenerator

from strands import Agent, tool
from strands.models import Model
from strands.session.file_session_manager import FileSessionManager

from emerald import actions, config, ledger, registry, signoff, surveillance
from emerald.gate import SignoffGate


class ScriptedModel(Model):
    """Plays back a fixed list of turns: a dict is a tool call, a string is a final answer."""

    def __init__(self, turns: list) -> None:
        self.turns = list(turns)

    def get_config(self) -> dict:
        return {}

    def update_config(self, **kwargs: Any) -> None:
        pass

    async def structured_output(self, *args: Any, **kwargs: Any):
        raise NotImplementedError

    async def stream(self, *args: Any, **kwargs: Any) -> AsyncGenerator[dict, None]:
        turn = self.turns.pop(0) if self.turns else "done"
        yield {"messageStart": {"role": "assistant"}}
        if isinstance(turn, dict):
            yield {"contentBlockStart": {"start": {"toolUse": {"name": turn["name"], "toolUseId": turn.get("id", "t1")}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(turn["input"])}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockDelta": {"delta": {"text": turn}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}


@tool
def pay_vet_consult(case_id: str, vet_id: str, amount_inr: float, signoff_id: str = "") -> dict:
    """Pay a vet."""
    return actions.pay_vet_consult(case_id, vet_id, amount_inr, signoff_id)


@tool
def start_ring_calls(case_id: str, disease: str, signoff_id: str = "") -> dict:
    """Ring calls."""
    return actions.start_ring_calls(case_id, disease, signoff_id)


def agent_for(case_id: str, turns: list) -> Agent:
    return Agent(model=ScriptedModel(turns), tools=[pay_vet_consult], hooks=[SignoffGate(case_id)], callback_handler=None,
                 session_manager=FileSessionManager(session_id=case_id, storage_dir=str(config.data_dir() / "sessions")))


def pay_turn(case_id: str, amount: float = 300, **extra: Any) -> dict:
    return {"name": "pay_vet_consult", "input": {"case_id": case_id, "vet_id": "V01", "amount_inr": amount, **extra}}


def new_case() -> str:
    return surveillance.record_case("F001", ["skin_nodules", "fever"], weight_kg=300)["case_id"]


def payments() -> int:
    return sum(1 for e in ledger.entries() if e["type"] == "vet_paid")


def test_irreversible_tool_pauses_and_nothing_happens_yet():
    case_id = new_case()
    result = agent_for(case_id, [pay_turn(case_id)])("pay the vet")
    assert result.stop_reason == "interrupt" and payments() == 0
    assert signoff.pending()[0]["summary"].startswith("Pay 300")


def test_approval_resumes_and_pays_even_in_a_new_agent_object():
    case_id = new_case()
    first = agent_for(case_id, [pay_turn(case_id)])("pay the vet")
    interrupt = first.interrupts[0]
    signoff.decide(interrupt.reason["signoff_id"], "V01", registry.DEMO_VET_PIN, True)
    # A brand new object stands in for a new process: the state has to come back from disk.
    second = agent_for(case_id, ["paid"])([{"interruptResponse": {"interruptId": interrupt.id, "response": "approved"}}])
    assert second.stop_reason == "end_turn" and payments() == 1


def test_decline_means_no_payment():
    case_id = new_case()
    first = agent_for(case_id, [pay_turn(case_id)])("pay the vet")
    interrupt = first.interrupts[0]
    signoff.decide(interrupt.reason["signoff_id"], "V01", registry.DEMO_VET_PIN, False)
    agent_for(case_id, ["ok"])([{"interruptResponse": {"interruptId": interrupt.id, "response": "declined"}}])
    assert payments() == 0


def test_saying_approved_without_a_vet_signature_is_refused():
    """The hook is told 'approved' but nobody signed: the tool's own check must stop it."""
    case_id = new_case()
    first = agent_for(case_id, [pay_turn(case_id)])("pay the vet")
    interrupt = first.interrupts[0]
    agent_for(case_id, ["ok"])([{"interruptResponse": {"interruptId": interrupt.id, "response": "approved"}}])
    assert payments() == 0
    assert any(e["type"] == "action_refused" for e in ledger.entries(case_id))


def test_model_supplying_its_own_signoff_id_gains_nothing():
    case_id = new_case()
    result = agent_for(case_id, [pay_turn(case_id, signoff_id="SO-forged")])("pay the vet")
    assert result.stop_reason == "interrupt" and payments() == 0


def test_repeating_a_done_action_neither_pays_nor_asks_the_vet_again():
    case_id = new_case()
    first = agent_for(case_id, [pay_turn(case_id)])("pay the vet")
    interrupt = first.interrupts[0]
    signoff.decide(interrupt.reason["signoff_id"], "V01", registry.DEMO_VET_PIN, True)
    second = agent_for(case_id, [pay_turn(case_id, signoff_id="x"), "done"])(
        [{"interruptResponse": {"interruptId": interrupt.id, "response": "approved"}}])
    assert second.stop_reason == "end_turn" and payments() == 1 and not signoff.pending()


def test_outbreak_tool_without_a_cluster_does_not_reach_the_vet():
    case_id = new_case()
    turn = {"name": "start_ring_calls", "input": {"case_id": case_id, "disease": "lsd"}}
    result = Agent(model=ScriptedModel([turn, "ok"]), tools=[start_ring_calls], hooks=[SignoffGate(case_id)], callback_handler=None)("ring")
    assert result.stop_reason == "end_turn" and not signoff.pending()


def test_agent_cannot_act_on_another_case():
    case_id, other = new_case(), surveillance.record_case("F002", ["skin_nodules"])["case_id"]
    agent_for(case_id, [pay_turn(other), "ok"])("pay the vet")
    assert payments() == 0 and not signoff.pending()
