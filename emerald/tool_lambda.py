"""AWS Lambda behind AgentCore Gateway: the stateless tools, for anyone the gateway's policy allows."""

from __future__ import annotations

from . import dosing, knowledge


def handler(event: dict, context) -> object:
    name = context.client_context.custom["bedrockAgentCoreToolName"].split("___")[-1]
    if name == "search_guidelines":
        return [
            {"passage_id": p["id"], "disease": p["disease"], "section": p["section"], "page": p["page"], "source": p["title"], "text": p["text"]}
            for p in knowledge.search(event["query"], event.get("disease") or None, k=4)
        ]
    if name == "compute_dose":
        return dosing.compute(event["disease"], event["drug"], float(event["weight_kg"]))
    raise ValueError(f"unknown tool {name}")
