"""emerald-ledger: read and re-verify the tamper-evident record.

The agent can only read the ledger. Entries are written by the actions themselves, never by a model.
"""

import json

from mcp.server.mcpserver import MCPServer

from emerald import ledger

mcp = MCPServer("emerald-ledger")


@mcp.tool()
def read_case_record(case_id: str) -> list[dict]:
    """Everything recorded for a case, in order."""
    return [{"seq": e["seq"], "ts": e["ts"], "type": e["type"], "payload": json.loads(e["payload"]), "hash": e["hash"]}
            for e in ledger.entries(case_id)]


@mcp.tool()
def verify_ledger() -> dict:
    """Re-derive the whole hash chain and check every signature."""
    return ledger.verify()


if __name__ == "__main__":
    mcp.run()
