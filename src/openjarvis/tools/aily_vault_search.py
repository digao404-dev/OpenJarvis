"""Search AILY's curated Markdown vault from agents and MCP clients."""

from __future__ import annotations

from typing import Any

from openjarvis.aily_vault import VaultIndex
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("aily_vault_search")
class AilyVaultSearchTool(BaseTool):
    tool_id = "aily_vault_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Search AILY's Markdown knowledge vault. Returns excerpts with "
                "absolute source paths and curation status. Pending captures "
                "are excluded unless explicitly requested."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Words to search for."},
                    "top_k": {
                        "type": "integer",
                        "description": "Maximum results, 1 to 20.",
                    },
                    "include_pending": {
                        "type": "boolean",
                        "description": "Also search unreviewed Brain/AILY captures.",
                    },
                },
                "required": ["query"],
            },
            category="knowledge",
        )

    def execute(self, **params: Any) -> ToolResult:
        query = params.get("query", "")
        if not isinstance(query, str) or not query.strip():
            return ToolResult(self.tool_id, "Informe uma busca não vazia.", False)
        try:
            results = VaultIndex().search(
                query,
                top_k=params.get("top_k", 5),
                include_pending=params.get("include_pending") is True,
            )
        except (OSError, ValueError) as exc:
            return ToolResult(self.tool_id, f"Busca no vault falhou: {exc}", False)
        if not results:
            return ToolResult(self.tool_id, "Nenhuma nota encontrada.")
        lines = [
            f"{i}. {result.title} [status: {result.status}]\n"
            f"   Fonte: {result.path}\n"
            f"   Trecho: {result.excerpt}"
            for i, result in enumerate(results, 1)
        ]
        return ToolResult(self.tool_id, "\n\n".join(lines))
