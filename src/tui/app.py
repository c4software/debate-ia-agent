"""Interface TUI pour agents-meeting."""

import time
from datetime import datetime
from textual.app import App, ComposeResult, ScreenStackError
from textual.containers import Vertical, ScrollableContainer, Horizontal, Center, Middle
from textual.widgets import Footer, Static, Button, Label, Markdown, Input
from textual.binding import Binding
from textual import work
from textual.message import Message
from textual.widget import Widget
from textual.screen import Screen
from textual.reactive import reactive
from src.agents import DebateManager, DebateEvent
from src.config import MeetingConfig


# ---------------------------------------------------------------------------
# Widget sélecteur de tours
# ---------------------------------------------------------------------------

class RoundPicker(Widget):
    """Ligne de chiffres 1–10 cliquables. Le chiffre actif est mis en évidence."""

    value: reactive[int] = reactive(2)

    DEFAULT_CSS = """
    RoundPicker {
        height: 1;
        width: auto;
        layout: horizontal;
    }

    RoundPicker .round-btn {
        width: 3;
        height: 1;
        background: transparent;
        color: $text-disabled;
        text-align: center;
        padding: 0;
    }

    RoundPicker .round-btn:hover {
        color: $text;
        background: $primary-darken-2;
    }

    RoundPicker .round-btn--active {
        color: $accent;
        text-style: bold;
        background: $accent 15%;
    }
    """

    def __init__(self, initial: int = 2, **kwargs):
        super().__init__(**kwargs)
        self.value = initial

    def compose(self) -> ComposeResult:
        for n in range(1, 11):
            classes = "round-btn round-btn--active" if n == self.value else "round-btn"
            yield Static(str(n), id=f"round-{n}", classes=classes)

    def watch_value(self, new_value: int) -> None:
        """Met à jour les classes CSS quand la valeur change."""
        for n in range(1, 11):
            try:
                btn = self.query_one(f"#round-{n}", Static)
                if n == new_value:
                    btn.add_class("round-btn--active")
                else:
                    btn.remove_class("round-btn--active")
            except Exception:
                pass

    def on_click(self, event) -> None:
        """Détecte le clic sur un chiffre."""
        # Remonter jusqu'au Static qui a l'id round-N
        widget = event.widget if hasattr(event, "widget") else None
        if widget is None:
            return
        widget_id = getattr(widget, "id", None) or ""
        if widget_id.startswith("round-"):
            try:
                self.value = int(widget_id.split("-")[1])
            except (ValueError, IndexError):
                pass


# ---------------------------------------------------------------------------
# Écran d'accueil centré (style OpenCode / Claude Code)
# ---------------------------------------------------------------------------

