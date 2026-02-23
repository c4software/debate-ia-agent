"""Point d'entrée principal."""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

import yaml

from src.config import MeetingConfig
from src.tui import AgentsMeetingApp


def load_config(path: str | Path) -> MeetingConfig:
    """Charge la configuration depuis un fichier YAML."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return MeetingConfig(**data)


def create_sample_config() -> str:
    """Génère un fichier de configuration d'exemple."""
    return """title: "Discussion: L'IA va-t-elle transformer le travail ?"

api_keys:
  openai: "env:OPENAI_API_KEY"
  anthropic: "env:ANTHROPIC_API_KEY"
  custom: "env:CUSTOM_API_KEY"

agents:
  - name: "Modérateur"
    role: "Anime le débat, synthétise et pose des questions de suivi"
    provider: "openai"
    model: "gpt-4o"
    temperature: 0.5
    is_leader: true

  - name: "Sceptique"
    role: "Remet en question les bénéfices de l'IA et souligne les risques"
    provider: "openai"
    model: "gpt-4o"
    temperature: 0.8
    is_leader: false

  - name: "Pragmatique"
    role: "Analyse les aspects pratiques et les contraintes réelles"
    provider: "anthropic"
    model: "claude-3-5-sonnet-20241022"
    temperature: 0.5
    is_leader: false

  - name: "Optimiste"
    role: "Voit les opportunités et le potentiel de l'IA"
    provider: "anthropic"
    model: "claude-3-5-sonnet-20241022"
    temperature: 0.9
    is_leader: false

debate:
  rounds: 2
  initial_prompt: "Comment l'intelligence artificielle va-t-elle transformer le monde du travail dans les 10 prochaines années ?"
  system_prompt: "Tu participes à un débat structuré. Sois concis et argumenté."
  leader_prompt: "En tant que modérateur, assure-toi que tous les points de vue sont exprimés et synthétise régulièrement."
"""


async def run_cli(config: MeetingConfig) -> None:
    """Lance le débat en mode CLI avec affichage temps réel."""
    from src.agents import DebateManager, DebateEvent
    
    print(f"\n{'='*60}")
    print(f"  {config.title or 'Débat Multi-Agents'}")
    print(f"{'='*60}")
    print(f"\nQuestion: {config.debate.initial_prompt}\n")
    
    def on_event(event: DebateEvent):
        if event.type == "phase_start":
            print(f"\n[{'='*40}]")
            print(f"  Phase: {event.phase.upper()}")
            print(f"[{'='*40}]")
        elif event.type == "leader_thinking":
            print(f"\n  💭 {event.agent_name} réfléchit...")
        elif event.type == "agent_thinking":
            print(f"\n  💭 {event.agent_name} réfléchit...")
        elif event.type == "leader_speak" and event.content:
            print(f"\n🎤 {event.agent_name}:")
            print(f"   {event.content[:500]}")
        elif event.type == "leader_intervention" and event.content:
            print(f"\n🔧 INTERVENTION DU MODÉRATEUR:")
            print(f"   {event.content[:500]}")
        elif event.type == "agent_speak" and event.content:
            print(f"\n💬 {event.agent_name}:")
            print(f"   {event.content[:500]}")
        elif event.type == "agent_streaming" and event.content:
            print(event.content, end="", flush=True)
        elif event.type == "end":
            print(f"\n{'='*60}")
            print(f"  ✅ Débat terminé!")
            print(f"{'='*60}\n")
    
    manager = DebateManager(config, on_event=on_event)
    await manager.initialize()
    await manager.run()
    await manager.cleanup()

    # Proposer la sauvegarde
    if config.output:
        path = manager.save(config.output)
        print(f"\nConversation sauvegardée : {path}")
    else:
        default = datetime.now().strftime("debate_%Y-%m-%d_%H-%M.md")
        try:
            answer = input(f"\nNom du fichier de sauvegarde [{default}] : ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer == "":
            answer = default
        if not answer.endswith(".md"):
            answer += ".md"
        path = manager.save(answer)
        print(f"Conversation sauvegardée : {path}")


async def run_tui(config: MeetingConfig) -> None:
    """Lance l'application TUI."""
    app = AgentsMeetingApp(config)
    await app.run_async()


def main() -> None:
    parser = argparse.ArgumentParser(description="Agents Meeting - Système de débat multi-agents")
    parser.add_argument(
        "config",
        nargs="?",
        help="Chemin vers le fichier de configuration YAML",
    )
    parser.add_argument(
        "--create-config",
        action="store_true",
        help="Crée un fichier de configuration d'exemple",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        help="Prompt/direct question pour le débat (remplace la config)",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Mode CLI (sans interface TUI)",
    )
    
    args = parser.parse_args()

    if args.create_config:
        config_path = Path("agents-meeting.yaml")
        if config_path.exists():
            print(f"Erreur: {config_path} existe déjà")
            sys.exit(1)
        with open(config_path, "w") as f:
            f.write(create_sample_config())
        print(f"Config créée: {config_path}")
        sys.exit(0)

    if args.config:
        config = load_config(args.config)
    else:
        print("Erreur: Fournissez un fichier de config ou utilisez --create-config")
        sys.exit(1)

    if args.prompt:
        config.debate.initial_prompt = args.prompt

    if args.cli:
        asyncio.run(run_cli(config))
    else:
        asyncio.run(run_tui(config))


if __name__ == "__main__":
    main()
