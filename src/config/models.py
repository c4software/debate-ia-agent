"""Configuration for agents-meeting project."""

import os
from pydantic import BaseModel, Field, field_validator
from typing import Any


class APIKeysConfig(BaseModel):
    """Global API keys configuration."""

    openai: str | None = Field(default=None, description="OpenAI key")
    anthropic: str | None = Field(default=None, description="Anthropic key")
    gemini: str | None = Field(default=None, description="Google Gemini API key")
    ollama: str | None = Field(default=None, description="Ollama URL (optional)")
    custom: str | None = Field(default=None, description="Custom API key")
    lmstudio: str | None = Field(
        default=None, description="LM Studio API key (optional, not required by default)"
    )

    @field_validator("openai", "anthropic", "gemini", "custom")
    @classmethod
    def resolve_env_var(cls, v: str | None) -> str | None:
        if v and v.startswith("env:"):
            env_name = v[4:]
            return os.getenv(env_name) or v
        return v


class AgentConfig(BaseModel):
    """Configuration for an agent."""

    name: str = Field(..., description="Agent name")
    role: str = Field(..., description="Role/description of the agent")
    provider: str = Field(
        ..., description="Provider: openai, anthropic, gemini, ollama, custom, lmstudio"
    )
    model: str = Field(default="gpt-4o", description="Model to use")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, description="Token limit")
    api_key: str | None = Field(default=None, description="API key (or env:VAR_NAME)")
    base_url: str | None = Field(default=None, description="API URL")
    is_leader: bool = Field(default=False, description="This agent is the leader/moderator")
    extra: dict[str, Any] = Field(default_factory=dict, description="Additional parameters")

    def resolve_api_key(self, global_keys: APIKeysConfig | None = None) -> str | None:
        """Resolve the API key (local or global)."""
        if self.api_key:
            if self.api_key.startswith("env:"):
                return os.getenv(self.api_key[4:])
            return self.api_key
        if global_keys:
            provider_key = getattr(global_keys, self.provider, None)
            if provider_key:
                if provider_key.startswith("env:"):
                    return os.getenv(provider_key[4:])
                return provider_key
        return None


class DebateConfig(BaseModel):
    """Configuration for the debate."""

    rounds: int = Field(default=2, ge=1, le=10, description="Number of discussion rounds")
    initial_prompt: str = Field(..., description="Initial question/prompt")
    system_prompt: str | None = Field(
        default=None, description="Optional system prompt for all agents"
    )
    leader_prompt: str | None = Field(
        default=None, description="Additional prompt for the leader (moderation instructions)"
    )

    # --- Configurable prompt templates (English defaults) ---

    intro_prompt: str = Field(
        default=(
            "You are the moderator of a debate. "
            "Present the following topic clearly, frame the issues "
            "and ask the initial questions that participants must answer:\n\n"
            "TOPIC: {initial_prompt}"
        ),
        description=(
            "Prompt sent to the moderator to open the debate. "
            "Use {initial_prompt} for the debate topic."
        ),
    )

    moderator_context_prefix: str = Field(
        default="The moderator said:\n{content}",
        description=(
            "Prefix injected into agents' context before each round. "
            "Use {content} for the moderator's last message."
        ),
    )

    round_header_template: str = Field(
        default="Round {round_num} — Participant responses:",
        description=(
            "Header line in the moderator's intervention prompt. "
            "Use {round_num} for the round number."
        ),
    )

    intervention_prompt: str = Field(
        default=(
            "As moderator, synthesize the positions expressed this round, "
            "identify points of convergence and divergence, "
            "then ask a refined question to deepen the debate for the next round."
        ),
        description="Instruction given to the moderator for mid-debate round synthesis.",
    )

    intervention_last_prompt: str = Field(
        default=(
            "As moderator, provide a complete synthesis of the positions "
            "expressed this round. Identify points of convergence and divergence."
        ),
        description="Instruction given to the moderator for the final-round synthesis.",
    )

    conclusion_prompt: str = Field(
        default=(
            "Original question: {initial_prompt}\n\n"
            "Here are all participant interventions across all rounds:\n\n"
            "{turns}\n\n"
            "As moderator, provide a balanced final synthesis of the debate: "
            "summarize the main positions, points of agreement and disagreement, "
            "and propose a general conclusion."
        ),
        description=(
            "Prompt for the moderator's final synthesis. "
            "Use {initial_prompt} and {turns} (all agent turns joined)."
        ),
    )

    continuation_prompt: str = Field(
        default=(
            'You just moderated a debate on the topic: "{initial_prompt}".\n\n'
            "Here is your final synthesis:\n{conclusion_text}\n\n"
            "Propose only one short and precise follow-up question that would deepen "
            "or broaden the debate. Respond only with the question, without introduction or explanation."
        ),
        description=(
            "Prompt used to generate a follow-up question after the debate. "
            "Use {initial_prompt} and {conclusion_text}."
        ),
    )

    previous_debate_label: str = Field(
        default='[Synthesis of previous debate on "{initial_prompt}"]',
        description=(
            "Label injected into the leader's LLM history when continuing a debate. "
            "Use {initial_prompt} for the previous topic."
        ),
    )

    previous_context_label: str = Field(
        default='[Context — previous debate on "{initial_prompt}"]',
        description=(
            "Context prefix injected into agents' starting context for a continuation. "
            "Use {initial_prompt} for the previous topic."
        ),
    )

    agent_identity_template: str = Field(
        default="You are {name}. {role}",
        description=(
            "Template for the agent identity line in the system prompt. Use {name} and {role}."
        ),
    )

    agent_context_template: str = Field(
        default="Other agents' context:\n{context}\n\nQuestion: {prompt}",
        description=(
            "Template wrapping the user message when context is provided. "
            "Use {context} and {prompt}."
        ),
    )


class MeetingConfig(BaseModel):
    """Complete meeting configuration."""

    agents: list[AgentConfig] = Field(..., description="List of agents")
    debate: DebateConfig = Field(..., description="Debate configuration")
    title: str | None = Field(default=None, description="Meeting title")
    api_keys: APIKeysConfig | None = Field(default=None, description="Global API keys")
