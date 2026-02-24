"""OpenAI provider."""

import os
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI

from .base import LLMProvider, Message, Response


class OpenAIProvider(LLMProvider):
    """Provider for OpenAI API."""

    def __init__(
        self,
        model: str = "gpt-4o",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        **kwargs: Any
    ):
        super().__init__(model, temperature, max_tokens, **kwargs)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
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
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend([
            {"role": m.role, "content": m.content, "name": m.name}
            for m in messages
        ])

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature,
        }
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens

        response = await self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        return Response(
            content=choice.message.content or "",
            model=response.model,
            raw_response=response,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            } if response.usage else None,
        )

    async def chat_stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> "AsyncGenerator[str, None]":
        api_messages = []
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})
        api_messages.extend([
            {"role": m.role, "content": m.content, "name": m.name}
            for m in messages
        ])

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature,
            "stream": True,
        }
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens

        response = await self.client.chat.completions.create(**kwargs)
        async for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
