"""Google Gemini provider."""

import os
from typing import Any, AsyncGenerator

from google import genai
from google.genai import types

from .base import LLMProvider, Message, Response


class GeminiProvider(LLMProvider):
    """Provider for Google Gemini API."""

    def __init__(
        self,
        model: str = "gemini-2.0-flash",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        api_key: str | None = None,
        **kwargs: Any,
    ):
        super().__init__(model, temperature, max_tokens, **kwargs)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self._client: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _build_contents(
        self,
        messages: list[Message],
    ) -> list[types.Content]:
        """Convert internal Message list to Gemini contents format.

        Gemini uses 'user' and 'model' roles (not 'assistant').
        Consecutive messages of the same role are merged to satisfy the
        alternating-turn requirement of the Gemini API.
        """
        contents: list[types.Content] = []
        for m in messages:
            role = "model" if m.role == "assistant" else "user"
            if contents and contents[-1].role == role:
                # Merge consecutive same-role messages
                existing_text = contents[-1].parts[0].text  # type: ignore[index]
                contents[-1] = types.Content(
                    role=role,
                    parts=[types.Part(text=existing_text + "\n" + m.content)],
                )
            else:
                contents.append(
                    types.Content(
                        role=role,
                        parts=[types.Part(text=m.content)],
                    )
                )
        return contents

    def _build_config(self) -> types.GenerateContentConfig:
        """Build the generation config."""
        config: dict[str, Any] = {"temperature": self.temperature}
        if self.max_tokens:
            config["max_output_tokens"] = self.max_tokens
        return types.GenerateContentConfig(**config)

    async def chat(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> Response:
        contents = self._build_contents(messages)
        gen_config = self._build_config()
        if system_prompt:
            gen_config.system_instruction = system_prompt

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=gen_config,
        )

        content = response.text or ""
        usage = None
        if response.usage_metadata:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count,
                "completion_tokens": response.usage_metadata.candidates_token_count,
                "total_tokens": response.usage_metadata.total_token_count,
            }

        return Response(
            content=content,
            model=self.model,
            raw_response=response,
            usage=usage,
        )

    async def chat_stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> "AsyncGenerator[str, None]":
        contents = self._build_contents(messages)
        gen_config = self._build_config()
        if system_prompt:
            gen_config.system_instruction = system_prompt

        async for chunk in await self.client.aio.models.generate_content_stream(
            model=self.model,
            contents=contents,
            config=gen_config,
        ):
            if chunk.text:
                yield chunk.text

    async def close(self) -> None:
        self._client = None
