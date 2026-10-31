"""emerald-payments: capped payments from the village fund. Needs a vet's signature on the exact amount."""

from mcp.server.mcpserver import MCPServer

from emerald import actions

mcp = MCPServer("emerald-payments")


@mcp.tool()
def pay_vet_consult(case_id: str, vet_id: str, amount_inr: float, signoff_id: str = "") -> dict:
    """IRREVERSIBLE. Pay a vet's consult fee from the village fund."""
    return actions.pay_vet_consult(case_id, vet_id, amount_inr, signoff_id)


if __name__ == "__main__":
    mcp.run()
