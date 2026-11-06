"""Validated MCP tool input models; none accepts caller-selected SQL or scope."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ..api.schemas.common import (
    LocaleCode,
    OpaqueId,
    SchemaModel,
    SearchQuery,
    TicketMessage,
)


class MCPInvestigationInput(SchemaModel):
    ticket_id: OpaqueId | None = None
    message: TicketMessage | None = None
    order_id: OpaqueId | None = None
    query: SearchQuery | None = None
    locale: LocaleCode = "en-IN"
    top_k: int = Field(default=3, ge=1, le=10)
    methods: list[Literal["semantic", "keyword"]] = Field(
        default_factory=lambda: ["semantic", "keyword"], min_length=1, max_length=2
    )

    @model_validator(mode="after")
    def require_one_ticket_source(self):
        if not self.ticket_id and not self.message:
            raise ValueError("provide a ticket_id, a message, or both")
        if len(set(self.methods)) != len(self.methods):
            raise ValueError("methods must not contain duplicates")
        return self
