"""One call, start to finish: record, triage, prove, act, wait for the vet, carry on.

What a model decides is kept separate from what must always happen. Safety steps and the vet call run
in code, so a weak or wrong model can make Emerald less helpful but cannot make it skip them.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field

from strands import Agent
from strands.session.file_session_manager import FileSessionManager

from . import config, db, gateway, knowledge, ledger, models, proof_graph, registry, signoff, surveillance
from .gate import SignoffGate
from .tools import connected

ACTION_SERVERS = ("telephony", "payments", "dosing", "surveillance", "registry")

ACTION_PROMPT = """You are the action agent of a veterinary phone line for smallholder farmers.
The evidence has been verified. The task lists the tool calls to make. Make each one exactly once, in order, with the arguments given.
For tell_farmer, write the message yourself: plain words, based only on the verified claims, and never a dose or a drug name.
The tools marked IRREVERSIBLE pause until a vet decides. If the vet declines, or a tool says something is already done, do not try again. Never set signoff_id.
When finished, reply with one short sentence saying what was done."""


@dataclass
class Outcome:
    case_id: str
    status: str
    assessment: dict = field(default_factory=dict)
    summary: str = ""
    verified: list[dict] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    cluster: dict | None = None
    pending: list[dict] = field(default_factory=list)
    final_text: str = ""


_case_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _case_lock(case_id: str) -> threading.RLock:
    """One agent run per case at a time. A fast vet can sign before the agent has finished saving its pause,
    so a resume has to wait for that run to end rather than find no pause to resume."""
    with _locks_guard:
        return _case_locks.setdefault(case_id, threading.RLock())


def _run_file(case_id: str):
    path = config.data_dir() / "runs"
    path.mkdir(exist_ok=True)
    return path / f"{case_id}.json"


def _agent(case_id: str, tools: list) -> Agent:
    # File-backed session: the pause survives a restart or a dropped network while the vet is being reached.
    sessions = config.data_dir() / "sessions"
    return Agent(
        model=models.reasoner(), system_prompt=ACTION_PROMPT, tools=tools, hooks=[SignoffGate(case_id)], callback_handler=None,
        session_manager=FileSessionManager(session_id=case_id, storage_dir=str(sessions)), name="actor",
    )


def _save_pause(case_id: str, interrupts: list, context: dict) -> list[dict]:
    pending = [{"interrupt_id": i.id, **i.reason} for i in interrupts]
    _run_file(case_id).write_text(json.dumps({"pending": pending, "context": context}, indent=1), encoding="utf-8")
    return pending


def _guarantee_safety(case: dict) -> None:
    """Runs before any model acts. Red flags reach the farmer and the doctor, whatever happens next."""
    from . import actions

    for flag in case["red_flags"]:
        actions.tell_farmer(case["case_id"], flag["instruction"])
        if flag["pull_in_doctor"]:
            actions.call_doctor(case["case_id"], f'{flag["code"]}: people may be exposed. Signs: {", ".join(case["reported_signs"])}.')


def _gather_evidence(case: dict, cluster: dict | None, semantic: bool) -> proof_graph.ProofRun:
    """Retrieval goes through the knowledge MCP server, the same way in both lanes."""
    wanted: list[tuple[str, str | None, int]] = []
    for candidate in case["candidates"][:2]:
        wanted.append((" ".join(candidate["matched_signs"]) + " treatment isolation prevention", candidate["disease"], 3))
    for flag in case["red_flags"]:
        wanted.append((flag["passage_query"], None, 2))
    if cluster or any(c["notifiable"] for c in case["candidates"]):
        wanted.append(("reporting scheduled diseases obligatory segregate", "law", 1))
    found = _retrieve(case["case_id"], wanted)
    graph, run, listing = proof_graph.build(case["case_id"], list(found.values()), semantic)
    graph_result = graph(f'Case: {case["species"]}, signs reported: {", ".join(case["reported_signs"]) or "none clear"}.\n'
          f'Possible causes from the triage rules: {", ".join(c["name"] for c in case["candidates"]) or "none matched"}.\n\n'
          f"Numbered source sentences:\n{listing}")
    run.usage["reasoner_in"] += graph_result.accumulated_usage.get("inputTokens", 0)
    run.usage["reasoner_out"] += graph_result.accumulated_usage.get("outputTokens", 0)
    return run


def _retrieve(case_id: str, wanted: list[tuple[str, str | None, int]]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    if config.lane() == "cloud" and gateway.url():
        try:
            for query, disease, k in wanted:
                for hit in gateway.call_tool("search_guidelines", {"query": query, "disease": disease or ""})[:k]:
                    found.setdefault(hit["passage_id"], knowledge.get(hit["passage_id"]))
            ledger.append("retrieved_via_gateway", {"passages": len(found)}, case_id)
            return found
        except (OSError, gateway.GatewayDenied, ValueError) as exc:
            ledger.append("gateway_unavailable", {"error": type(exc).__name__}, case_id)
    with connected("knowledge") as tools:
        search = next(t for t in tools if t.tool_name == "search_guidelines")
        for query, disease, k in wanted:
            result = search.mcp_client.call_tool_sync(tool_use_id=f"retrieve-{len(found)}", name="search_guidelines",
                                                      arguments={"query": query, "disease": disease or ""})
            for hit in result.get("structuredContent", {}).get("result", [])[:k]:
                found.setdefault(hit["passage_id"], knowledge.get(hit["passage_id"]))
    return found


def _action_task(case: dict, run: proof_graph.ProofRun, cluster: dict | None) -> str:
    """Code decides which steps apply. The model carries them out and writes the words the farmer hears."""
    case_id = case["case_id"]
    vet = registry.nearest("vets", case["farmer"]["lat"], case["farmer"]["lon"])
    lines = [f"Case id: {case_id}. Summary: {run.summary}", "Verified claims:", *[f"- {c.claim.claim}" for c in run.verified], "", "Tool calls to make:",
             f"1. tell_farmer with case_id {case_id} and your message."]
    drug = _drug_option(case)
    if drug:
        lines.append(f'{len(lines) - 4}. prescribe_treatment with case_id {case_id}, disease "{drug[0]}", drug "{drug[1]}".')
    lines.append(f'{len(lines) - 4}. pay_vet_consult with case_id {case_id}, vet_id "{vet["id"]}", amount_inr {vet["fee_inr"]}.')
    for tool in _missing_outbreak_actions(case_id, cluster):
        lines.append(f'{len(lines) - 4}. {tool} with case_id {case_id}, disease "{cluster["disease"]}".')
    return "\n".join(lines)


def _allowed_tools(case: dict, tools: list, cluster: dict | None) -> list:
    """An agent only holds the tools its steps need. The attack evaluation runs against the full set."""
    allowed = {"tell_farmer", "pay_vet_consult"}
    if _drug_option(case):
        allowed.add("prescribe_treatment")
    if cluster:
        allowed |= {"file_outbreak_report", "start_ring_calls"}
    return [t for t in tools if t.tool_name in allowed]


def _drug_option(case: dict) -> tuple[str, str] | None:
    from .dosing import TABLE

    if not case.get("weight_kg"):
        return None
    for candidate in case["candidates"]:
        # Only non-antibiotic options are suggested up front. An antibiotic is the vet's call, not a default.
        for row in TABLE:
            if row.disease == candidate["disease"] and not row.antibiotic:
                return row.disease, row.drug
    return None


def _missing_outbreak_actions(case_id: str, cluster: dict | None) -> list[str]:
    """What the detector requires that hasn't happened. A vet's decline counts as decided."""
    if not cluster:
        return []
    done = surveillance.outbreak_actions_done(cluster["disease"])
    with db.connect() as conn:
        declined = {r["tool"] for r in conn.execute("SELECT tool FROM signoffs WHERE case_id=? AND status='declined'", (case_id,))}
    return [tool for tool in ("file_outbreak_report", "start_ring_calls") if tool not in done and tool not in declined]


def _drive(case_id: str, agent: Agent, prompt) -> object:
    """Run the agent, then send it back if it stopped short of a required step. A model can't drop a step."""
    result = agent(prompt)
    for _ in range(2):
        if result.stop_reason == "interrupt":
            return result
        cluster = surveillance.find_cluster(case_id)
        missing = _missing_outbreak_actions(case_id, cluster)
        if not missing:
            return result
        ledger.append("agent_sent_back", {"missing": missing}, case_id)
        result = agent(f'Case id: {case_id}. You have not finished. Call these tools now for disease "{cluster["disease"]}": {", ".join(missing)}.')
    return result


