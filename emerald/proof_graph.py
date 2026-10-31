"""The evidence loop, as a Strands Graph: evidence -> verifier, and back again if any claim fails.

Source passages are split into numbered sentences. The model cites a sentence number and code fills in
the exact words, so a misquote can't happen even with a small local model. Whether the sentence really
supports the claim is a separate question, checked by plain rules and then by a second model.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel
from strands import Agent
from strands.agent.agent_result import AgentResult
from strands.multiagent import GraphBuilder
from strands.multiagent.base import MultiAgentBase, MultiAgentResult, NodeResult, Status
from strands.telemetry.metrics import EventLoopMetrics

from . import config, ledger, models, proof

MAX_ATTEMPTS = 3

EVIDENCE_PROMPT = """You are the evidence clerk for a veterinary phone line in rural India.
Write what a vet needs to know about this case, using ONLY the numbered source sentences you are given.

Rules:
- Each claim is one plain sentence, and cites the one source sentence that supports it, like "S4".
- The claim must not say more than its source sentence says. Do not combine facts from different sentences.
- Never state a dose or a drug amount. Doses come from a separate calculator.
- Say what the signs could mean, never that the animal definitely has a disease.
- Cover what the farmer should do now, and whether the disease must be reported if a source says so.
- Write 3 to 6 claims. Avoid years and section numbers.
- If you are given a list of failed claims, fix or drop them, and do not repeat them.

Reply with only this JSON and nothing else:
{"summary": "two sentences for the vet", "claims": [{"claim": "...", "source": "S4"}]}"""

CHECKER_PROMPT = """You check a veterinary evidence brief. For each numbered claim, decide if the quote really supports the claim.
Each quote comes with where it sits in the source. A quote may rely on that context for what it is about.
A claim fails if it says more than the quote does, is more certain than the quote, or gives a different meaning.
A claim that signs "may" or "could" point to a disease is supported when the quote lists those signs for that disease.
Reply with only JSON: {"failed": [{"index": 0, "reason": "short reason"}]}. Use an empty list if all claims are supported."""

_SENTENCE_END = re.compile(r"(?<=[.;])\s+(?=[A-Z])|\s*•\s*|\s+(?=\(\d\)\s)")


class ClaimDraft(BaseModel):
    claim: str
    source: str = ""


class Draft(BaseModel):
    summary: str = ""
    claims: list[ClaimDraft]


def parse_draft(text: str) -> Draft:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the reply")
    return Draft.model_validate_json(text[start: end + 1])


def index_sentences(passages: list[dict]) -> tuple[dict[str, tuple[str, str]], str]:
    """Number every sentence. Returns the lookup and the listing shown to the model."""
    index: dict[str, tuple[str, str]] = {}
    lines: list[str] = []
    for passage in passages:
        lines.append(f'\n{passage["disease"]}, {passage["section"]}:')
        for sentence in _SENTENCE_END.split(passage["text"]):
            sentence = sentence.strip()
            if len(sentence) >= 20:
                sid = f"S{len(index) + 1}"
                index[sid] = (passage["id"], sentence)
                lines.append(f"{sid}: {sentence}")
    return index, "\n".join(lines)


class ProofRun:
    """What the loop has established so far. The graph's edges read this."""

    def __init__(self, case_id: str, sentences: dict[str, tuple[str, str]]) -> None:
        self.case_id = case_id
        self.sentences = sentences
        self.attempts = 0
        self.verified: list[proof.ClaimCheck] = []
        self.rejected: list[dict] = []
        self.summary = ""
        self.retry = False
        self.usage = {"reasoner_in": 0, "reasoner_out": 0, "checker_in": 0, "checker_out": 0}


