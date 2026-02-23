"""Configuration du projet agents-meeting."""

import os
from pydantic import BaseModel, Field, field_validator
from typing import Any


class APIKeysConfig(BaseModel):
    """Configuration des clefs API globales."""
    openai: str | None = Field(default=None, description="Clé OpenAI")
    anthropic: str | None = Field(default=None, description="Clé Anthropic")
    ollama: str | None = Field(default=None, description="URL Ollama (optionnel)")
    custom: str | None = Field(default=None, description="Clé API custom")

    @field_validator("openai", "anthropic", "custom")
    @classmethod
    def resolve_env_var(cls, v: str | None) -> str | None:
        if v and v.startswith("env:"):
            env_name = v[4:]
            return os.getenv(env_name) or v
        return v


class AgentConfig(BaseModel):
    """Configuration d'un agent."""
    name: str = Field(..., description="Nom de l'agent")
    role: str = Field(..., description="Rôle/description de l'agent")
    provider: str = Field(..., description="Provider: openai, anthropic, ollama, custom")
    model: str = Field(default="gpt-4o", description="Modèle à utiliser")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, description="Limite de tokens")
    api_key: str | None = Field(default=None, description="Clé API (ou env:VAR_NAME)")
    base_url: str | None = Field(default=None, description="URL de l'API")
    is_leader: bool = Field(default=False, description="Cet agent est le leader/modérateur")
    extra: dict[str, Any] = Field(default_factory=dict, description="Paramètres additionnels")

    def resolve_api_key(self, global_keys: APIKeysConfig | None = None) -> str | None:
        """Résout la clef API (locale ou globale)."""
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
    """Configuration du débat."""
    rounds: int = Field(default=2, ge=1, le=10, description="Nombre de tours de confrontation")
    initial_prompt: str = Field(..., description="Question/prompt initial")
    system_prompt: str | None = Field(
        default=None,
        description="System prompt optionnel pour tous les agents"
    )
    leader_prompt: str | None = Field(
        default=None,
        description="Prompt additionnel pour le leader (instructions de modération)"
    )


class MeetingConfig(BaseModel):
    """Configuration complète de la réunion."""
    agents: list[AgentConfig] = Field(..., description="Liste des agents")
    debate: DebateConfig = Field(..., description="Configuration du débat")
    title: str | None = Field(default=None, description="Titre de la réunion")
    api_keys: APIKeysConfig | None = Field(default=None, description="Clefs API globales")
