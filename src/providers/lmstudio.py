"""LM Studio provider (local) — uses the OpenAI-compatible /v1/chat/completions API."""

from typing import Any, AsyncGenerator, Literal

from openai import AsyncOpenAI

from .base import LLMProvider, Message, Response

# Reasoning levels understood by this provider.
# "off"  → injects /no_think into the system prompt (DeepSeek/QwQ convention).
# Others → accepted but have no effect; the model decides on its own.
ReasoningLevel = Literal["off", "low", "medium", "high", "on"]


class LMStudioProvider(LLMProvider):
    """Provider for LM Studio using the OpenAI-compatible /v1/chat/completions endpoint.

    Set ``reasoning="off"`` to prepend ``/no_think`` to the system prompt,
    which suppresses chain-of-thought on DeepSeek-R1 / QwQ models loaded in
    LM Studio.  Other reasoning values are accepted but currently ignored.

    Default base URL: http://localhost:1234/v1
    """

    def __init__(
        self,
        model: str = "local-model",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        base_url: str = "http://localhost:1234/v1",
        api_key: str | None = None,
        reasoning: ReasoningLevel | None = None,
        **kwargs: Any,
    ):
        super().__init__(model, temperature, max_tokens, **kwargs)
        self.base_url = base_url
        # LM Studio does not require a real API key; use a placeholder if none given.
        self.api_key = api_key or "lm-studio"
        self.reasoning = reasoning
        self._client: AsyncOpenAI | None = None

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
            )
        return self._client

    def _apply_reasoning(self, system_prompt: str | None) -> str | None:
        """Prepend /no_think to the system prompt when reasoning is disabled."""
        if self.reasoning == "off":
            prefix = "/no_think\n"
            return prefix + (system_prompt or "")
        return system_prompt

    def _build_api_messages(
        self, messages: list[Message], system_prompt: str | None
    ) -> list[dict[str, Any]]:
        api_messages: list[dict[str, Any]] = []
        effective_system = self._apply_reasoning(system_prompt)
        if effective_system:
            api_messages.append({"role": "system", "content": effective_system})
        api_messages.extend(
            {"role": m.role, "content": m.content, "name": m.name} for m in messages
        )
        return api_messages

    async def chat(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> Response:
        api_messages = self._build_api_messages(messages, system_prompt)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature,
        }
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens

        response = await self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        content = self.strip_thinking(choice.message.content or "")
        return Response(
            content=content,
            model=response.model,
            raw_response=response,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
            if response.usage
            else None,
        )

    async def chat_stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> "AsyncGenerator[str, None]":
        api_messages = self._build_api_messages(messages, system_prompt)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature,
            "stream": True,
        }
        if self.max_tokens:
            kwargs["max_tokens"] = self.max_tokens

        response = await self.client.chat.completions.create(**kwargs)

        buffer = ""
        in_think = False
        just_closed_think = False
        async for chunk in response:
            if not chunk.choices or chunk.choices[0].delta.content is None:
                continue
            raw = chunk.choices[0].delta.content
            if not raw:
                continue
            buffer += raw
            while True:
                if in_think:
                    end = buffer.find("</think>")
                    if end == -1:
                        break
                    buffer = buffer[end + len("</think>") :]
                    in_think = False
                    just_closed_think = True
                else:
                    start = buffer.find("<think>")
                    if start == -1:
                        if just_closed_think:
                            buffer = buffer.lstrip("\n")
                            just_closed_think = False
                        yield buffer
                        buffer = ""
                        break
                    if start > 0:
                        yield buffer[:start]
                    buffer = buffer[start + len("<think>") :]
                    in_think = True
                    just_closed_think = False
        if buffer and not in_think:
            if just_closed_think:
                buffer = buffer.lstrip("\n")
            yield buffer

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