class Verifier(MultiAgentBase):
    """A graph node that is mostly plain code, with an independent model as a second opinion."""

    def __init__(self, run: ProofRun, semantic: bool = True) -> None:
        super().__init__()
        self.id = "verifier"
        self.run = run
        self.semantic = semantic

    def _semantic_failures(self, passed: list[proof.ClaimCheck]) -> dict[int, str]:
        if not passed:
            return {}
        if not self.semantic:
            # On the field kit the same small model would be marking its own work, so this waits for sync.
            ledger.append("second_opinion_deferred", {"claims": len(passed)}, self.run.case_id)
            return {}
        listing = "\n".join(f'{i}. Claim: {c.claim.claim}\n   Quote, from {proof.context_of(c.claim.passage_id)}: {c.claim.quote}'
                             for i, c in enumerate(passed))
        try:
            result = Agent(model=models.checker(), system_prompt=CHECKER_PROMPT, callback_handler=None)(listing)
            used = result.metrics.accumulated_usage
            self.run.usage["checker_in"] += used.get("inputTokens", 0)
            self.run.usage["checker_out"] += used.get("outputTokens", 0)
            reply = str(result)
            found = json.loads(reply[reply.find("{"): reply.rfind("}") + 1])
            return {int(f["index"]): str(f.get("reason", "not supported")) for f in found.get("failed", [])}
        except Exception as exc:  # Recorded, so nobody can read a claim as second-checked when it wasn't.
            ledger.append("second_opinion_unavailable", {"error": type(exc).__name__}, self.run.case_id)
            return {}

    def _check(self, text: str) -> str:
        run = self.run
        run.attempts += 1
        try:
            draft = parse_draft(text)
        except ValueError as exc:
            run.retry = run.attempts < MAX_ATTEMPTS
            return f"REJECTED: the reply was not valid JSON ({str(exc)[:200]}). Reply with only the JSON object."
        checks: list[proof.ClaimCheck] = []
        for item in draft.claims:
            sid = item.source.strip().strip('"[]')
            if sid not in run.sentences:
                checks.append(proof.ClaimCheck(claim=proof.Claim(claim=item.claim, passage_id="", quote=""), ok=False,
                                               reason=f'"{item.source}" is not one of the numbered source sentences'))
                continue
            passage_id, sentence = run.sentences[sid]
            checks.append(proof.check_claim(proof.Claim(claim=item.claim, passage_id=passage_id, quote=sentence)))
        passed = [c for c in checks if c.ok]
        failed = [c for c in checks if not c.ok]
        semantic = self._semantic_failures(passed)
        kept = []
        for i, check in enumerate(passed):
            if i in semantic:
                failed.append(check.model_copy(update={"ok": False, "reason": "second opinion: " + semantic[i]}))
            else:
                kept.append(check)
        # Keep what has already passed: a later attempt can add claims but can't lose verified ones.
        known = {c.claim.claim for c in run.verified}
        run.verified.extend(c for c in kept if c.claim.claim not in known)
        run.rejected.extend({"attempt": run.attempts, "claim": c.claim.claim, "reason": c.reason} for c in failed)
        run.summary = draft.summary or run.summary
        ledger.append("evidence_checked", {
            "attempt": run.attempts, "passed": len(kept),
            "verified": [{"claim": c.claim.claim, "quote": c.claim.quote, "citation": c.citation, "context": proof.context_of(c.claim.passage_id)} for c in kept],
            "rejected": [{"claim": c.claim.claim, "reason": c.reason} for c in failed],
        }, run.case_id)
        run.retry = bool(failed) and run.attempts < MAX_ATTEMPTS and len(run.verified) < 3
        if not failed:
            return "ACCEPTED: all claims verified."
        return "REJECTED claims, fix or drop them:\n" + "\n".join(f'- "{c.claim.claim}": {c.reason}' for c in failed)

    async def invoke_async(self, task: Any, invocation_state: dict | None = None, **kwargs: Any) -> MultiAgentResult:
        text = task if isinstance(task, str) else "\n".join(block.get("text", "") for block in task)
        # Graph passes earlier node outputs in this text; the newest evidence reply comes after its label.
        marker = text.rfind("From evidence:")
        message = self._check(text[marker:] if marker >= 0 else text)
        result = AgentResult(stop_reason="end_turn", message={"role": "assistant", "content": [{"text": message}]},
                             metrics=EventLoopMetrics(), state={})
        return MultiAgentResult(status=Status.COMPLETED, results={self.id: NodeResult(result=result, status=Status.COMPLETED)})

    async def stream_async(self, task: Any, invocation_state: dict | None = None, **kwargs: Any):
        yield {"result": await self.invoke_async(task, invocation_state, **kwargs)}


def build(case_id: str, passages: list[dict], semantic: bool = True) -> tuple[Any, ProofRun, str]:
    """Returns the graph, its run state, and the numbered source listing to put in the task."""
    sentences, listing = index_sentences(passages)
    run = ProofRun(case_id, sentences)
    evidence = Agent(model=models.reasoner(), system_prompt=EVIDENCE_PROMPT, callback_handler=None, name="evidence")
    builder = GraphBuilder()
    builder.add_node(evidence, "evidence")
    builder.add_node(Verifier(run, semantic and config.lane() != "offline"), "verifier")
    builder.add_edge("evidence", "verifier")
    builder.add_edge("verifier", "evidence", condition=lambda state: run.retry)
    builder.set_entry_point("evidence")
    builder.reset_on_revisit(True)
    builder.set_max_node_executions(MAX_ATTEMPTS * 2)
    builder.set_execution_timeout(600)
    return builder.build(), run, listing
