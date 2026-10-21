"""Minimal stdio MCP endpoint for Claude's AILY vault search tool."""

from __future__ import annotations

import json
import sys

from openjarvis.mcp.protocol import MCPRequest
from openjarvis.mcp.server import MCPServer
from openjarvis.tools.aily_actions import AilyActionStatusTool, AilyPrepareActionTool
from openjarvis.tools.aily_vault_search import AilyVaultSearchTool


def main() -> None:
    server = MCPServer(
        tools=[AilyVaultSearchTool(), AilyPrepareActionTool(), AilyActionStatusTool()]
    )
    for line in sys.stdin:
        try:
            payload = json.loads(line)
            if "id" not in payload:
                continue  # MCP notifications have no response.
            response = server.handle(MCPRequest.from_json(line))
            print(response.to_json(), flush=True)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            print(f"Invalid MCP request: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