def _ensure_vet_called(case_id: str, summary: str) -> None:
    from . import actions

    if not any(e["type"] == "vet_called" for e in ledger.entries(case_id)):
        actions.call_vet(case_id, summary or "New case. Please review the recorded signs.")


def _record_usage(case_id: str, result, extra: dict | None = None) -> None:
    used = result.metrics.accumulated_usage
    usage = dict(extra or {})
    usage["reasoner_in"] = usage.get("reasoner_in", 0) + used.get("inputTokens", 0)
    usage["reasoner_out"] = usage.get("reasoner_out", 0) + used.get("outputTokens", 0)
    ledger.append("model_usage", usage, case_id)


DEFAULT_FARMER_MESSAGE = "We have recorded this and are calling the vet now. Keep this animal away from your other animals until the vet has decided what to do."


def _ensure_farmer_told(case_id: str) -> None:
    """If the model never produced an acceptable message, the farmer still hears safe words, written by code."""
    from . import actions

    if not any(e["type"] == "farmer_told" for e in ledger.entries(case_id)):
        actions.tell_farmer(case_id, DEFAULT_FARMER_MESSAGE)


def _finish(outcome: Outcome, result) -> Outcome:
    if result.stop_reason == "interrupt":
        outcome.status = "waiting_for_vet"
        return outcome
    _ensure_farmer_told(outcome.case_id)
    outcome.status = "done"
    outcome.final_text = str(result).strip()
    ledger.append("case_run_finished", {"text": outcome.final_text[:500]}, outcome.case_id)
    return outcome


