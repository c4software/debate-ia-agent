"""Main entry point."""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

import yaml

from src.config import MeetingConfig
from src.tui import AgentsMeetingApp


def load_config(path: str | Path) -> MeetingConfig:
    """Load configuration from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    return MeetingConfig(**data)



async def run_cli(config: MeetingConfig) -> None:
    """Run the debate in CLI mode with real-time display."""
    from src.agents import DebateManager, DebateEvent
    
    print(f"\n{'='*60}")
    print(f"  {config.title or 'Multi-Agent Debate'}")
    print(f"{'='*60}")
    print(f"\nQuestion: {config.debate.initial_prompt}\n")
    
    def on_event(event: DebateEvent):
        if event.type == "phase_start":
            print(f"\n[{'='*40}]")
            print(f"  Phase: {event.phase.upper()}")
            print(f"[{'='*40}]")
        elif event.type == "leader_thinking":
            print(f"\n  💭 {event.agent_name} is thinking...")
        elif event.type == "agent_thinking":
            print(f"\n  💭 {event.agent_name} is thinking...")
        elif event.type == "leader_speak" and event.content:
            print(f"\n🎤 {event.agent_name}:")
            print(f"   {event.content[:500]}")
        elif event.type == "leader_intervention" and event.content:
            print(f"\n🔧 MODERATOR INTERVENTION:")
            print(f"   {event.content[:500]}")
        elif event.type == "agent_speak" and event.content:
            print(f"\n💬 {event.agent_name}:")
            print(f"   {event.content[:500]}")
        elif event.type == "agent_streaming" and event.content:
            print(event.content, end="", flush=True)
        elif event.type == "end":
            print(f"\n{'='*60}")
            print(f"  ✅ Debate ended!")
            print(f"{'='*60}\n")
    
    manager = DebateManager(config, on_event=on_event)
    await manager.initialize()
    await manager.run()
    await manager.cleanup()

    # Offer to save
    if config.output:
        path = manager.save(config.output)
        print(f"\nConversation saved: {path}")
    else:
        default = datetime.now().strftime("debate_%Y-%m-%d_%H-%M.md")
        try:
            answer = input(f"\nSave file name [{default}] : ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer == "":
            answer = default
        if not answer.endswith(".md"):
            answer += ".md"
        path = manager.save(answer)
        print(f"Conversation saved: {path}")


async def run_tui(config: MeetingConfig) -> None:
    """Launch the TUI application."""
    app = AgentsMeetingApp(config)
    await app.run_async()


def main() -> None:
    parser = argparse.ArgumentParser(description="Agents Meeting - Multi-agent debate system")
    parser.add_argument(
        "config",
        nargs="?",
        help="Path to the YAML configuration file",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        help="Prompt/direct question for the debate (replaces config)",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="CLI mode (without TUI)",
    )
    
    args = parser.parse_args()

    if args.config:
        config = load_config(args.config)
    else:
        print("Error: Provide a config file.")
        sys.exit(1)

    if args.prompt:
        config.debate.initial_prompt = args.prompt

    if args.cli:
        asyncio.run(run_cli(config))
    else:
        asyncio.run(run_tui(config))


if __name__ == "__main__":
    main()
