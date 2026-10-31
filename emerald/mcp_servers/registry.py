"""emerald-registry: synthetic farmers, vets and doctors."""

from mcp.server.mcpserver import MCPServer

from emerald import registry

mcp = MCPServer("emerald-registry")


@mcp.tool()
def find_nearest_vet(lat: float, lon: float) -> dict:
    """Nearest vet to a location, with their consult fee in INR."""
    return registry.nearest("vets", lat, lon)


@mcp.tool()
def find_nearest_doctor(lat: float, lon: float) -> dict:
    """Nearest doctor or health centre to a location."""
    return registry.nearest("doctors", lat, lon)


if __name__ == "__main__":
    mcp.run()
