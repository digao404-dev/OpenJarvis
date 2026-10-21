"""Agent-visible preparation and inspection; execution stays in AILY CLI."""

from __future__ import annotations

import json
from typing import Any

from openjarvis.aily_actions import get, prepare
from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("aily_prepare_action")
class AilyPrepareActionTool(BaseTool):
    tool_id = "aily_prepare_action"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Prepare an AILY note or calendar event for explicit human "
                "approval. Does not write the note or calendar."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["note", "calendar_event"]},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "start": {
                        "type": "string",
                        "description": "ISO 8601 with timezone",
                    },
                    "end": {"type": "string", "description": "ISO 8601 with timezone"},
                    "description": {"type": "string"},
                    "calendar_id": {"type": "string"},
                },
                "required": ["kind", "title"],
            },
            category="aily",
        )

    def execute(self, **params: Any) -> ToolResult:
        kind = params.pop("kind", "")
        try:
            action = prepare(kind, params)
        except (ValueError, TypeError, OSError) as exc:
            return ToolResult(self.tool_id, str(exc), False)
        return ToolResult(
            self.tool_id,
            json.dumps(action, ensure_ascii=False)
            + f"\nAguardando aprovação humana: aily action approve {action['id']}",
        )


@ToolRegistry.register("aily_action_status")
class AilyActionStatusTool(BaseTool):
    tool_id = "aily_action_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect status and verified result of a prepared AILY action.",
            parameters={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            category="aily",
        )

    def execute(self, **params: Any) -> ToolResult:
        action = get(str(params.get("id", "")))
        return ToolResult(
            self.tool_id,
            json.dumps(action, ensure_ascii=False)
            if action
            else "Ação não encontrada.",
            bool(action),
        )
