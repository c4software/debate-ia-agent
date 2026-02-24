"""Agents pour agents-meeting."""

import asyncio
from dataclasses import dataclass, field
from typing import AsyncGenerator

from src.config import AgentConfig, APIKeysConfig
from src.providers import (
    LLMProvider,
    Message,
    OpenAIProvider,
    AnthropicProvider,
    OllamaProvider,
    CustomProvider,
)


@dataclass
class Turn:
    """Un tour de parole d'un agent."""
    round: int
    phase: str
    content: str
    timestamp: float = 0.0


@dataclass
class Agent:
    """Représente un agent dans le débat."""
    config: AgentConfig
    global_api_keys: APIKeysConfig | None = None
    provider: LLMProvider = field(init=False)
    history: list[Message] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.provider = self._create_provider()

    def _create_provider(self) -> LLMProvider:
        extra = self.config.extra or {}
        api_key = self.config.resolve_api_key(self.global_api_keys)
        
        if self.config.provider == "openai":
            return OpenAIProvider(
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                api_key=api_key,
                base_url=self.config.base_url,
                **extra,
            )
        elif self.config.provider == "anthropic":
            return AnthropicProvider(
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                api_key=api_key,
                base_url=self.config.base_url,
                **extra,
            )
        elif self.config.provider == "ollama":
            return OllamaProvider(
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                base_url=self.config.base_url or "http://localhost:11434",
                **extra,
            )
        elif self.config.provider == "custom":
            return CustomProvider(
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                base_url=self.config.base_url or "http://localhost:8000/v1",
                api_key=api_key,
                **extra,
            )
        else:
            raise ValueError(f"Provider inconnu: {self.config.provider}")

    def build_system_prompt(
        self,
        global_system: str | None = None,
        leader_prompt: str | None = None,
    ) -> str:
        """Construit le system prompt pour l'agent."""
        parts = []
        if global_system:
            parts.append(global_system)
        parts.append(f"Tu es {self.config.name}. {self.config.role}")
        if leader_prompt:
            parts.append(leader_prompt)
        return "\n\n".join(parts)

    async def think(
        self,
        prompt: str,
        context: str | None = None,
        system_prompt: str | None = None,
        leader_prompt: str | None = None,
    ) -> str:
        """L'agent réfléchit et répond au prompt."""
        system = self.build_system_prompt(system_prompt, leader_prompt)
        
        user_content = prompt
        if context:
            user_content = f"Contexte des autres agents:\n{context}\n\nQuestion: {prompt}"
        
        messages = list(self.history) + [Message(role="user", content=user_content)]
        
        response = await self.provider.chat(
            messages=messages,
            system_prompt=system,
        )
        
        self.history.append(Message(role="user", content=user_content))
        self.history.append(Message(role="assistant", content=response.content))
        
        return response.content

    async def think_stream(
        self,
        prompt: str,
        context: str | None = None,
        system_prompt: str | None = None,
        leader_prompt: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Version streaming de think."""
        system = self.build_system_prompt(system_prompt, leader_prompt)
        
        user_content = prompt
        if context:
            user_content = f"Contexte des autres agents:\n{context}\n\nQuestion: {prompt}"
        
        messages = list(self.history) + [Message(role="user", content=user_content)]
        
        full_content = ""
        async for chunk in self.provider.chat_stream(
            messages=messages,
            system_prompt=system,
        ):
            full_content += chunk
            yield chunk
        
        self.history.append(Message(role="user", content=user_content))
        self.history.append(Message(role="assistant", content=full_content))

    async def react(
        self,
        prompt: str,
        other_agents_responses: dict[str, str],
        system_prompt: str | None = None,
    ) -> str:
        """L'agent réagit aux réponses des autres agents."""
        context_lines = [
            f"### Réponse de {name}:"
            for name in other_agents_responses.keys()
        ]
        context_lines.append("")
        for name, response in other_agents_responses.items():
            context_lines.append(f"**{name}**: {response}")
        
        context = "\n".join(context_lines)
        return await self.think(prompt, context=context, system_prompt=system_prompt)

    async def close(self) -> None:
        """Ferme les ressources de l'agent."""
        await self.provider.close()

    def __repr__(self) -> str:
        return f"Agent({self.config.name}, provider={self.config.provider}:{self.config.model})"
