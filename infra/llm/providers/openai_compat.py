"""OpenAI-compatible Chat Completions provider."""

from __future__ import annotations

import os
import time

import openai
from openai import AsyncOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from infra.llm.base import LLMUsage
from infra.log import get_logger

logger = get_logger(__name__)

_RETRYABLE = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
)


class OpenAICompatProvider:
    """Adapter for OpenAI-compatible chat completion APIs."""

    def __init__(
        self,
        provider_name: str,
        model: str,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int = 30,
        require_api_key: bool = True,
    ) -> None:
        self._provider_name = provider_name
        self._model = model
        self._api_key = api_key or ""
        self._base_url = base_url or None
        self._timeout = timeout
        self._require_api_key = require_api_key
        self._client: AsyncOpenAI | None = None

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model

    def is_available(self) -> bool:
        if not self._require_api_key:
            return True
        return bool(self._api_key)

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            kwargs: dict = {"api_key": self._api_key or "ollama"}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_fixed(2),
        retry=retry_if_exception_type(_RETRYABLE),
        reraise=True,
    )
    async def _create_completion(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        json_mode: bool,
        use_json_format: bool,
    ):
        client = self._get_client()
        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
            "timeout": self._timeout,
        }
        if json_mode and use_json_format:
            kwargs["response_format"] = {"type": "json_object"}
        return await client.chat.completions.create(**kwargs)

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        json_mode: bool = False,
    ) -> tuple[str, LLMUsage]:
        start = time.perf_counter()
        use_json_format = json_mode
        try:
            response = await self._create_completion(
                messages,
                max_tokens=max_tokens,
                json_mode=json_mode,
                use_json_format=use_json_format,
            )
        except openai.BadRequestError:
            if json_mode and use_json_format:
                response = await self._create_completion(
                    messages,
                    max_tokens=max_tokens,
                    json_mode=json_mode,
                    use_json_format=False,
                )
            else:
                raise

        duration_ms = int((time.perf_counter() - start) * 1000)
        content = (response.choices[0].message.content or "").strip()
        usage = response.usage
        token_input = usage.prompt_tokens if usage else 0
        token_output = usage.completion_tokens if usage else 0
        logger.info(
            "llm_call",
            provider=self._provider_name,
            model=self._model,
            duration_ms=duration_ms,
            token_input=token_input,
            token_output=token_output,
            status="success",
        )
        return content, LLMUsage(input_tokens=token_input, output_tokens=token_output)


def build_openai_compat_provider(
    provider_name: str,
    model: str,
    api_key_env: str,
    base_url: str | None,
    timeout: int,
) -> OpenAICompatProvider:
    api_key = os.environ.get(api_key_env, "") if api_key_env else ""
    require_api_key = provider_name != "ollama"
    return OpenAICompatProvider(
        provider_name=provider_name,
        model=model,
        api_key=api_key or None,
        base_url=base_url,
        timeout=timeout,
        require_api_key=require_api_key,
    )
