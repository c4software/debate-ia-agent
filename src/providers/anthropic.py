"""Provider Anthropic."""

import os
from typing import Any, AsyncGenerator

from anthropic import AsyncAnthropic

from .base import LLMProvider, Message, Response


class AnthropicProvider(LLMProvider):
    """Provider pour l'API Anthropic (Claude)."""

    def __init__(
        self,
        model: str = "claude-3-5-sonnet-20241022",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any
    ):
        super().__init__(model, temperature, max_tokens, **kwargs)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self.base_url = base_url
        self._client: AsyncAnthropic | None = None

    @property
    def client(self) -> AsyncAnthropic:
        if self._client is None:
            self._client = AsyncAnthropic(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._client

    async def chat(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> Response:
        api_messages = []
        for m in messages:
            if m.role == "system" and not system_prompt:
                system_prompt = m.content
            else:
                api_messages.append({
                    "role": m.role,
                    "content": m.content
                })

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens

        response = await self.client.messages.create(**kwargs)
        content = response.content[0].text if response.content else ""
        return Response(
            content=content,
            model=response.model,
            raw_response=response,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            } if response.usage else None,
        )

    async def chat_stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> "AsyncGenerator[str, None]":
        api_messages = []
        for m in messages:
            if m.role == "system" and not system_prompt:
                system_prompt = m.content
            else:
                api_messages.append({
                    "role": m.role,
                    "content": m.content
                })

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature,
            "stream": True,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens

        async with self.client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def close(self) -> None:
        self._client = None
