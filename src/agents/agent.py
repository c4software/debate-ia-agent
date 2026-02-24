"""Agents for agents-meeting."""

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
    """A turn of speech for an agent."""
    round: int
    phase: str
    content: str
    timestamp: float = 0.0


@dataclass
class Agent:
    """Represents an agent in the debate."""
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
            raise ValueError(f"Unknown provider: {self.config.provider}")

    def build_system_prompt(
        self,
        global_system: str | None = None,
        leader_prompt: str | None = None,
        identity_template: str | None = None,
    ) -> str:
        """Build the system prompt for the agent."""
        parts = []
        if global_system:
            parts.append(global_system)
        template = identity_template or "You are {name}. {role}"
        parts.append(template.format(name=self.config.name, role=self.config.role))
        if leader_prompt:
            parts.append(leader_prompt)
        return "\n\n".join(parts)

    async def think(
        self,
        prompt: str,
        context: str | None = None,
        system_prompt: str | None = None,
        leader_prompt: str | None = None,
        identity_template: str | None = None,
        context_template: str | None = None,
    ) -> str:
        """The agent thinks and responds to the prompt."""
        system = self.build_system_prompt(system_prompt, leader_prompt, identity_template)

        user_content = prompt
        if context:
            tmpl = context_template or "Other agents' context:\n{context}\n\nQuestion: {prompt}"
            user_content = tmpl.format(context=context, prompt=prompt)

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
        identity_template: str | None = None,
        context_template: str | None = None,
    ) -> AsyncGenerator[str, None]:
        """Streaming version of think."""
        system = self.build_system_prompt(system_prompt, leader_prompt, identity_template)

        user_content = prompt
        if context:
            tmpl = context_template or "Other agents' context:\n{context}\n\nQuestion: {prompt}"
            user_content = tmpl.format(context=context, prompt=prompt)

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
        """The agent reacts to other agents' responses."""
        context_lines = [
            f"### Response from {name}:"
            for name in other_agents_responses.keys()
        ]
        context_lines.append("")
        for name, response in other_agents_responses.items():
            context_lines.append(f"**{name}**: {response}")
        
        context = "\n".join(context_lines)
        return await self.think(prompt, context=context, system_prompt=system_prompt)

    async def close(self) -> None:
        """Close the agent's resources."""
        await self.provider.close()

    def __repr__(self) -> str:
        return f"Agent({self.config.name}, provider={self.config.provider}:{self.config.model})"