def open_case(farmer_id: str, signs: list[str], weight_kg: float | None = None, species: str = "cattle",
              reported_at: str | None = None) -> dict:
    """The fast part, done while the farmer is still on the line: record the case and act on any red flag."""
    case = surveillance.record_case(farmer_id, signs, species, weight_kg, reported_at)
    _guarantee_safety(case)
    return case


def handle_case(farmer_id: str, signs: list[str], weight_kg: float | None = None, species: str = "cattle",
                semantic: bool = True, reported_at: str | None = None) -> Outcome:
    return process_case(open_case(farmer_id, signs, weight_kg, species, reported_at), semantic)


def process_case(case: dict, semantic: bool = True) -> Outcome:
    """The slower part, which carries on after the call ends: prove, act, and pause for the vet."""
    case_id = case["case_id"]
    cluster = surveillance.find_cluster(case_id)
    try:
        run = _gather_evidence(case, cluster, semantic)
    except Exception as exc:
        # A model or connection failure must never stop the vet being called. It only means no evidence comes with the call.
        ledger.append("evidence_unavailable", {"error": type(exc).__name__}, case_id)
        run = proof_graph.ProofRun(case_id, {})
    _ensure_vet_called(case_id, run.summary)
    outcome = Outcome(case_id, "running", assessment={k: case[k] for k in ("candidates", "red_flags", "reported_signs")},
                      summary=run.summary, cluster=cluster, rejected=run.rejected,
                      verified=[{"claim": c.claim.claim, "quote": c.claim.quote, "citation": c.citation} for c in run.verified])
    if not run.verified:
        # Nothing could be proven, so the agent gets nothing to act on. The vet has already been called.
        ledger.append("no_verified_evidence", {"rejected": len(run.rejected)}, case_id)
        _ensure_farmer_told(case_id)
        outcome.status = "done"
        outcome.final_text = "No claim could be verified, so only the vet was called."
        return outcome
    try:
        with _case_lock(case_id), connected(*ACTION_SERVERS) as tools:
            result = _drive(case_id, _agent(case_id, _allowed_tools(case, tools, cluster)), _action_task(case, run, cluster))
            _record_usage(case_id, result, run.usage)
            outcome.pending = _save_pause(case_id, result.interrupts or [], {}) if result.stop_reason == "interrupt" else _save_pause(case_id, [], {})
    except Exception as exc:
        # The vet already has the case and the evidence. Nothing irreversible can have run unsigned, so stop here safely.
        ledger.append("action_agent_failed", {"error": type(exc).__name__}, case_id)
        _ensure_farmer_told(case_id)
        outcome.status = "done"
        outcome.final_text = "The action agent could not finish, so the case rests with the vet."
        return outcome
    return _finish(outcome, result)


def resume(case_id: str) -> Outcome:
    """Carry on after vets have decided. Works from a new process: state comes from disk."""
    with _case_lock(case_id):
        file = _run_file(case_id)
        saved = json.loads(file.read_text(encoding="utf-8")) if file.exists() else {"pending": []}
        if not saved["pending"]:
            return Outcome(case_id, "done")  # another resume already finished this, so there's nothing to do
        responses, still_waiting = [], []
        for item in saved["pending"]:
            status = signoff.get(item["signoff_id"])["status"]
            if status == "pending":
                still_waiting.append(item)
            else:
                responses.append({"interruptResponse": {"interruptId": item["interrupt_id"], "response": status}})
        outcome = Outcome(case_id, "waiting_for_vet", pending=still_waiting)
        if still_waiting:
            return outcome
        with connected(*ACTION_SERVERS) as tools:
            case = surveillance.get_case(case_id)
            case["farmer"] = registry.farmer(case["farmer_id"])
            result = _drive(case_id, _agent(case_id, _allowed_tools(case, tools, surveillance.find_cluster(case_id))), responses)
            _record_usage(case_id, result)
        outcome.pending = _save_pause(case_id, result.interrupts or [], {})
        return _finish(outcome, result)
