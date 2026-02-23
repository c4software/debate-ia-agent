"""Base classes pour les providers LLM."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Coroutine, TypeVar


@dataclass
class Message:
    """Représente un message dans une conversation."""
    role: str
    content: str
    name: str | None = None


@dataclass
class Response:
    """Représente une réponse d'un provider LLM."""
    content: str
    model: str
    raw_response: Any = None
    usage: dict | None = None


class LLMProvider(ABC):
    """Classe de base pour tous les providers LLM."""

    def __init__(
        self,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any
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
        """Envoie une requête de chat et retourne la réponse."""
        pass

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[Message],
        system_prompt: str | None = None,
    ) -> "AsyncGenerator[str, None]":
        """Version streaming de chat."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Ferme les connexions si nécessaire."""
        pass

    def build_messages(
        self,
        user_prompt: str,
        history: list[Message] | None = None,
    ) -> list[Message]:
        """Construit la liste des messages pour l'API."""
        msgs = []
        if history:
            msgs.extend(history)
        msgs.append(Message(role="user", content=user_prompt))
        return msgs

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model})"
