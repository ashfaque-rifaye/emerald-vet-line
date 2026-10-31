"""emerald-telephony: outbound calls. Results name the provider, so a simulated call says it is simulated."""

from mcp.server.mcpserver import MCPServer

from emerald import actions

mcp = MCPServer("emerald-telephony")


@mcp.tool()
def call_vet(case_id: str, evidence_summary: str) -> dict:
    """Phone the nearest vet and read them the evidence pack. Use this for every case."""
    return actions.call_vet(case_id, evidence_summary)


@mcp.tool()
def call_doctor(case_id: str, reason: str) -> dict:
    """Phone the nearest doctor when people may have been exposed to a disease that can pass to humans."""
    return actions.call_doctor(case_id, reason)


@mcp.tool()
def tell_farmer(case_id: str, message: str) -> dict:
    """Tell the farmer what to do now, in plain words."""
    return actions.tell_farmer(case_id, message)


@mcp.tool()
def start_ring_calls(case_id: str, disease: str, signoff_id: str = "") -> dict:
    """IRREVERSIBLE. Phone every registered household around a detected outbreak. Needs a vet's signature."""
    return actions.start_ring_calls(case_id, disease, signoff_id)


if __name__ == "__main__":
    mcp.run()