class WelcomeScreen(Screen):
    """Écran plein écran avec la question centrée, affiché au lancement."""

    BINDINGS = [
        Binding("enter", "start", "Démarrer", show=True),
        Binding("escape", "quit", "Quitter", show=True),
    ]

    CSS = """
    WelcomeScreen {
        background: $surface;
        align: center middle;
    }

    #welcome-box {
        width: 80;
        max-width: 90%;
        padding: 3 4;
        border: round $accent;
        background: $panel;
        height: auto;
    }

    #welcome-title {
        text-align: center;
        color: $accent;
        text-style: bold;
        margin-bottom: 2;
    }

    #welcome-subtitle {
        text-align: center;
        color: $text-muted;
        margin-bottom: 3;
    }

    #question-input {
        border: tall $accent;
        background: $surface;
        margin-bottom: 2;
    }

    #rounds-row {
        height: 1;
        margin-bottom: 2;
        align: left middle;
    }

    #rounds-label {
        width: auto;
        padding: 0 2 0 0;
        color: $text-muted;
    }

    #welcome-hint {
        text-align: center;
        color: $text-disabled;
        margin-top: 1;
    }

    #welcome-error {
        text-align: center;
        color: $error;
        height: 1;
    }
    """

    def __init__(self, config: MeetingConfig, **kwargs):
        super().__init__(**kwargs)
        self.config = config

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                with Vertical(id="welcome-box"):
                    yield Static(
                        self.config.title or "Agents Meeting",
                        id="welcome-title",
                    )
                    yield Static(
                        "Quelle question soumettre au débat ?",
                        id="welcome-subtitle",
                    )
                    yield Input(
                        value=self.config.debate.initial_prompt,
                        placeholder="Entrez la question du débat...",
                        id="question-input",
                    )
                    with Horizontal(id="rounds-row"):
                        yield Static("Tours :", id="rounds-label")
                        yield RoundPicker(
                            initial=self.config.debate.rounds,
                            id="rounds-picker",
                        )
                    yield Static("", id="welcome-error")
                    yield Static(
                        "[dim]Entrée pour démarrer · Échap pour quitter[/dim]",
                        id="welcome-hint",
                    )
        yield Footer()

    def on_mount(self) -> None:
        inp = self.query_one("#question-input", Input)
        inp.focus()
        inp.cursor_position = len(inp.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_start()

    def action_start(self) -> None:
        error = self.query_one("#welcome-error", Static)

        question = self.query_one("#question-input", Input).value.strip()
        if not question:
            error.update("[red]La question ne peut pas être vide.[/red]")
            self.query_one("#question-input", Input).focus()
            return

        rounds = self.query_one("#rounds-picker", RoundPicker).value

        error.update("")
        self.config.debate.initial_prompt = question
        self.config.debate.rounds = rounds
        self.app.switch_screen(DebateScreen(self.config))

    def action_quit(self) -> None:
        self.app.exit()


# ---------------------------------------------------------------------------
# AgentCard
# ---------------------------------------------------------------------------

class AgentCard(Widget):
    """Carte d'un agent avec sa réponse en Markdown."""

    can_focus = False

    def __init__(self, agent_name: str, agent_role: str = "", agent_model: str = "", is_leader: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.agent_name = agent_name
        self.agent_role = agent_role
        self.agent_model = agent_model
        self.is_leader = is_leader
        self._phase = ""
        self._current_content = ""
        self._dirty = False
        safe = "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "_" for c in agent_name)
        self._header_id = f"hdr_{safe}"
        self._body_id = f"bdy_{safe}"
        self._history_id = f"hist_{safe}"
        self._streaming_id = f"strm_{safe}"
        self._history_dirty = False
        self._history_content = ""
        self._streaming_content = ""
        self._streaming_dirty = False

    def compose(self) -> ComposeResult:
        role_line = f"\n[dim]{self.agent_role}[/dim]" if self.agent_role else ""
        model_line = f"\n[dim italic]{self.agent_model}[/dim italic]" if self.agent_model else ""
        yield Static(f"[bold]{self.agent_name}[/bold]{role_line}{model_line}", id=self._header_id)
        if self.is_leader:
            yield Markdown("", id=self._history_id)
            yield Markdown("", id=self._streaming_id)
        else:
            yield Markdown("", id=self._body_id)

    def _body(self) -> Markdown:
        return self.query_one(f"#{self._body_id}", Markdown)

    def flush_render(self) -> None:
        if self._dirty:
            self._body().update(self._current_content)
            self._dirty = False

    def flush_leader_render(self, history: str, history_dirty: bool, streaming: str) -> None:
        if history_dirty:
            self.query_one(f"#{self._history_id}", Markdown).update(history)
        if streaming != self._streaming_content:
            self._streaming_content = streaming
            self.query_one(f"#{self._streaming_id}", Markdown).update(streaming)

    def reset(self) -> None:
        self._current_content = ""
        self._phase = ""
        self._dirty = False
        self._body().update("")

    def set_thinking(self, phase: str) -> None:
        self._phase = phase
        self._current_content = ""
        self._dirty = False
        self._body().update("*Réfléchit...*")

    def set_content(self, phase: str, content: str) -> None:
        self._phase = phase
        self._current_content = content
        self._dirty = False
        self._body().update(content)

    def append_chunk(self, chunk: str) -> None:
        self._current_content += chunk
        self._dirty = True


# ---------------------------------------------------------------------------
# Écran de saisie du nom de fichier
# ---------------------------------------------------------------------------

class FilenameScreen(Screen):
    """Modale de saisie du nom de fichier pour la sauvegarde."""

    BINDINGS = [
        Binding("escape", "cancel", "Annuler", show=True),
    ]

    CSS = """
    FilenameScreen {
        background: $background 60%;
        align: center middle;
    }

    #filename-box {
        width: 60;
        max-width: 90%;
        padding: 2 3;
        border: round $accent;
        background: $panel;
        height: auto;
    }

    #filename-title {
        text-align: center;
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }

    #filename-input {
        border: tall $accent;
        background: $surface;
        margin-bottom: 1;
    }

    #filename-hint {
        text-align: center;
        color: $text-disabled;
    }

    #filename-error {
        text-align: center;
        color: $error;
        height: 1;
    }
    """

    def __init__(self, default_name: str = "", **kwargs):
        super().__init__(**kwargs)
        self._default_name = default_name

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                with Vertical(id="filename-box"):
                    yield Static("Nom du fichier de sauvegarde", id="filename-title")
                    yield Input(
                        value=self._default_name,
                        placeholder="nom-du-fichier.md",
                        id="filename-input",
                    )
                    yield Static("", id="filename-error")
                    yield Static(
                        "[dim]Entrée pour confirmer · Échap pour annuler[/dim]",
                        id="filename-hint",
                    )

    def on_mount(self) -> None:
        inp = self.query_one("#filename-input", Input)
        inp.focus()
        inp.cursor_position = len(inp.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._confirm()

    def _confirm(self) -> None:
        filename = self.query_one("#filename-input", Input).value.strip()
        if not filename:
            self.query_one("#filename-error", Static).update(
                "[red]Le nom de fichier ne peut pas être vide.[/red]"
            )
            return
        if not filename.endswith(".md"):
            filename += ".md"
        self.dismiss(filename)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Message bridge
# ---------------------------------------------------------------------------

class DebateEventMessage(Message):
    """Message Textual transportant un DebateEvent."""

    def __init__(self, event: DebateEvent):
        super().__init__()
        self.debate_event = event


# ---------------------------------------------------------------------------
# Écran de continuation du débat
# ---------------------------------------------------------------------------

class ContinueScreen(Screen):
    """Modale de saisie de la question de continuation proposée par le leader."""

    BINDINGS = [
        Binding("escape", "cancel", "Annuler", show=True),
    ]

    CSS = """
    ContinueScreen {
        background: $background 60%;
        align: center middle;
    }

    #continue-box {
        width: 70;
        max-width: 95%;
        padding: 2 3;
        border: round $accent;
        background: $panel;
        height: auto;
    }

    #continue-title {
        text-align: center;
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }

    #continue-subtitle {
        color: $text-muted;
        margin-bottom: 1;
    }

    #continue-input {
        border: tall $accent;
        background: $surface;
        margin-bottom: 1;
    }

    #continue-hint {
        text-align: center;
        color: $text-disabled;
    }

    #continue-error {
        text-align: center;
        color: $error;
        height: 1;
    }
    """

    def __init__(self, suggested_question: str = "", **kwargs):
        super().__init__(**kwargs)
        self._suggested = suggested_question

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                with Vertical(id="continue-box"):
                    yield Static("Continuer le débat", id="continue-title")
                    yield Static(
                        "[dim]Le modérateur suggère :[/dim]",
                        id="continue-subtitle",
                    )
                    yield Input(
                        value=self._suggested,
                        placeholder="Question pour continuer le débat...",
                        id="continue-input",
                    )
                    yield Static("", id="continue-error")
                    yield Static(
                        "[dim]Entrée pour confirmer · Échap pour annuler[/dim]",
                        id="continue-hint",
                    )

    def on_mount(self) -> None:
        inp = self.query_one("#continue-input", Input)
        inp.focus()
        inp.cursor_position = len(inp.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._confirm()

    def _confirm(self) -> None:
        question = self.query_one("#continue-input", Input).value.strip()
        if not question:
            self.query_one("#continue-error", Static).update(
                "[red]La question ne peut pas être vide.[/red]"
            )
            return
        self.dismiss(question)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Écran de débat
# ---------------------------------------------------------------------------

class DebateScreen(Screen):
    """Écran principal du débat — affiché après validation de la question."""

    BINDINGS = [
        Binding("escape", "stop_debate", "Arrêter", show=True, priority=True),
        Binding("c", "continue_debate", "Continuer", show=False),
    ]

    CSS = """
    DebateScreen {
        background: $surface;
    }

    #title {
        text-align: center;
        padding: 1;
        color: $accent;
    }

    #question-banner {
        padding: 0 2 1 2;
        color: $text-muted;
        text-wrap: wrap;
        max-height: 3;
        overflow-y: auto;
    }

    #agents_columns {
        height: 1fr;
    }

    #agents_col_left, #agents_col_right {
        width: 1fr;
    }

    AgentCard {
        border: round $primary-darken-2;
        padding: 1;
        margin: 0 0 1 0;
        height: auto;
        min-height: 6;
    }

    AgentCard Static {
        padding: 0 0 1 0;
        color: $text;
    }

    AgentCard Markdown {
        background: transparent;
        padding: 0;
        overflow-y: hidden;
    }

    #leader_scroll {
        height: 20;
        border: solid $accent;
        padding: 1;
    }

    #leader_scroll AgentCard {
        border: none;
        padding: 0;
        height: auto;
        overflow-y: hidden;
    }

    #status_bar {
        height: 3;
        align: center middle;
        background: $panel;
        padding: 0 1;
    }
    """

    def __init__(self, config: MeetingConfig, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.debate_manager: DebateManager | None = None
        self.agent_cards: dict[str, AgentCard] = {}
        self.leader_name: str | None = None
        self._current_round = 0
        self._total_rounds = config.debate.rounds
        self._leader_history: str = ""
        self._leader_streaming: str = ""
        self._leader_history_dirty: bool = False
        self._leader_flush_interval = None
        self._agent_container: dict[str, str] = {}
        self._scroll_pending: set[str] = set()
        self._user_scrolled_up: set[str] = set()
        # Chronomètre
        self._start_time: float | None = None
        self._debate_ended: bool = False
        self._current_phase_display: str = ""
        self._continuation_question: str = ""

    def compose(self) -> ComposeResult:
        yield Label(
            f"[bold cyan]{self.config.title or 'Agents Meeting'}[/bold cyan]",
            id="title",
        )
        yield Label(
            f"[dim]{self.config.debate.initial_prompt}[/dim]",
            id="question-banner",
        )

        non_leaders = [a for a in self.config.agents if not a.is_leader]
        left_agents = non_leaders[0::2]
        right_agents = non_leaders[1::2]

        with Horizontal(id="agents_columns"):
            with ScrollableContainer(id="agents_col_left"):
                for agent_config in left_agents:
                    safe_id = "card_" + "".join(
                        c if c.isascii() and (c.isalnum() or c in "-_") else "_"
                        for c in agent_config.name
                    )
                    model_str = f"{agent_config.provider} / {agent_config.model}"
                    card = AgentCard(agent_config.name, agent_config.role or "", model_str, id=safe_id)
                    self.agent_cards[agent_config.name] = card
                    self._agent_container[agent_config.name] = "#agents_col_left"
                    yield card

            with ScrollableContainer(id="agents_col_right"):
                for agent_config in right_agents:
                    safe_id = "card_" + "".join(
                        c if c.isascii() and (c.isalnum() or c in "-_") else "_"
                        for c in agent_config.name
                    )
                    model_str = f"{agent_config.provider} / {agent_config.model}"
                    card = AgentCard(agent_config.name, agent_config.role or "", model_str, id=safe_id)
                    self.agent_cards[agent_config.name] = card
                    self._agent_container[agent_config.name] = "#agents_col_right"
                    yield card

        with ScrollableContainer(id="leader_scroll"):
            for agent_config in self.config.agents:
                if agent_config.is_leader:
                    self.leader_name = agent_config.name
                    safe_id = "card_" + "".join(
                        c if c.isascii() and (c.isalnum() or c in "-_") else "_"
                        for c in agent_config.name
                    )
                    model_str = f"{agent_config.provider} / {agent_config.model}"
                    leader_card = AgentCard(
                        agent_config.name,
                        agent_config.role or "",
                        model_str,
                        is_leader=True,
                        id=safe_id,
                    )
                    self.agent_cards[agent_config.name] = leader_card
                    yield leader_card

        with Horizontal(id="status_bar"):
            yield Label("[yellow]Initialisation...[/yellow]", id="status")

        yield Footer()

    def on_mount(self) -> None:
        self._leader_flush_interval = self.set_interval(0.1, self._flush_tick)
        self.start_debate()

    async def on_unmount(self) -> None:
        """Nettoie le debate_manager si l'écran est quitté avant la fin."""
        if self.debate_manager is not None:
            try:
                await self.debate_manager.cleanup()
            except Exception:
                pass

    def on_mouse_scroll_up(self) -> None:
        self._update_scroll_flags()

    def on_mouse_scroll_down(self) -> None:
        self._update_scroll_flags()

    def _update_scroll_flags(self) -> None:
        container_ids = ["#agents_col_left", "#agents_col_right", "#leader_scroll"]
        for cid in container_ids:
            try:
                container = self.query_one(cid, ScrollableContainer)
                if container.scroll_y < container.max_scroll_y - 3:
                    self._user_scrolled_up.add(cid)
                else:
                    self._user_scrolled_up.discard(cid)
            except Exception:
                pass

    def _elapsed_str(self) -> str:
        if self._start_time is None:
            return ""
        elapsed = int(time.monotonic() - self._start_time)
        minutes, seconds = divmod(elapsed, 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _flush_tick(self) -> None:
        # Mettre à jour le chronomètre dans la status bar si le débat est en cours
        if self._start_time is not None and not self._debate_ended:
            try:
                status = self.query_one("#status", Label)
                elapsed = self._elapsed_str()
                round_info = f"Tour {self._current_round}/{self._total_rounds}" if self._current_round > 0 else "Intro"
                phase_display = self._current_phase_display
                status.update(f"[cyan]{round_info} · {phase_display} · {elapsed}[/cyan]")
            except Exception:
                pass

        # Flush agents non-leader
        for name, card in self.agent_cards.items():
            if name != self.leader_name:
                card.flush_render()

        # Flush leader
        if self.leader_name and self.leader_name in self.agent_cards:
            leader_card = self.agent_cards[self.leader_name]
            leader_card.flush_leader_render(
                history=self._leader_history,
                history_dirty=self._leader_history_dirty,
                streaming=self._leader_streaming,
            )
            self._leader_history_dirty = False

        # Flush scrolls
        for container_id in list(self._scroll_pending):
            if container_id not in self._user_scrolled_up:
                try:
                    container = self.query_one(container_id, ScrollableContainer)
                    container.call_after_refresh(container.scroll_end, animate=False)
                except Exception:
                    pass
        self._scroll_pending.clear()

    def _scroll_to_bottom(self, agent_name: str | None) -> None:
        if agent_name == self.leader_name:
            container_id = "#leader_scroll"
        else:
            container_id = self._agent_container.get(agent_name or "", "#agents_col_left")
        self._scroll_pending.add(container_id)

    def _update_leader_display(self) -> None:
        self._scroll_to_bottom(self.leader_name)

    def on_debate_event_message(self, message: DebateEventMessage) -> None:
        event = message.debate_event
        status = self.query_one("#status", Label)

        if event.type == "phase_start":
            self._current_round = event.round
            self._current_phase_display = event.phase.upper().replace("_", " ")

            if "discussion" in event.phase and event.round > 0:
                for name, card in self.agent_cards.items():
                    if name != self.leader_name:
                        card.reset()

        elif event.type == "leader_section_start":
            if self._leader_streaming and self._leader_streaming != "*Réfléchit...*":
                self._leader_history += self._leader_streaming
            self._leader_streaming = ""
            header = event.content or ""
            if self._leader_history:
                self._leader_history += f"\n\n---\n\n{header}\n\n"
            else:
                self._leader_history = f"{header}\n\n"
            self._leader_history_dirty = True
            self._update_leader_display()

        elif event.type == "leader_thinking":
            self._leader_streaming = "*Réfléchit...*"
            self._update_leader_display()

        elif event.type == "leader_streaming":
            if self._leader_streaming == "*Réfléchit...*":
                self._leader_streaming = ""
            self._leader_streaming += event.content or ""
            self._update_leader_display()

        elif event.type == "leader_speak":
            self._leader_history += event.content or ""
            self._leader_streaming = ""
            self._leader_history_dirty = True
            self._update_leader_display()

        elif event.type == "agent_thinking":
            if event.agent_name and event.agent_name in self.agent_cards:
                self.agent_cards[event.agent_name].set_thinking(event.phase)
                self._scroll_to_bottom(event.agent_name)

        elif event.type == "agent_streaming":
            if event.agent_name and event.agent_name in self.agent_cards:
                self.agent_cards[event.agent_name].append_chunk(event.content or "")
                self._scroll_to_bottom(event.agent_name)

        elif event.type == "agent_speak":
            if event.agent_name and event.agent_name in self.agent_cards:
                self.agent_cards[event.agent_name].set_content(event.phase, event.content or "")
                self._scroll_to_bottom(event.agent_name)

        elif event.type == "continuation_thinking":
            status.update("[dim]Le modérateur prépare une question de suivi...[/dim]")

        elif event.type == "end":
            self._debate_ended = True
            elapsed = self._elapsed_str()
            elapsed_str = f" · {elapsed}" if elapsed else ""
            status.update(f"[green bold]Débat terminé !{elapsed_str}[/green bold]")

        elif event.type == "continuation_suggestion":
            self._continuation_question = event.content or ""
            # Rendre le binding "c" visible maintenant que le débat est terminé
            try:
                self.app.refresh_bindings()
            except Exception:
                pass

    def save_debate(self) -> None:
        if self.debate_manager is None:
            self.query_one("#status", Label).update("[red]Aucun débat en cours.[/red]")
            return
        default = datetime.now().strftime("debate_%Y-%m-%d_%H-%M.md")
        self.app.push_screen(FilenameScreen(default_name=default), self._on_filename_chosen)

    def _on_filename_chosen(self, filename: str | None) -> None:
        if filename is None:
            return
        self._do_save(filename)

    def _do_save(self, path: str) -> None:
        try:
            saved = self.debate_manager.save(path)  # type: ignore[union-attr]
            self.query_one("#status", Label).update(f"[green]Sauvegardé : {saved}[/green]")
        except Exception as e:
            self.query_one("#status", Label).update(f"[red]Erreur sauvegarde : {e}[/red]")

    def action_toggle_leader(self) -> None:
        leader_scroll = self.query_one("#leader_scroll")
        leader_scroll.display = not leader_scroll.display

    def check_action(self, action: str, parameters: tuple) -> bool | None:
        """Désactive l'action 'continue_debate' tant que le débat n'est pas terminé."""
        if action == "continue_debate":
            return self._debate_ended
        return True

    def action_continue_debate(self) -> None:
        if not self._debate_ended or self.debate_manager is None:
            return
        self.app.push_screen(
            ContinueScreen(suggested_question=self._continuation_question),
            self._on_continue_chosen,
        )

    def _on_continue_chosen(self, question: str | None) -> None:
        if not question or self.debate_manager is None:
            return

        # Préparer la continuation dans le manager
        self.debate_manager.continue_with(question)

        # Reset de l'état TUI
        self._debate_ended = False
        self._continuation_question = ""
        self._leader_history = ""
        self._leader_streaming = ""
        self._leader_history_dirty = False
        self._current_round = 0
        self._start_time = None

        # Mettre à jour le bandeau de question
        try:
            self.query_one("#question-banner", Label).update(
                f"[dim]{question}[/dim]"
            )
        except Exception:
            pass

        # Reset des cartes agents non-leader
        for name, card in self.agent_cards.items():
            if name != self.leader_name:
                card.reset()

        # Rafraîchir les bindings
        try:
            self.app.refresh_bindings()
        except Exception:
            pass

        # Relancer le débat
        self.start_debate()

    def action_stop_debate(self) -> None:
        """Arrête le débat en cours et revient à l'écran d'accueil."""
        if self.debate_manager is None:
            return
        self.debate_manager.cancel()
        status = self.query_one("#status", Label)
        status.update("[yellow]Arrêt en cours...[/yellow]")

    @work(exclusive=True, thread=False)
    async def start_debate(self) -> None:
        self._start_time = time.monotonic()

        def on_event(event: DebateEvent) -> None:
            self.post_message(DebateEventMessage(event))

        # Si un manager existe déjà (continuation), on le réutilise
        if self.debate_manager is None:
            self.debate_manager = DebateManager(self.config, on_event=on_event)
            self._total_rounds = self.config.debate.rounds
            await self.debate_manager.initialize()
        else:
            # Continuation : réattacher le callback et mettre à jour le total de tours
            self.debate_manager.on_event = on_event
            self._total_rounds = self.config.debate.rounds

        try:
            await self.debate_manager.run()
        except Exception:
            pass
        finally:
            if self.debate_manager.is_cancelled:
                try:
                    self.query_one("#status", Label).update("[yellow]Débat arrêté.[/yellow]")
                    self._debate_ended = True
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Application principale
# ---------------------------------------------------------------------------

class AgentsMeetingApp(App):
    """Application principale."""

    BINDINGS = [
        Binding("q", "quit", "Quitter", show=True),
        Binding("m", "toggle_leader", "Modérateur", show=True),
        Binding("w", "save_debate", "Sauvegarder", show=True),
        Binding("c", "continue_debate", "Continuer", show=True),
        Binding("r", "new_question", "Nouvelle question", show=True),
    ]

    def __init__(self, config: MeetingConfig):
        super().__init__()
        self.config = config

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen(self.config))

    def compose(self) -> ComposeResult:
        # Fond vide — les écrans sont gérés par push_screen / switch_screen
        return
        yield  # satisfaire mypy

    def action_toggle_leader(self) -> None:
        screen = self.screen
        if isinstance(screen, DebateScreen):
            screen.action_toggle_leader()

    def action_stop_debate(self) -> None:
        screen = self.screen
        if isinstance(screen, DebateScreen):
            screen.action_stop_debate()

    def action_continue_debate(self) -> None:
        screen = self.screen
        if isinstance(screen, DebateScreen):
            screen.action_continue_debate()

    def action_save_debate(self) -> None:
        screen = self.screen
        if isinstance(screen, DebateScreen):
            screen.save_debate()

    def action_new_question(self) -> None:
        """Revenir à l'écran d'accueil pour éditer la question et relancer."""
        screen = self.screen
        if isinstance(screen, DebateScreen):
            self.switch_screen(WelcomeScreen(self.config))
        elif isinstance(screen, WelcomeScreen):
            # Déjà sur l'écran d'accueil, juste remettre le focus sur l'input
            try:
                inp = screen.query_one("#question-input", Input)
                inp.focus()
            except Exception:
                pass

    def action_quit(self) -> None:
        self.exit()
