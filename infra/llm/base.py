"""LLM provider abstract interface."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMUsage:
    input_tokens: int
    output_tokens: int


class LLMProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def is_available(self) -> bool: ...

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        json_mode: bool = False,
    ) -> tuple[str, LLMUsage]: ...
