"""Ollama provider (local)."""

import json
from typing import Any, AsyncGenerator

import httpx

from .base import LLMProvider, Message, Response


class OllamaProvider(LLMProvider):
    """Provider for Ollama (local LLM models)."""

    def __init__(
        self,
        model: str = "llama3",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        base_url: str = "http://localhost:11434",
        **kwargs: Any,
    ):
        super().__init__(model, temperature, max_tokens, **kwargs)
        self.base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=520.0)
        return self._client

    async def chat(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> Response:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [],
            "temperature": self.temperature,
            "stream": False,
        }
        if system_prompt:
            payload["messages"].append({"role": "system", "content": system_prompt})
        payload["messages"].extend([{"role": m.role, "content": m.content} for m in messages])
        if self.max_tokens:
            payload["options"] = {"num_predict": self.max_tokens}

        response = await self.client.post(
            f"{self.base_url}/api/chat",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        return Response(
            content=self.strip_thinking(data["message"]["content"]),
            model=data.get("model", self.model),
            raw_response=data,
        )

    async def chat_stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> "AsyncGenerator[str, None]":
        """Streaming version of chat."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [],
            "temperature": self.temperature,
            "stream": True,
        }
        if system_prompt:
            payload["messages"].append({"role": "system", "content": system_prompt})
        payload["messages"].extend([{"role": m.role, "content": m.content} for m in messages])
        if self.max_tokens:
            payload["options"] = {"num_predict": self.max_tokens}

        async with self.client.stream(
            "POST",
            f"{self.base_url}/api/chat",
            json=payload,
        ) as response:
            response.raise_for_status()
            buffer = ""
            in_think = False
            just_closed_think = False
            async for line in response.aiter_lines():
                if line.strip():
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if "message" in data and "content" in data["message"]:
                        chunk = data["message"]["content"]
                        if not chunk:
                            continue
                        buffer += chunk
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
            await self._client.aclose()
            self._client = None
