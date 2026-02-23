"""Système de débat multi-agents avec leader."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from src.agents.agent import Agent, Turn
from src.config import DebateConfig, MeetingConfig


@dataclass
class DebateEvent:
    """Événement dans le débat."""
    type: str
    round: int
    phase: str
    agent_name: str | None
    content: str | None
    timestamp: float = 0.0
    is_streaming: bool = False


class DebateManager:
    """Gère le déroulement du débat entre agents."""

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
        """Demande l'arrêt du débat."""
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    async def initialize(self) -> None:
        """Initialise les agents."""
        for agent_config in self.config.agents:
            agent = Agent(config=agent_config, global_api_keys=self.config.api_keys)
            if agent_config.is_leader:
                self.leader = agent
            self.agents.append(agent)

        if not self.leader and self.agents:
            self.leader = self.agents[0]

    async def run(self) -> dict[str, list[Turn]]:
        """Exécute le débat complet."""
        self._emit("start", 0, "init", None, None)

        # 1. Le modérateur ouvre le débat
        await self._phase_intro()
        if self._cancelled:
            return {agent.config.name: agent.turns for agent in self.agents}

        # 2. Boucle de discussion
        for round_num in range(1, self.config.debate.rounds + 1):
            self._current_round = round_num
            # Les agents répondent en se basant sur la dernière intervention du modérateur
            await self._phase_discussion(round_num)
            if self._cancelled:
                return {agent.config.name: agent.turns for agent in self.agents}
            # Le modérateur synthétise (y compris au dernier tour, avant la conclusion)
            await self._leader_intervention(round_num)
            if self._cancelled:
                return {agent.config.name: agent.turns for agent in self.agents}

        # 3. Synthèse finale
        await self._phase_conclusion()

        self._emit("end", 0, "end", None, None)

        # 4. Le leader propose une question de continuation
        await self._generate_continuation_question()

        result = {agent.config.name: agent.turns for agent in self.agents}
        return result

    async def _phase_intro(self) -> None:
        """Phase d'introduction : le modérateur pose le sujet et cadre le débat."""
        self._current_phase = "intro"
        self._emit("phase_start", 0, "intro", None, None)

        if not self.leader:
            return

        prompt = (
            f"Tu es le modérateur d'un débat. "
            f"Présente le sujet suivant de manière claire, cadre les enjeux "
            f"et pose les questions initiales auxquelles les participants devront répondre:\n\n"
            f"SUJET: {self.config.debate.initial_prompt}"
        )
        if self.config.debate.leader_prompt:
            prompt += f"\n\n{self.config.debate.leader_prompt}"

        self._emit("leader_section_start", 0, "intro", self.leader.config.name, "## Ouverture du débat")
        self._emit("leader_thinking", 0, "intro", self.leader.config.name, None)

        full_content = await self._stream_leader(prompt, 0, "intro")

        turn = Turn(round=0, phase="intro", content=full_content)
        self.leader.turns.append(turn)
        self._emit("leader_speak", 0, "intro", self.leader.config.name, full_content)

        # Stocker pour que les agents en disposent au tour 1
        self._leader_last_content = full_content

    async def _phase_discussion(self, round_num: int) -> None:
        """Phase de discussion : les agents répondent en parallèle."""
        self._current_phase = f"discussion_{round_num}"
        self._emit("phase_start", round_num, "discussion", None, None)

        # Contexte commun à tous les agents : dernière synthèse/intro du modérateur
        moderator_context = (
            f"Le modérateur a dit:\n{self._leader_last_content}"
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
                ):
                    if self._cancelled:
                        break
                    full_content += chunk
                    self._emit("agent_streaming", round_num, "discussion", agent.config.name, chunk, is_streaming=True)
            except Exception as e:
                full_content = f"[Erreur: {e}]"

            turn = Turn(round=round_num, phase="discussion", content=full_content)
            agent.turns.append(turn)
            self._emit("agent_speak", round_num, "discussion", agent.config.name, full_content)

            return agent.config.name, full_content

        results = await asyncio.gather(*[
            get_agent_response(agent) for agent in self.agents
        ])

        # Stocker les réponses pour l'intervention du modérateur
        self._last_round_responses = {
            name: content for name, content in results if name and content
        }

    async def _leader_intervention(self, round_num: int) -> None:
        """Le modérateur synthétise les réponses et pose une question affinée."""
        if not self.leader:
            return

        responses = getattr(self, "_last_round_responses", {})

        context_parts = [f"Tour {round_num} — Réponses des participants:"]
        for name, content in responses.items():
            context_parts.append(f"\n### {name}\n{content}")

        is_last = round_num >= self.config.debate.rounds
        if is_last:
            instruction = (
                f"En tant que modérateur, fais une synthèse complète des positions "
                f"exprimées ce tour. Identifie les points de convergence et de divergence."
            )
        else:
            instruction = (
                f"En tant que modérateur, fais une synthèse des positions exprimées ce tour, "
                f"identifie les points de convergence et de divergence, "
                f"puis pose une question affinée pour approfondir le débat au prochain tour."
            )

        prompt = (
            f"Question originale: {self.config.debate.initial_prompt}\n\n"
            + "\n".join(context_parts) + "\n\n"
            + instruction
        )
        if self.config.debate.leader_prompt:
            prompt += f"\n\n{self.config.debate.leader_prompt}"

        self._emit("leader_section_start", round_num, "leader_intervention",
                   self.leader.config.name, f"## Tour {round_num}")
        self._emit("leader_thinking", round_num, "leader_intervention", self.leader.config.name, None)

        full_content = await self._stream_leader(prompt, round_num, "leader_intervention")

        turn = Turn(round=round_num, phase="leader_intervention", content=full_content)
        self.leader.turns.append(turn)
        self._emit("leader_speak", round_num, "leader_intervention", self.leader.config.name, full_content)

        # Mettre à jour le contexte pour les agents du prochain tour
        self._leader_last_content = full_content

    async def _generate_continuation_question(self) -> None:
        """Le leader propose une question de suivi pour continuer le débat."""
        if not self.leader:
            return

        # Récupérer la synthèse finale
        conclusion_turns = [t for t in self.leader.turns if t.phase == "conclusion"]
        conclusion_text = conclusion_turns[-1].content if conclusion_turns else ""

        prompt = (
            f"Tu viens de modérer un débat sur le sujet : « {self.config.debate.initial_prompt} ».\n\n"
            f"Voici ta synthèse finale :\n{conclusion_text}\n\n"
            f"Propose une seule question de suivi courte et précise qui permettrait d'approfondir "
            f"ou d'élargir le débat. Réponds uniquement avec la question, sans introduction ni explication."
        )

        self._emit("continuation_thinking", 0, "end", self.leader.config.name, None)

        try:
            from src.providers import Message
            response = await self.leader.provider.chat(
                messages=[Message(role="user", content=prompt)],
                system_prompt=self.leader.build_system_prompt(self.config.debate.system_prompt),
            )
            question = response.content.strip()
        except Exception:
            question = ""

        self._emit("continuation_suggestion", 0, "end", self.leader.config.name, question)

    def continue_with(self, new_prompt: str) -> None:
        """Prépare une continuation du débat avec une nouvelle question.

        - Le leader conserve son historique LLM et ses turns (mémoire cumulative).
        - Les agents non-leader repartent à zéro.
        - La synthèse finale du leader est injectée comme contexte de départ.
        """
        # Récupérer la synthèse finale avant de tout réinitialiser
        conclusion_turns = [t for t in self.leader.turns if t.phase == "conclusion"] if self.leader else []
        conclusion_text = conclusion_turns[-1].content if conclusion_turns else ""

        # Reset des agents non-leader
        for agent in self.agents:
            if agent != self.leader:
                agent.history.clear()
                agent.turns.clear()

        # Injecter la synthèse finale dans l'historique LLM du leader
        if conclusion_text and self.leader:
            from src.providers import Message as Msg
            self.leader.history.append(Msg(
                role="assistant",
                content=f"[Synthèse du débat précédent sur « {self.config.debate.initial_prompt} »]\n{conclusion_text}",
            ))

        # Mise à jour du prompt
        self.config.debate.initial_prompt = new_prompt

        # Injecter la synthèse comme contexte de départ pour les agents
        if conclusion_text:
            self._leader_last_content = (
                f"[Contexte — débat précédent sur « {self.config.debate.initial_prompt} »]\n"
                f"{conclusion_text}"
            )
        else:
            self._leader_last_content = ""

        # Réinitialiser l'état interne du manager
        self._cancelled = False
        self._current_round = 0
        self._current_phase = ""
        self._last_round_responses: dict[str, str] = {}

    async def _phase_conclusion(self) -> None:
        """Phase de conclusion : le modérateur fait la synthèse finale."""
        self._current_phase = "conclusion"
        self._emit("phase_start", self._current_round, "conclusion", None, None)

        if not self.leader:
            return

        # Rassembler tout l'historique des agents
        all_turns_parts = []
        for agent in self.agents:
            if agent == self.leader:
                continue
            agent_turns = [t for t in agent.turns if t.phase == "discussion"]
            if agent_turns:
                all_turns_parts.append(f"### {agent.config.name}")
                for t in agent_turns:
                    all_turns_parts.append(f"*Tour {t.round}:* {t.content}")

        prompt = (
            f"Question originale: {self.config.debate.initial_prompt}\n\n"
            f"Voici l'ensemble des interventions des participants sur tous les tours:\n\n"
            + "\n\n".join(all_turns_parts) + "\n\n"
            f"En tant que modérateur, fais une synthèse finale équilibrée du débat : "
            f"résume les grandes positions, les points d'accord et de désaccord, "
            f"et propose une conclusion générale."
        )
        if self.config.debate.leader_prompt:
            prompt += f"\n\n{self.config.debate.leader_prompt}"

        self._emit("leader_section_start", self._current_round, "conclusion",
                   self.leader.config.name, "## Synthese finale")
        self._emit("leader_thinking", self._current_round, "conclusion", self.leader.config.name, None)

        full_content = await self._stream_leader(prompt, self._current_round, "conclusion")

        turn = Turn(round=self._current_round, phase="conclusion", content=full_content)
        self.leader.turns.append(turn)
        self._emit("leader_speak", self._current_round, "conclusion", self.leader.config.name, full_content)

    async def _stream_leader(self, prompt: str, round_num: int, phase: str) -> str:
        """Stream la réponse du leader et émet les chunks."""
        if not self.leader:
            return ""
        full_content = ""
        try:
            async for chunk in self.leader.think_stream(
                prompt,
                system_prompt=self.config.debate.system_prompt,
            ):
                if self._cancelled:
                    break
                full_content += chunk
                self._emit("leader_streaming", round_num, phase,
                           self.leader.config.name, chunk, is_streaming=True)
        except Exception as e:
            full_content = f"[Erreur: {e}]"
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
        """Sauvegarde le débat en Markdown. Retourne le chemin effectif."""
        if path is None:
            path = datetime.now().strftime("debate_%Y-%m-%d_%H-%M.md")
        content = self._build_markdown()
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _build_markdown(self) -> str:
        """Construit le document Markdown du débat depuis les turns enregistrés."""
        lines: list[str] = []

        title = self.config.title or "Agents Meeting"
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"> {self.config.debate.initial_prompt}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Section leader
        if self.leader:
            model_info = f"{self.leader.config.provider} / {self.leader.config.model}"
            lines.append(f"## {self.leader.config.name} ({model_info})")
            lines.append("")
            phase_labels = {
                "intro": "Ouverture du débat",
                "conclusion": "Synthèse finale",
            }
            for turn in self.leader.turns:
                label = phase_labels.get(turn.phase)
                if label is None:
                    # leader_intervention pour tour N
                    label = f"Tour {turn.round}"
                lines.append(f"### {label}")
                lines.append("")
                lines.append(turn.content)
                lines.append("")

            lines.append("---")
            lines.append("")

        # Section agents
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
                        lines.append(f"**Tour {turn.round}**")
                        lines.append("")
                        lines.append(turn.content)
                        lines.append("")

        return "\n".join(lines)

    async def cleanup(self) -> None:
        """Nettoie les ressources."""
        for agent in self.agents:
            await agent.close()
