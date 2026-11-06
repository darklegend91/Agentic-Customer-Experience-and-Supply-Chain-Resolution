"""Shared API boundary types and schema conventions."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class VersionedRequest(SchemaModel):
    schema_version: Literal["1.0"]


OpaqueId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
TicketMessage = Annotated[str, Field(min_length=1, max_length=5000)]
SearchQuery = Annotated[str, Field(min_length=3, max_length=3000)]
LocaleCode = Annotated[str, Field(min_length=5, max_length=8, pattern=r"^[a-z]{2}-[A-Z]{2}$")]
PolicyMethod = Literal["semantic", "keyword"]
ReadStatus = Literal["found", "not_found", "insufficient_data"]


class MethodsRequest(VersionedRequest):
    methods: list[PolicyMethod] = Field(default_factory=lambda: ["semantic", "keyword"], min_length=1, max_length=2)

    @field_validator("methods")
    @classmethod
    def unique_methods(cls, methods: list[PolicyMethod]) -> list[PolicyMethod]:
        if len(set(methods)) != len(methods):
            raise ValueError("methods must not contain duplicates")
        return methods


class VersionedResponse(SchemaModel):
    schema_version: Literal["1.0"] = "1.0"
