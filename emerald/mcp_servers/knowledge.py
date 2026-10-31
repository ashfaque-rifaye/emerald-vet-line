"""emerald-knowledge: official guideline and statute passages, each with a source, page and hash."""

from mcp.server.mcpserver import MCPServer

from emerald import knowledge

mcp = MCPServer("emerald-knowledge")


@mcp.tool()
def search_guidelines(query: str, disease: str = "") -> list[dict]:
    """Search official veterinary guidelines and the 2009 animal diseases Act. disease is optional: lsd, fmd, hs, anthrax, bq, rabies or mastitis."""
    return [
        {"passage_id": p["id"], "disease": p["disease"], "section": p["section"], "page": p["page"], "source": p["title"], "text": p["text"]}
        for p in knowledge.search(query, disease or None, k=4)
    ]


@mcp.tool()
def get_passage(passage_id: str) -> dict:
    """Fetch one passage by id, with its hash so a citation can be re-checked."""
    return knowledge.get(passage_id) or {"error": "no such passage"}


if __name__ == "__main__":
    mcp.run()
