"""Base classes for LLM providers."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Coroutine, TypeVar


@dataclass
class Message:
    """Represents a message in a conversation."""

    role: str
    content: str
    name: str | None = None


@dataclass
class Response:
    """Represents a response from an LLM provider."""

    content: str
    model: str
    raw_response: Any = None
    usage: dict | None = None


class LLMProvider(ABC):
    """Base class for all LLM providers."""

    def __init__(
        self, model: str, temperature: float = 0.7, max_tokens: int | None = None, **kwargs: Any
    ):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.extra_kwargs = kwargs

    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> Response:
        """Send a chat request and return the response."""
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> "AsyncGenerator[str, None]":
        """Streaming version of chat."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close connections if necessary."""
        pass

    def build_messages(
        self,
        user_prompt: str,
        history: list[Message] | None = None,
    ) -> list[Message]:
        """Build the list of messages for the API."""
        msgs = []
        if history:
            msgs.extend(history)
        msgs.append(Message(role="user", content=user_prompt))
        return msgs

    @staticmethod
    def strip_thinking(text: str) -> str:
        """Remove <think>...</think> blocks from model output.

        Some local models (DeepSeek-R1, QwQ, etc.) embed their chain-of-thought
        inside <think> tags inline with the response text. This method strips
        those blocks and trims any leading/trailing whitespace left behind.
        """
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model})"
