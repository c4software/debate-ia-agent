"""Multi-agent debate system with leader."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from src.agents.agent import Agent, Turn
from src.config import DebateConfig, MeetingConfig


@dataclass
class DebateEvent:
    """Event in the debate."""
    type: str
    round: int
    phase: str
    agent_name: str | None
    content: str | None
    timestamp: float = 0.0
    is_streaming: bool = False


class DebateManager:
    """Manages the debate flow between agents."""

    def __init__(
        self,
        config: MeetingConfig,
        on_event: Callable[[DebateEvent], None] | None = None,
    ):
        self.config = config
        self.agents: list[Agent] = []
        self.leader: Agent | None = None
        self.events: list[DebateEvent] = []
        self.on_event = on_event
        self._current_round = 0
        self._current_phase = ""
        self._leader_last_content: str = ""
        self._cancelled: bool = False

    def cancel(self) -> None:
        """Request to stop the debate."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    async def initialize(self) -> None:
        """Initialize the agents."""
        for agent_config in self.config.agents:
            agent = Agent(config=agent_config, global_api_keys=self.config.api_keys)
            if agent_config.is_leader:
                self.leader = agent
            self.agents.append(agent)

        if not self.leader and self.agents:
            self.leader = self.agents[0]

    async def run(self) -> dict[str, list[Turn]]:
        """Execute the complete debate."""
        self._emit("start", 0, "init", None, None)

        # 1. The moderator opens the debate
        await self._phase_intro()
        if self._cancelled:
            return {agent.config.name: agent.turns for agent in self.agents}

        # 2. Discussion loop
        for round_num in range(1, self.config.debate.rounds + 1):
            self._current_round = round_num
            # Agents respond based on the moderator's last intervention
            await self._phase_discussion(round_num)
            if self._cancelled:
                return {agent.config.name: agent.turns for agent in self.agents}
            # The moderator synthesizes (including in the last round, before conclusion)
            await self._leader_intervention(round_num)
            if self._cancelled:
                return {agent.config.name: agent.turns for agent in self.agents}

        # 3. Final synthesis
        await self._phase_conclusion()

        self._emit("end", 0, "end", None, None)

        # 4. The leader proposes a continuation question
        await self._generate_continuation_question()

        result = {agent.config.name: agent.turns for agent in self.agents}
        return result

    async def _phase_intro(self) -> None:
        """Introduction phase: the moderator presents the topic and frames the debate."""
        self._current_phase = "intro"
        self._emit("phase_start", 0, "intro", None, None)

        if not self.leader:
            return

        prompt = self.config.debate.intro_prompt.format(
            initial_prompt=self.config.debate.initial_prompt,
        )

        self._emit("leader_section_start", 0, "intro", self.leader.config.name, "## Debate Opening")
        self._emit("leader_thinking", 0, "intro", self.leader.config.name, None)

        full_content = await self._stream_leader(prompt, 0, "intro")

        turn = Turn(round=0, phase="intro", content=full_content)
        self.leader.turns.append(turn)
        self._emit("leader_speak", 0, "intro", self.leader.config.name, full_content)

        # Store for agents to use in round 1
        self._leader_last_content = full_content

    async def _phase_discussion(self, round_num: int) -> None:
        """Discussion phase: agents respond in parallel."""
        self._current_phase = f"discussion_{round_num}"
        self._emit("phase_start", round_num, "discussion", None, None)

        # Common context for all agents: last moderator synthesis/intro
        moderator_context = (
            self.config.debate.moderator_context_prefix.format(content=self._leader_last_content)
            if self._leader_last_content else None
        )

        async def get_agent_response(agent: Agent) -> tuple[str, str]:
            if agent == self.leader:
                return agent.config.name, ""

            self._emit("agent_thinking", round_num, "discussion", agent.config.name, None)

            full_content = ""
            try:
                async for chunk in agent.think_stream(
                    self.config.debate.initial_prompt,
                    context=moderator_context,
                    system_prompt=self.config.debate.system_prompt,
                    identity_template=self.config.debate.agent_identity_template,
                    context_template=self.config.debate.agent_context_template,
                ):
                    if self._cancelled:
                        break
                    full_content += chunk
                    self._emit("agent_streaming", round_num, "discussion", agent.config.name, chunk, is_streaming=True)
            except Exception as e:
                full_content = f"[Error: {e}]"

            turn = Turn(round=round_num, phase="discussion", content=full_content)
            agent.turns.append(turn)
            self._emit("agent_speak", round_num, "discussion", agent.config.name, full_content)

            return agent.config.name, full_content

        results = await asyncio.gather(*[
            get_agent_response(agent) for agent in self.agents
        ])

        # Store responses for moderator intervention
        self._last_round_responses = {
            name: content for name, content in results if name and content
        }

    async def _leader_intervention(self, round_num: int) -> None:
        """The moderator synthesizes responses and asks a refined question."""
        if not self.leader:
            return

        responses = getattr(self, "_last_round_responses", {})

        context_parts = [
            self.config.debate.round_header_template.format(round_num=round_num)
        ]
        for name, content in responses.items():
            context_parts.append(f"\n### {name}\n{content}")

        is_last = round_num >= self.config.debate.rounds
        if is_last:
            instruction = self.config.debate.intervention_last_prompt
        else:
            instruction = self.config.debate.intervention_prompt

        prompt = (
            f"Original question: {self.config.debate.initial_prompt}\n\n"
            + "\n".join(context_parts) + "\n\n"
            + instruction
        )

        self._emit("leader_section_start", round_num, "leader_intervention",
                   self.leader.config.name, f"## Round {round_num}")
        self._emit("leader_thinking", round_num, "leader_intervention", self.leader.config.name, None)

        full_content = await self._stream_leader(prompt, round_num, "leader_intervention")

        turn = Turn(round=round_num, phase="leader_intervention", content=full_content)
        self.leader.turns.append(turn)
        self._emit("leader_speak", round_num, "leader_intervention", self.leader.config.name, full_content)

        # Update context for agents in the next round
        self._leader_last_content = full_content

    async def _generate_continuation_question(self) -> None:
        """The leader proposes a follow-up question to continue the debate."""
        if not self.leader:
            return

        # Get the final synthesis
        conclusion_turns = [t for t in self.leader.turns if t.phase == "conclusion"]
        conclusion_text = conclusion_turns[-1].content if conclusion_turns else ""

        prompt = self.config.debate.continuation_prompt.format(
            initial_prompt=self.config.debate.initial_prompt,
            conclusion_text=conclusion_text,
        )

        self._emit("continuation_thinking", 0, "end", self.leader.config.name, None)

        try:
            from src.providers import Message
            response = await self.leader.provider.chat(
                messages=[Message(role="user", content=prompt)],
                system_prompt=self.leader.build_system_prompt(
                    self.config.debate.system_prompt,
                    identity_template=self.config.debate.agent_identity_template,
                ),
            )
            question = response.content.strip()
        except Exception:
            question = ""

        self._emit("continuation_suggestion", 0, "end", self.leader.config.name, question)

    def add_round(self) -> None:
        """Add one extra round to the debate, continuing with the same question and context.

        - All agents retain their LLM history and turns.
        - The leader's final synthesis is injected as the starting context for the new round.
        - The debate round counter is incremented by 1.
        """
        # Inject the final synthesis as starting context for the new round
        conclusion_turns = [t for t in self.leader.turns if t.phase == "conclusion"] if self.leader else []
        conclusion_text = conclusion_turns[-1].content if conclusion_turns else self._leader_last_content

        if conclusion_text:
            context_label = self.config.debate.previous_context_label.format(
                initial_prompt=self.config.debate.initial_prompt,
            )
            self._leader_last_content = f"{context_label}\n{conclusion_text}"

        # Add one extra round
        self.config.debate.rounds += 1

        # Reset internal manager state without touching agent histories
        self._cancelled = False
        self._current_phase = ""

    def continue_with(self, new_prompt: str) -> None:
        """Prepare a continuation of the debate with a new question.

        - The leader retains their LLM history and turns (cumulative memory).
        - Non-leader agents start fresh.
        - The leader's final synthesis is injected as starting context.
        """
        # Get the final synthesis before resetting everything
        conclusion_turns = [t for t in self.leader.turns if t.phase == "conclusion"] if self.leader else []
        conclusion_text = conclusion_turns[-1].content if conclusion_turns else ""

        # Reset non-leader agents
        for agent in self.agents:
            if agent != self.leader:
                agent.history.clear()
                agent.turns.clear()

        # Inject final synthesis into leader's LLM history
        if conclusion_text and self.leader:
            from src.providers import Message as Msg
            label = self.config.debate.previous_debate_label.format(
                initial_prompt=self.config.debate.initial_prompt,
            )
            self.leader.history.append(Msg(
                role="assistant",
                content=f"{label}\n{conclusion_text}",
            ))

        # Update the prompt
        self.config.debate.initial_prompt = new_prompt

        # Inject synthesis as starting context for agents
        if conclusion_text:
            context_label = self.config.debate.previous_context_label.format(
                initial_prompt=self.config.debate.initial_prompt,
            )
            self._leader_last_content = f"{context_label}\n{conclusion_text}"
        else:
            self._leader_last_content = ""

        # Reset internal manager state
        self._cancelled = False
        self._current_round = 0
        self._current_phase = ""
        self._last_round_responses: dict[str, str] = {}

    async def _phase_conclusion(self) -> None:
        """Conclusion phase: the moderator provides the final synthesis."""
        self._current_phase = "conclusion"
        self._emit("phase_start", self._current_round, "conclusion", None, None)

        if not self.leader:
            return

        # Gather all agent history
        all_turns_parts = []
        for agent in self.agents:
            if agent == self.leader:
                continue
            agent_turns = [t for t in agent.turns if t.phase == "discussion"]
            if agent_turns:
                all_turns_parts.append(f"### {agent.config.name}")
                for t in agent_turns:
                    all_turns_parts.append(f"*Round {t.round}:* {t.content}")

        prompt = self.config.debate.conclusion_prompt.format(
            initial_prompt=self.config.debate.initial_prompt,
            turns="\n\n".join(all_turns_parts),
        )

        self._emit("leader_section_start", self._current_round, "conclusion",
                   self.leader.config.name, "## Final Synthesis")
        self._emit("leader_thinking", self._current_round, "conclusion", self.leader.config.name, None)

        full_content = await self._stream_leader(prompt, self._current_round, "conclusion")

        turn = Turn(round=self._current_round, phase="conclusion", content=full_content)
        self.leader.turns.append(turn)
        self._emit("leader_speak", self._current_round, "conclusion", self.leader.config.name, full_content)

    async def _stream_leader(self, prompt: str, round_num: int, phase: str) -> str:
        """Stream the leader's response and emit chunks."""
        if not self.leader:
            return ""
        full_content = ""
        try:
            async for chunk in self.leader.think_stream(
                prompt,
                system_prompt=self.config.debate.system_prompt,
                leader_prompt=self.config.debate.leader_prompt,
                identity_template=self.config.debate.agent_identity_template,
            ):
                if self._cancelled:
                    break
                full_content += chunk
                self._emit("leader_streaming", round_num, phase,
                           self.leader.config.name, chunk, is_streaming=True)
        except Exception as e:
            full_content = f"[Error: {e}]"
        return full_content

    def _emit(
        self,
        event_type: str,
        round_num: int,
        phase: str,
        agent_name: str | None,
        content: str | None,
        is_streaming: bool = False,
    ) -> None:
        event = DebateEvent(
            type=event_type,
            round=round_num,
            phase=phase,
            agent_name=agent_name,
            content=content,
            is_streaming=is_streaming,
        )
        self.events.append(event)
        if self.on_event:
            self.on_event(event)

    def save(self, path: str | None = None) -> str:
        """Save the debate to Markdown. Returns the effective path."""
        if path is None:
            path = datetime.now().strftime("debate_%Y-%m-%d_%H-%M.md")
        content = self._build_markdown()
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _build_markdown(self) -> str:
        """Build the Markdown document of the debate from recorded turns."""
        lines: list[str] = []

        title = self.config.title or "Agents Meeting"
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"> {self.config.debate.initial_prompt}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Leader section
        if self.leader:
            model_info = f"{self.leader.config.provider} / {self.leader.config.model}"
            lines.append(f"## {self.leader.config.name} ({model_info})")
            lines.append("")
            phase_labels = {
                "intro": "Debate Opening",
                "conclusion": "Final Synthesis",
            }
            for turn in self.leader.turns:
                label = phase_labels.get(turn.phase)
                if label is None:
                    # leader_intervention for round N
                    label = f"Round {turn.round}"
                lines.append(f"### {label}")
                lines.append("")
                lines.append(turn.content)
                lines.append("")

            lines.append("---")
            lines.append("")

        # Agents section
        non_leaders = [a for a in self.agents if a != self.leader]
        if non_leaders:
            lines.append("## Agents")
            lines.append("")
            for agent in non_leaders:
                model_info = f"{agent.config.provider} / {agent.config.model}"
                lines.append(f"### {agent.config.name} ({model_info})")
                if agent.config.role:
                    lines.append(f"*{agent.config.role}*")
                lines.append("")
                for turn in agent.turns:
                    if turn.phase == "discussion":
                        lines.append(f"**Round {turn.round}**")
                        lines.append("")
                        lines.append(turn.content)
                        lines.append("")

        return "\n".join(lines)

    async def cleanup(self) -> None:
        """Clean up resources."""
        for agent in self.agents:
            await agent.close()
