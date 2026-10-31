"""The action gate: any irreversible tool call pauses the agent until a vet has decided.

This is the first of two layers. Even if this hook were removed, the tool itself would refuse (see actions.py).
"""

from __future__ import annotations

from typing import Any

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

from . import dosing, signoff, surveillance, triage


OUTBREAK_TOOLS = {"file_outbreak_report", "start_ring_calls"}


def describe(case_id: str, tool: str, args: dict) -> str:
    """What the vet hears. Built by code from the actual arguments, so it can't misdescribe the action."""
    disease = triage.NAMES.get(str(args.get("disease")), str(args.get("disease"))).lower()
    if tool == "prescribe_treatment":
        case = surveillance.get_case(case_id) or {}
        dose = dosing.compute(str(args.get("disease")), str(args.get("drug")), float(case.get("weight_kg") or 0))
        if dose["status"] != "ok":
            return f'Treat suspected {disease} with {args.get("drug")}: {dose["reason"]}.'
        kind = "antibiotic" if dose["antibiotic"] else "not an antibiotic"
        return (f'Treat suspected {disease} with {args.get("drug")} ({kind}): {dose["total_dose"]} {dose["route"]}, duration: {dose["days"]}. '
                f'Milk withdrawal: {dose["milk_withdrawal"]}. Source: "{dose["source_quote"]}".')
    if tool == "pay_vet_consult":
        return f'Pay {args.get("amount_inr")} INR from the village fund to vet {args.get("vet_id")}.'
    if tool == "file_outbreak_report":
        return f"File the legally required report of a suspected {disease} outbreak."
    if tool == "start_ring_calls":
        return f"Phone every registered household around the suspected {disease} outbreak."
    return f"{tool}: {args}"


class SignoffGate(HookProvider):
    def __init__(self, case_id: str) -> None:
        self.case_id = case_id

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.check)

    def check(self, event: BeforeToolCallEvent) -> None:
        tool = event.tool_use["name"]
        if tool not in signoff.IRREVERSIBLE:
            return
        args = dict(event.tool_use["input"] or {})
        args.pop("signoff_id", None)
        if args.get("case_id") != self.case_id:
            event.cancel_tool = f"this agent may only act on case {self.case_id}"
            return
        if tool in OUTBREAK_TOOLS:
            # Don't take up a vet's time with something the detector doesn't support.
            cluster = surveillance.find_cluster(self.case_id)
            if not cluster or cluster["disease"] != args.get("disease"):
                event.cancel_tool = "the cluster detector has not found this outbreak, so this was not sent to the vet"
                return
        req = signoff.request(self.case_id, tool, args, describe(self.case_id, tool, args))
        if req["used_at"]:
            event.cancel_tool = "this has already been done with the vet's signature. Do not repeat it."
            return
        if req["status"] == "declined":
            event.cancel_tool = "the vet declined this action. Do not try again."
            return
        if req["status"] != "approved":
            decision = event.interrupt(f"vet-signoff-{req['id']}", reason={"signoff_id": req["id"], "tool": tool, "summary": req["summary"]})
            if decision != "approved":
                event.cancel_tool = "the vet did not approve this action"
                return
        # Only the id is passed along. The tool itself checks the signature behind it.
        event.tool_use["input"]["signoff_id"] = req["id"]
