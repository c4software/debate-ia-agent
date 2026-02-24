"""Custom provider for third-party APIs."""

from typing import Any, AsyncGenerator

import httpx

from .base import LLMProvider, Message, Response


class CustomProvider(LLMProvider):
    """Flexible provider for third-party LLM APIs (OpenAI-compatible or custom format)."""

    def __init__(
        self,
        model: str = "custom",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        base_url: str = "http://localhost:8000/v1",
        api_key: str | None = None,
        headers: dict[str, str] | None = None,
        request_format: str = "openai",
        response_format: str = "openai",
        **kwargs: Any
    ):
        super().__init__(model, temperature, max_tokens, **kwargs)
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = headers or {}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"
        self.request_format = request_format
        self.response_format = response_format
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=120.0, headers=self.headers)
        return self._client

    async def chat(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> Response:
        if self.request_format == "openai":
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": [],
                "temperature": self.temperature,
            }
            if system_prompt:
                payload["messages"].append({
                    "role": "system",
                    "content": system_prompt
                })
            payload["messages"].extend([
                {"role": m.role, "content": m.content}
                for m in messages
            ])
            if self.max_tokens:
                payload["max_tokens"] = self.max_tokens
            endpoint = "/chat/completions"
        else:
            raise ValueError(f"Format de requête non supporté: {self.request_format}")

        response = await self.client.post(
            f"{self.base_url}{endpoint}",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        if self.response_format == "openai":
            content = data["choices"][0]["message"]["content"]
            return Response(
                content=content,
                model=data.get("model", self.model),
                raw_response=data,
            )
        else:
            raise ValueError(f"Format de réponse non supporté: {self.response_format}")

    async def chat_stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> "AsyncGenerator[str, None]":
        if self.request_format != "openai":
            raise ValueError(f"Streaming non supporté pour le format: {self.request_format}")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [],
            "temperature": self.temperature,
            "stream": True,
        }
        if system_prompt:
            payload["messages"].append({
                "role": "system",
                "content": system_prompt
            })
        payload["messages"].extend([
            {"role": m.role, "content": m.content}
            for m in messages
        ])
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens

        async with self.client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip() and line.startswith("data: "):
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    data = eval(data_str)
                    if "choices" in data and data["choices"]:
                        content = data["choices"][0].get("delta", {}).get("content")
                        if content:
                            yield content

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
