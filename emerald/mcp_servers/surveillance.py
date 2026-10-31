"""emerald-surveillance: case lookup, the cluster detector, and the signed outbreak report."""

from mcp.server.mcpserver import MCPServer

from emerald import actions, surveillance

mcp = MCPServer("emerald-surveillance")


@mcp.tool()
def get_case(case_id: str) -> dict:
    """Read a recorded case: signs, candidate diseases, red flags."""
    return surveillance.get_case(case_id) or {"error": "no such case"}


@mcp.tool()
def check_cluster(case_id: str) -> dict:
    """Ask the cluster detector whether this case is part of a suspected outbreak."""
    return surveillance.find_cluster(case_id) or {"cluster": False}


@mcp.tool()
def file_outbreak_report(case_id: str, disease: str, signoff_id: str = "") -> dict:
    """IRREVERSIBLE. File the legally required report for a detected cluster. Needs a vet's signature."""
    return actions.file_outbreak_report(case_id, disease, signoff_id)


if __name__ == "__main__":
    mcp.run()
