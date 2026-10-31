"""emerald-dosing: dose arithmetic from a table of quoted guideline rows, and signed treatment plans.

No model does this sum, and a plan can only be issued with a vet's signature.
"""

from mcp.server.mcpserver import MCPServer

from emerald import actions, dosing

mcp = MCPServer("emerald-dosing")


@mcp.tool()
def compute_dose(disease: str, drug: str, weight_kg: float) -> dict:
    """Work out the guideline dose for cattle or buffalo. Returns 'vet_decides' if the guideline table has no entry."""
    return dosing.compute(disease, drug, weight_kg)


@mcp.tool()
def prescribe_treatment(case_id: str, disease: str, drug: str, signoff_id: str = "") -> dict:
    """IRREVERSIBLE. Issue a treatment plan for the vet to give. The dose comes from code using the recorded weight, and a vet must sign."""
    return actions.prescribe_treatment(case_id, disease, drug, signoff_id)


if __name__ == "__main__":
    mcp.run()
