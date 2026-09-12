"""Schermate modali (viste). Dipendono solo da models/storage/lang/nlparse."""

import calendar
import re
from datetime import datetime, timedelta
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Input,
    Label,
    ListItem,
    ListView,
    Select,
    SelectionList,
    Static,
    TextArea,
)

from src import crypto as _crypto
from src.lang import (
    T,
    days_long,
    days_short,
    get_lang,
    key_sections,
    months,
    prio_disp,
    prio_letters,
    rec_disp,
)
from src.models import (
    HEALTH_CRIT_LATE,
    HEALTH_CRIT_RATIO,
    PRIORITY_ORDER,
    Priority,
    Recurrence,
    TodoItem,
    _due_date_part,
    _due_time_part,
    _format_date_it,
    _is_valid_date,
    _normalize_date,
    _pomo_label,
    _status,
)
from src.nlparse import parse_with_found
from src.plan import plan_day
from src.storage import _backup_sources, snapshot_info


def _parse_day(due: str):
    part = _due_date_part(due)
    if not part:
        return datetime.max.date()
    try:
        return datetime.strptime(part, "%Y-%m-%d").date()
    except ValueError:
        return datetime.max.date()


def _agenda_due(todo: TodoItem) -> str:
    day = _due_date_part(todo.due)
    if not day:
        return ""
    try:
        d = datetime.strptime(day, "%Y-%m-%d").date()
        label = f"{d.day:02d}/{d.month:02d}"
    except ValueError:
        label = day
    time = _due_time_part(todo.due)
    return f"({label} {time}) " if time else f"({label}) "


_RICH_STYLE_TAGS = (
    "b",
    "/b",
    "dim",
    "/dim",
    "green",
    "red",
    "cyan",
    "yellow",
    "bold",
    "/bold",
    "italic",
    "/italic",
    "underline",
    "/underline",
)


def _strip_rich_tags(line: str) -> str:
    """Toglie i tag di stile noti (il resto, es. [x] utente, resta intatto)."""
    tags = "|".join(re.escape(t) for t in _RICH_STYLE_TAGS)
    return re.sub(rf"\[({tags})\]", "", line).strip()


def _escape_markup(text: str) -> str:
    """Rende letterali le parentesi quadre (i widget le leggono come Rich)."""
    return text.replace("[", "\\[")


def _hero_row(label: str, value: str) -> str:
    """Riga statistica allineata: label puntinata a larghezza fissa."""
    dots = "." * max(2, 16 - len(label))
    return f"  {label} {dots} {value}"


def _done_on_day(todos: list[TodoItem], day: str) -> list[TodoItem]:
    return [t for t in todos if t.done and (t.completed_at or "")[:10] == day]


def _pomo_on_day(todos: list[TodoItem], day: str) -> int:
    return sum(1 for t in todos for ts in (t.pomodoro_log or []) if ts[:10] == day)


def _streak_days(by_date: dict[str, int], today: str) -> int:
    """Serie di giorni di fila con completati (vale da ieri se oggi e' a zero)."""
    try:
        today_d = datetime.strptime(today, "%Y-%m-%d").date()
    except ValueError:
        return 0
    d = (
        today_d
        if by_date.get(today_d.strftime("%Y-%m-%d"), 0) > 0
        else today_d - timedelta(days=1)
    )
    streak = 0
    while by_date.get(d.strftime("%Y-%m-%d"), 0) > 0:
        streak += 1
        d -= timedelta(days=1)
    return streak


class TodoFormScreen(ModalScreen[dict | None]):
    """Modal screen to add or edit a todo item."""

    CSS = """
    #form-container {
        width: 72;
        max-width: 95%;
        height: 90%;
        max-height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 0 2 1 2;
    }
    #form-title-wrap {
        width: 100%;
        height: auto;
        align: center middle;
        margin-bottom: 1;
    }
    #form-title {
        width: auto;
        text-style: bold;
        color: $primary;
        height: auto;
        border: solid $primary;
        padding: 0 1;
    }
    #form-body {
        width: 100%;
        height: 1fr;
    }
    #form-body Input {
        margin-bottom: 1;
    }
    #title-input {
        border: solid $primary-darken-1;
        padding: 0 1;
    }
    #nl-preview {
        width: 1fr;
        height: auto;
        margin-bottom: 1;
    }
    #nl-syntax {
        width: 1fr;
        height: auto;
        margin-bottom: 0;
    }
    #nl-try {
        height: auto;
        margin-bottom: 1;
        text-style: underline;
        color: $primary;
    }
    #form-body Label {
        margin-bottom: 0;
    }
    #row-priorita-ricorrenza {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }
    #col-priorita {
        width: 1fr;
        height: auto;
        margin-right: 1;
    }
    #col-ricorrenza {
        width: 1fr;
        height: auto;
        margin-left: 1;
    }
    #row-tags-due, #row-prog-due, #row-tags {
        width: 100%;
        height: auto;
        margin-bottom: 1;
    }
    #col-tags, #col-project {
        width: 1fr;
        height: auto;
        margin-right: 1;
    }
    #col-stima {
        width: 20;
        min-width: 12;
        height: auto;
        margin-left: 1;
    }
    #col-due {
        width: 1fr;
        height: auto;
        margin-left: 1;
    }
    #notes-textarea {
        height: 6;
        margin-bottom: 1;
        border: solid $primary-darken-1;
    }
    #form-buttons {
        align: center middle;
        margin-top: 1;
        width: 100%;
        height: 3;
        dock: bottom;
    }
    #form-buttons Button {
        margin: 0 1;
        width: 1fr;
        min-width: 18;
        height: 3;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Annulla"),
        Binding("ctrl+enter", "submit", "Salva", show=False),
        Binding("ctrl+l", "fill_nl", "Compila", show=False),
        Binding("s", "submit", "Salva", show=False),
    ]

    def __init__(
        self, todo: TodoItem | None = None, title: str = "", preset_project: str = ""
    ) -> None:
        super().__init__()
        self.todo = todo
        self.screen_title = title or T("form_new")
        self.preset_project = (preset_project or "").strip().lower()

    @staticmethod
    def _nl_example() -> str:
        """Esempio del giorno (rotazione deterministica, screenshot al sicuro)."""
        examples = [T("nl_exa1"), T("nl_exa2"), T("nl_exa3")]
        return examples[datetime.now().date().toordinal() % len(examples)]

    def compose(self) -> ComposeResult:
        with Vertical(id="form-container"):
            with Horizontal(id="form-title-wrap"):
                yield Label(self.screen_title, id="form-title")
            with VerticalScroll(id="form-body", can_focus=False):
                yield Input(
                    placeholder=T("form_title_ph", ex=self._nl_example()),
                    id="title-input",
                )
                yield Label(f"[dim]{T('nl_hint')}[/]", id="nl-preview")
                yield Label(f"[dim]{T('nl_syntax')}[/]", id="nl-syntax")
                yield Label(T("nl_try"), id="nl-try")
                yield Label(T("form_notes"))
                yield TextArea("", id="notes-textarea")
                with Horizontal(id="row-prog-due"):
                    with Vertical(id="col-project"):
                        yield Label(T("form_project"))
                        yield Input(
                            placeholder=T("form_project_ph"), id="project-input"
                        )
                    with Vertical(id="col-due"):
                        yield Label(T("form_due"))
                        yield Input(placeholder=T("form_due_ph"), id="due-input")
                with Horizontal(id="row-tags"):
                    with Vertical(id="col-tags"):
                        yield Label(T("form_tags"))
                        yield Input(placeholder=T("form_tags_ph"), id="tags-input")
                    with Vertical(id="col-stima"):
                        yield Label(T("form_stima"))
                        yield Input(placeholder=T("form_stima_ph"), id="stima-input")
                with Horizontal(id="row-priorita-ricorrenza"):
                    with Vertical(id="col-priorita"):
                        yield Label(T("form_priority"))
                        yield Select(
                            [(prio_disp(p.value), p) for p in Priority],
                            value=self.todo.priority if self.todo else Priority.MEDIUM,
                            id="priority-select",
                        )
                    with Vertical(id="col-ricorrenza"):
                        yield Label(T("form_recurrence"))
                        yield Select(
                            [(rec_disp(r.value), r) for r in Recurrence],
                            value=self.todo.recurrence
                            if self.todo
                            else Recurrence.NONE,
                            id="recurrence-select",
                        )
            with Horizontal(id="form-buttons"):
                yield Button(T("form_save"), id="save-btn", variant="default")
                yield Button(T("form_cancel"), id="cancel-btn", variant="default")

    def on_mount(self) -> None:
        if self.todo:
            self.query_one("#title-input", Input).value = self.todo.title
            self.query_one("#notes-textarea", TextArea).text = self.todo.notes
            self.query_one("#due-input", Input).value = self.todo.due
            self.query_one("#project-input", Input).value = self.todo.project
            if self.todo.tags:
                self.query_one("#tags-input", Input).value = ", ".join(self.todo.tags)
            if self.todo and self.todo.stima_pomo:
                self.query_one("#stima-input", Input).value = str(self.todo.stima_pomo)
        elif self.preset_project:
            # Nuovo sotto-task: mostra l'ereditarieta' dal padre (modificabile).
            self.query_one("#project-input", Input).value = self.preset_project
        # Form con campi: il focus sta sul primo campo (scrivere e' l'azione primaria).
        try:
            self.query_one("#title-input", Input).focus()
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self._submit()

    def action_fill_nl(self) -> None:
        """Compila SOLO i campi trovati nel titolo (ctrl+l); mai overwrite.

        A titolo vuoto apre il foglio esempi invece di lamentarsi.
        """
        raw = self.query_one("#title-input", Input).value.strip()
        if not raw:
            # Niente import di app (convenzione): self.app e' runtime Textual.
            self.app.push_screen(NLHelpScreen())
            return
        res, found = parse_with_found(raw, get_lang())
        # Firma anti-eco: il Changed asincrono del set programmatico viene ignorato.
        self._nl_filled = res["title"]
        self.query_one("#title-input", Input).value = res["title"]
        if "due" in found:
            self.query_one("#due-input", Input).value = res["due"]
        if "project" in found:
            self.query_one("#project-input", Input).value = res["project"]
        if "tags" in found:
            self.query_one("#tags-input", Input).value = ", ".join(res["tags"])
        if "stima_pomo" in found:
            stima = int(res["stima_pomo"] or 0)
            self.query_one("#stima-input", Input).value = str(stima) if stima else ""
        if "priority" in found:
            self.query_one("#priority-select", Select).value = res["priority"]
        if "recurrence" in found:
            self.query_one("#recurrence-select", Select).value = res["recurrence"]
        if "notes" in found:
            self.query_one("#notes-textarea", TextArea).text = res["notes"]
        self.query_one("#nl-preview", Label).update(self._nl_summary(res, found))
        try:
            self.query_one("#save-btn", Button).focus()
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        """Anteprima live mentre digiti il titolo (compila solo con ctrl+l)."""
        try:
            if event.input.id != "title-input":
                return
            if event.value == getattr(self, "_nl_filled", None):
                return  # eco del fill programmatico: preview gia' impostata
            self._nl_filled = None
            res, found = parse_with_found(event.value, get_lang())
            if len(found) > 1:
                self.query_one("#nl-preview", Label).update(
                    self._nl_summary(res, found)
                )
            else:
                self.query_one("#nl-preview", Label).update(f"[dim]{T('nl_hint')}[/]")
        except Exception:
            pass

    @staticmethod
    def _nl_summary(res: dict, found: set | None = None) -> str:
        parts = []
        if res["due"]:
            parts.append(res["due"])
        if res["project"]:
            parts.append(f"*{res['project']}")
        parts.extend(f"#{t}" for t in res["tags"])
        if res["priority"] != Priority.MEDIUM:
            parts.append(f"!{res['priority'].value}")
        if res["recurrence"] != Recurrence.NONE:
            parts.append(rec_disp(res["recurrence"].value))
        if int(res["stima_pomo"] or 0):
            parts.append(f"~{res['stima_pomo']}")
        if res["notes"]:
            parts.append("// …")
        if not parts:
            return f"[dim]{T('nl_none')}[/]"
        return T("nl_preview", s=" · ".join(parts))

    def on_click(self, event) -> None:
        """Solo il link esempi; gli altri click scorrono liberi (niente stop)."""
        try:
            widget, _region = self.get_widget_at(event.screen_x, event.screen_y)
        except Exception:
            return
        if widget is not None and getattr(widget, "id", None) == "nl-try":
            self._insert_example()

    def _insert_example(self) -> None:
        """Scrive l'esempio nel titolo solo se vuoto (mai distruggere digitato)."""
        try:
            title_input = self.query_one("#title-input", Input)
        except Exception:
            return
        if title_input.value.strip():
            self.notify(T("nl_title_busy"), severity="warning")
            return
        title_input.value = self._nl_example()
        title_input.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id == "save-btn":
            self._submit()

    def _submit(self) -> None:
        title = self.query_one("#title-input", Input).value.strip()
        if not title:
            title_input = self.query_one("#title-input", Input)
            title_input.border_title = T("form_need_title")
            title_input.focus()
            self.notify(T("n_title_req"), severity="warning")
            return
        priority = self.query_one("#priority-select", Select).value
        due_raw = self.query_one("#due-input", Input).value.strip()
        due = _normalize_date(due_raw)
        if due_raw and not _is_valid_date(due):
            due_input = self.query_one("#due-input", Input)
            due_input.border_title = T("form_need_date")
            due_input.focus()
            self.notify(T("n_date_bad"), severity="error")
            return
        notes = self.query_one("#notes-textarea", TextArea).text.strip()
        recurrence = self.query_one("#recurrence-select", Select).value
        tags_raw = self.query_one("#tags-input", Input).value.strip()
        tags = (
            [t.strip().lower() for t in tags_raw.split(",") if t.strip()]
            if tags_raw
            else []
        )
        project = self.query_one("#project-input", Input).value.strip().lower()
        stima_raw = self.query_one("#stima-input", Input).value.strip()
        try:
            stima = max(0, int(stima_raw)) if stima_raw else 0
        except (ValueError, TypeError):
            stima_input = self.query_one("#stima-input", Input)
            stima_input.border_title = T("form_need_num")
            stima_input.focus()
            self.notify(T("n_stima_bad"), severity="error")
            return
        self.dismiss(
            {
                "title": title,
                "priority": priority,
                "due": due,
                "notes": notes,
                "recurrence": recurrence,
                "tags": tags,
                "project": project,
                "stima_pomo": stima,
            }
        )


class NLHelpScreen(ModalScreen[None]):
    """Foglio esempi per l'inserimento in linguaggio naturale."""

    CSS = """
    #nlh-box {
        width: 72;
        max-width: 95%;
        height: auto;
        max-height: 90%;
    }
    #nlh-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
        height: auto;
    }
    .nlh-line {
        height: auto;
        margin-bottom: 0;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    ROWS = (
        "nl_h_due",
        "nl_h_proj",
        "nl_h_tags",
        "nl_h_prio",
        "nl_h_est",
        "nl_h_rec",
        "nl_h_notes",
    )

    def compose(self) -> ComposeResult:
        with Vertical(id="nlh-box"):
            yield Label(f"[b]{T('nl_help_t')}[/b]", id="nlh-title")
            for key in self.ROWS:
                yield Label(f"  {T(key)}", classes="nlh-line")
            yield Label(f"  [dim]{T('nl_ex1')}[/]", classes="nlh-line")
            yield Label(f"  [dim]{T('nl_ex2')}[/]", classes="nlh-line")
            yield Button(T("ui_close_esc"), id="nlh-close", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#nlh-close", Button).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nlh-close":
            self.dismiss()

    def action_close(self) -> None:
        self.dismiss()


class ConfirmScreen(ModalScreen[bool]):
    """Simple confirmation dialog."""

    CSS = """
    #confirm-box {
        width: 60;
        max-width: 90%;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }
    #confirm-msg {
        text-align: center;
        margin-bottom: 1;
    }
    #confirm-buttons {
        align: center middle;
        width: 100%;
        height: 3;
    }
    #confirm-buttons Button {
        margin: 0 1;
        width: 1fr;
        min-width: 12;
        height: 3;
    }
    """

    BINDINGS = [Binding("escape", "no", "No")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label(self.message, id="confirm-msg")
            with Horizontal(id="confirm-buttons"):
                yield Button(T("confirm_yes"), id="yes-btn", variant="error")
                yield Button(T("b_cancel"), id="no-btn", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes-btn")

    def on_mount(self) -> None:
        # Focus sull'azione principale: Enter conferma senza mouse (Esc annulla).
        try:
            self.query_one("#yes-btn", Button).focus()
        except Exception:
            pass

    def action_no(self) -> None:
        self.dismiss(False)


class StateChoiceScreen(ModalScreen[str | None]):
    """Menu scelta per lo stato di un todo (Space)."""

    CSS = """
    #state-box {
        width: 38;
        max-width: 90%;
        height: auto;
    }
    #state-buttons {
        width: 100%;
        height: auto;
    }
    #state-row-1, #state-row-2 {
        width: 100%;
        height: 3;
        margin-bottom: 1;
    }
    #state-row-1 Button, #state-row-2 Button {
        width: 1fr;
        min-width: 0;
        height: 3;
        margin: 0 1;
    }
    #state-legend {
        height: auto;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Annulla"),
        Binding("left", "focus_prev", "Precedente", show=False),
        Binding("right", "focus_next", "Successivo", show=False),
        Binding("up", "focus_up", "Sopra", show=False),
        Binding("down", "focus_down", "Sotto", show=False),
    ]

    def __init__(self, title: str, current: str, current_state: str = "attivo") -> None:
        super().__init__()
        self.todo_title = title
        self.current = current
        self.current_state = (
            current_state
            if current_state in ("attivo", "in_sospeso", "completato")
            else "attivo"
        )

    def _button_label(self, state: str, key: str) -> str:
        label = T(key)
        if state == self.current_state:
            label = f"● {label}"
        return label

    def compose(self) -> ComposeResult:
        with Vertical(id="state-box"):
            yield Label(
                T("state_title", title=self.todo_title, current=self.current),
                id="state-msg",
            )
            with Vertical(id="state-buttons"):
                with Horizontal(id="state-row-1"):
                    yield Button(
                        self._button_label("attivo", "state_btn_attivo"),
                        id="attivo-btn",
                        variant="default",
                    )
                    yield Button(
                        self._button_label("in_sospeso", "state_btn_sospeso"),
                        id="sospeso-btn",
                        variant="default",
                    )
                with Horizontal(id="state-row-2"):
                    yield Button(
                        self._button_label("completato", "state_btn_completato"),
                        id="completato-btn",
                        variant="default",
                    )
                    yield Button(T("ui_cancel_esc"), id="cancel-btn", variant="default")
            yield Static(T("state_legend"), id="state-legend")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "attivo-btn": "attivo",
            "sospeso-btn": "in_sospeso",
            "completato-btn": "completato",
        }
        if event.button.id == "cancel-btn":
            self.dismiss(None)
        elif event.button.id in mapping:
            self.dismiss(mapping[event.button.id])

    _STATE_FOCUS = {
        "attivo": "#attivo-btn",
        "in_sospeso": "#sospeso-btn",
        "completato": "#completato-btn",
    }

    def on_mount(self) -> None:
        try:
            self.query_one(
                self._STATE_FOCUS.get(self.current_state, "#attivo-btn"), Button
            ).focus()
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    _STATE_FOCUS_IDS = ("attivo-btn", "sospeso-btn", "completato-btn", "cancel-btn")

    def _focus_shift(self, delta: int) -> None:
        """Sposta il focus di delta posizioni nella griglia 2x2."""
        try:
            focused = self.focused
            cur = focused.id if focused is not None else None
            idx = (
                self._STATE_FOCUS_IDS.index(cur) if cur in self._STATE_FOCUS_IDS else 0
            )
            nxt = idx + delta
            if 0 <= nxt < len(self._STATE_FOCUS_IDS):
                self.query_one(f"#{self._STATE_FOCUS_IDS[nxt]}", Button).focus()
        except Exception:
            pass

    def action_focus_prev(self) -> None:
        self._focus_shift(-1)

    def action_focus_next(self) -> None:
        self._focus_shift(1)

    def action_focus_up(self) -> None:
        self._focus_shift(-2)

    def action_focus_down(self) -> None:
        self._focus_shift(2)


class ThemeListScreen(ModalScreen[str | None]):
    """Popup con lista temi selezionabile."""

    CSS = """
    #theme-box {
        width: 52;
        max-width: 90%;
        max-height: 85%;
    }
    #theme-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #theme-list {
        height: auto;
        max-height: 20;
        margin-bottom: 1;
    }
    #theme-list Button {
        width: 100%;
        min-width: 16;
        height: 3;
        margin-bottom: 0;
        text-align: left;
        content-align: left middle;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Chiudi"),
        Binding("up", "cursor_up", "Su", show=False, priority=True),
        Binding("down", "cursor_down", "Giu", show=False, priority=True),
    ]

    def __init__(self, themes: list[str], current: str) -> None:
        super().__init__()
        self.themes = themes
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-box"):
            yield Label(T("theme_title"), id="theme-title")
            with VerticalScroll(id="theme-list"):
                for name in self.themes:
                    label = f"● {name}" if name == self.current else f"○ {name}"
                    yield Button(label, id=f"theme-{name}", variant="default")
            yield Button(T("ui_close_esc"), id="theme-close", variant="default")

    def on_mount(self) -> None:
        # Focus sul tema corrente (o Chiudi): stile deterministico.
        try:
            buttons = [b for b in self.query("#theme-list Button")]
            target = next((b for b in buttons if b.id == f"theme-{self.current}"), None)
            (target or self.query_one("#theme-close", Button)).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "theme-close":
            self.dismiss(None)
        elif event.button.id.startswith("theme-"):
            self.dismiss(event.button.id[len("theme-") :])

    def _focusables(self) -> list[Button]:
        try:
            return [
                *self.query("#theme-list Button"),
                self.query_one("#theme-close", Button),
            ]
        except Exception:
            return []

    def _step_focus(self, delta: int) -> None:
        items = self._focusables()
        if not items:
            return
        try:
            cur = items.index(self.focused)
        except ValueError:
            cur = -1 if delta > 0 else 0
        try:
            items[(cur + delta) % len(items)].focus()
        except Exception:
            pass

    def action_cursor_up(self) -> None:
        self._step_focus(-1)

    def action_cursor_down(self) -> None:
        self._step_focus(1)

    def action_close(self) -> None:
        self.dismiss(None)


class SearchScreen(ModalScreen[str | None]):
    """Popup ricerca full-text con / ."""

    CSS = """
    #search-box {
        width: 60;
        max-width: 90%;
        height: auto;
    }
    #search-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #search-input {
        margin-bottom: 1;
    }
    #search-buttons {
        width: 100%;
        height: 3;
    }
    #search-buttons Button {
        width: 1fr;
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Annulla")]

    def __init__(self, current: str = "") -> None:
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="search-box"):
            yield Label(T("search_title"), id="search-title")
            yield Input(
                value=self.current, placeholder=T("search_ph"), id="search-input"
            )
            with Horizontal(id="search-buttons"):
                yield Button(T("b_search"), id="ok-btn", variant="default")
                yield Button(T("search_clear"), id="clear-btn", variant="default")

    def on_mount(self) -> None:
        # Query presente -> focus su Pulisci (Enter azzera); vuota -> cursore nel campo.
        try:
            if (self.current or "").strip():
                self.query_one("#clear-btn", Button).focus()
            else:
                self.query_one("#search-input", Input).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "ok-btn":
            self.dismiss(self.query_one("#search-input", Input).value.strip())
        elif event.button.id == "clear-btn":
            self.dismiss("")

    def action_cancel(self) -> None:
        self.dismiss(None)


class AgendaScreen(ModalScreen[None]):
    """Radar cronologico: scaduti, oggi, domani, prossimi 7 giorni."""

    CSS = """
    #agenda-box {
        width: 86;
        max-width: 95%;
        height: 90%;
        max-height: 90%;
    }
    #agenda-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #agenda-list {
        height: 1fr;
        margin-bottom: 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def __init__(self, all_todos: list[TodoItem]) -> None:
        super().__init__()
        self.all_todos = all_todos

    def compose(self) -> ComposeResult:
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        week_end = today + timedelta(days=7)
        active = [t for t in self.all_todos if t.state != "completato"]
        with Vertical(id="agenda-box"):
            yield Label(T("agenda_title"), id="agenda-title")
            with VerticalScroll(id="agenda-list"):
                yield from self._section(
                    T("agenda_overdue"),
                    [
                        t
                        for t in active
                        if _due_date_part(t.due) and _parse_day(t.due) < today
                    ],
                )
                yield from self._section(
                    T("agenda_today"),
                    [t for t in active if _parse_day(t.due) == today],
                )
                yield from self._section(
                    T("agenda_tomorrow"),
                    [t for t in active if _parse_day(t.due) == tomorrow],
                )
                yield from self._section(
                    T("agenda_next"),
                    [t for t in active if tomorrow < _parse_day(t.due) <= week_end],
                )
                yield from self._section(
                    T("agenda_important"),
                    [
                        t
                        for t in active
                        if not _due_date_part(t.due) and t.priority == Priority.HIGH
                    ],
                )
            yield Button(T("ui_close_esc"), id="agenda-close", variant="default")

    def _section(self, title: str, todos: list[TodoItem]):
        yield Label(f"[b]{title}[/b]")
        if not todos:
            yield Static(f"  [dim]{T('agenda_empty')}[/]")
            return
        for t in sorted(
            todos,
            key=lambda x: (
                _due_date_part(x.due) or "9999-99-99",
                _due_time_part(x.due) or "99:99",
                PRIORITY_ORDER.get(x.priority.value, 9),
                x.title.lower(),
            ),
        ):
            due = _agenda_due(t)
            proj = f" @{t.project}" if t.project else ""
            yield Static(
                f"  {_status(t)} {due}{t.title}{proj}  [{t.priority.color}]{prio_disp(t.priority.value)}[/]"
            )
        yield Static("")

    def on_mount(self) -> None:
        try:
            self.query_one("#agenda-close", Button).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "agenda-close":
            self.dismiss()

    def action_close(self) -> None:
        self.dismiss()


class WorkflowScreen(ModalScreen[None]):
    """Guida operativa breve: come usare Tasko nel ciclo quotidiano."""

    CSS = """
    #workflow-box {
        width: 86;
        max-width: 95%;
        height: 90%;
        max-height: 90%;
    }
    #workflow-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #workflow-list {
        height: 1fr;
        margin-bottom: 1;
    }
    .workflow-head {
        height: auto;
        margin-top: 1;
        margin-bottom: 0;
    }
    .workflow-line {
        height: auto;
        margin-bottom: 0;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def compose(self) -> ComposeResult:
        with Vertical(id="workflow-box"):
            yield Label(T("workflow_title"), id="workflow-title")
            with VerticalScroll(id="workflow-list"):
                yield Label(T("workflow_intro"), classes="workflow-line")
                for i in range(1, 6):
                    yield Label(T(f"workflow_s{i}_t"), classes="workflow-head")
                    yield Static(T(f"workflow_s{i}_b"), classes="workflow-line")
            yield Button(T("ui_close_esc"), id="workflow-close", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#workflow-close", Button).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "workflow-close":
            self.dismiss()

    def action_close(self) -> None:
        self.dismiss()


class WeekScreen(ModalScreen[None]):
    """Vista settimana Lun-Dom."""

    CSS = """
    #week-box {
        width: 80;
        max-width: 95%;
        height: 90%;
        max-height: 90%;
    }
    #week-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #week-nav {
        width: 100%;
        height: 3;
        margin-bottom: 1;
    }
    #week-nav Button {
        width: 1fr;
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    #week-list {
        height: 1fr;
        margin-bottom: 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def __init__(self, all_todos: list[TodoItem], monday: "datetime.date") -> None:
        super().__init__()
        self.all_todos = all_todos
        self.monday = monday

    def compose(self) -> ComposeResult:
        end = self.monday + timedelta(days=6)
        with Vertical(id="week-box"):
            yield Label(
                f"[b]{T('week_title', a=self.monday.strftime('%d/%m'), b=end.strftime('%d/%m/%Y'))}[/b]",
                id="week-title",
            )
            with Horizontal(id="week-nav"):
                yield Button(T("nav_prev"), id="prev-btn", variant="default")
                yield Button(T("nav_next"), id="next-btn", variant="default")
            with VerticalScroll(id="week-list"):
                for i in range(7):
                    d = self.monday + timedelta(days=i)
                    ds = d.strftime("%Y-%m-%d")
                    day_todos = [
                        t
                        for t in self.all_todos
                        if _due_date_part(t.due) == ds and t.state != "completato"
                    ]
                    label = (
                        f"{days_long()[d.weekday()]} {d.day:02d} {months()[d.month]}"
                    )
                    if d == datetime.now().date():
                        yield Label(f"[b reverse] {label} [/b reverse]")
                    else:
                        yield Label(f"[b]{label}[/b]")
                    if day_todos:
                        for t in sorted(
                            day_todos,
                            key=lambda x: (
                                PRIORITY_ORDER.get(x.priority.value, 9),
                                x.title.lower(),
                            ),
                        ):
                            tm = (
                                f" {_due_time_part(t.due)}"
                                if _due_time_part(t.due)
                                else ""
                            )
                            yield Static(
                                f"  {_status(t)} {t.title}{tm}  [{t.priority.color}]{prio_disp(t.priority.value)}[/]"
                            )
                    else:
                        yield Static("  [dim]-[/]")
            yield Button(T("ui_close_esc"), id="week-close", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#week-close", Button).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "week-close":
            self.dismiss()
        elif event.button.id == "prev-btn":
            self.monday -= timedelta(days=7)
            self.refresh(recompose=True)
        elif event.button.id == "next-btn":
            self.monday += timedelta(days=7)
            self.refresh(recompose=True)

    def action_close(self) -> None:
        self.dismiss()


class TemplateScreen(ModalScreen[tuple | None]):
    """Scelta template: Usa per creare i task, N nuovo, P da progetto, X elimina."""

    CSS = """
    #tpl-box {
        width: 60;
        max-width: 92%;
        max-height: 88%;
    }
    #tpl-list {
        height: auto;
        max-height: 24;
        margin-bottom: 1;
    }
    .tpl-row {
        width: 100%;
        height: 3;
        margin-bottom: 1;
        align-vertical: middle;
    }
    .tpl-use-btn {
        width: 1fr;
        min-width: 16;
        height: 3;
    }
    .tpl-del-btn {
        width: 3;
        min-width: 3;
        height: 1;
        min-height: 1;
        padding: 0;
        border: none;
        margin: 1 0 0 1;
    }
    .tpl-edit-btn {
        width: 3;
        min-width: 3;
        height: 1;
        min-height: 1;
        padding: 0;
        border: none;
        margin: 1 0 0 1;
    }
    #tpl-empty {
        height: auto;
        margin-bottom: 1;
    }
    #tpl-actions {
        width: 100%;
        height: auto;
    }
    #tpl-actions Button {
        width: 1fr;
        min-width: 12;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Chiudi"),
        Binding("n", "new_template", "Nuovo"),
        Binding("p", "from_project", "Da progetto"),
    ]

    def __init__(self, templates: dict[str, list[dict]] | None = None) -> None:
        super().__init__()
        self.templates = templates if templates is not None else {}

    def compose(self) -> ComposeResult:
        with Vertical(id="tpl-box"):
            yield Label(T("tpl_title"), id="tpl-title")
            with VerticalScroll(id="tpl-list"):
                if not self.templates:
                    yield Label(T("tpl_empty"), id="tpl-empty")
                for i, (name, items) in enumerate(self.templates.items()):
                    with Horizontal(classes="tpl-row"):
                        yield Button(
                            T("tpl_use", name=name, n=len(items)),
                            id=f"tpl-use-{i}",
                            variant="default",
                            classes="tpl-use-btn",
                        )
                        yield Button(
                            "M",
                            id=f"tpl-edit-{i}",
                            variant="default",
                            classes="tpl-edit-btn",
                        )
                        yield Button(
                            "X",
                            id=f"tpl-del-{i}",
                            variant="error",
                            classes="tpl-del-btn",
                        )
            with Horizontal(id="tpl-actions"):
                yield Button(T("tpl_new"), id="tpl-new", variant="default")
                yield Button(
                    T("tpl_fromproj"), id="tpl-from-project", variant="default"
                )
                yield Button(T("ui_close_esc"), id="tpl-close", variant="default")

    def _name_at(self, idx: int) -> str | None:
        try:
            return list(self.templates.keys())[idx]
        except IndexError:
            return None

    def on_mount(self) -> None:
        # Focus su "Nuovo": Enter apre subito la creazione (mouse non necessario).
        try:
            self.query_one("#tpl-new", Button).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "tpl-close":
            self.dismiss(None)
        elif bid == "tpl-new":
            self.dismiss(("new", None))
        elif bid == "tpl-from-project":
            self.dismiss(("from_project", None))
        elif bid.startswith("tpl-use-"):
            try:
                name = self._name_at(int(bid[len("tpl-use-") :]))
            except ValueError:
                return
            if name:
                self.dismiss(("use", name))
        elif bid.startswith("tpl-del-"):
            try:
                name = self._name_at(int(bid[len("tpl-del-") :]))
            except ValueError:
                return
            if name:
                self.dismiss(("delete", name))
        elif bid.startswith("tpl-edit-"):
            try:
                name = self._name_at(int(bid[len("tpl-edit-") :]))
            except ValueError:
                return
            if name:
                self.dismiss(("edit", name))

    def action_close(self) -> None:
        self.dismiss(None)

    def action_new_template(self) -> None:
        self.dismiss(("new", None))

    def action_from_project(self) -> None:
        self.dismiss(("from_project", None))


class TemplateCreateScreen(ModalScreen[dict | None]):
    """Crea un nuovo template: nome + un task per riga."""

    CSS = """
    #tplc-box {
        width: 64;
        max-width: 92%;
        height: 90%;
        max-height: 90%;
    }
    #tplc-body {
        width: 100%;
        height: 1fr;
    }
    #tplc-tasks {
        height: 10;
        margin-bottom: 1;
        border: solid $primary-darken-1;
    }
    #tplc-buttons {
        width: 100%;
        height: 3;
        dock: bottom;
        margin-top: 1;
    }
    #tplc-buttons Button {
        width: 1fr;
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Annulla"),
        Binding("ctrl+enter", "submit", "Salva", show=False),
        Binding("s", "submit", "Salva", show=False),
    ]

    def __init__(self, initial: dict | None = None) -> None:
        """initial: {'name': str, 'items': [{'title', 'priority'}]} per la modifica."""
        super().__init__()
        self.initial = initial or {}

    def compose(self) -> ComposeResult:
        title = T("tplc_edit") if self.initial.get("name") else T("tplc_new")
        with Vertical(id="tplc-box"):
            yield Label(f"[b]{title}[/b]", id="tplc-title")
            with VerticalScroll(id="tplc-body", can_focus=False):
                yield Label(T("tplc_name"))
                yield Input(placeholder=T("tplc_name_ph"), id="tplc-name")
                yield Label(T("tplc_prio"))
                yield Select(
                    [(prio_disp(p.value), p) for p in Priority],
                    value=Priority.MEDIUM,
                    id="tplc-priority",
                )
                yield Label(T("tplc_tasks"))
                yield TextArea("", id="tplc-tasks")
            with Horizontal(id="tplc-buttons"):
                yield Button(T("form_save"), id="tplc-save", variant="default")
                yield Button(T("form_cancel"), id="tplc-cancel", variant="default")

    def on_mount(self) -> None:
        # Form con campi: il focus sta sul nome da compilare.
        try:
            if self.initial.get("name"):
                self.query_one("#tplc-name", Input).value = str(self.initial["name"])
            items = self.initial.get("items") or []
            if items:
                self.query_one("#tplc-tasks", TextArea).text = "\n".join(
                    str(i.get("title", "")) for i in items if isinstance(i, dict)
                )
                prios = [i.get("priority") for i in items if isinstance(i, dict)]
                prios = [p for p in prios if isinstance(p, Priority)]
                if prios:
                    top = max(set(prios), key=prios.count)
                    try:
                        self.query_one("#tplc-priority", Select).value = top
                    except Exception:
                        pass
            self.query_one("#tplc-name", Input).focus()
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tplc-cancel":
            self.dismiss(None)
        elif event.button.id == "tplc-save":
            self._submit()

    def _submit(self) -> None:
        name = self.query_one("#tplc-name", Input).value.strip()
        if not name:
            self.query_one("#tplc-name", Input).focus()
            self.notify(T("n_tpl_name_req"), severity="warning")
            return
        default_priority = self.query_one("#tplc-priority", Select).value
        lines = [
            ln.strip()
            for ln in (self.query_one("#tplc-tasks", TextArea).text or "").splitlines()
        ]
        titles = [ln for ln in lines if ln]
        if not titles:
            self.query_one("#tplc-tasks", TextArea).focus()
            self.notify(T("n_tpl_tasks_req"), severity="warning")
            return
        self.dismiss(
            {
                "name": name,
                "items": [{"title": t, "priority": default_priority} for t in titles],
            }
        )


class TemplateProjectScreen(ModalScreen[str | None]):
    """Sceglie un progetto esistente da cui creare un template."""

    CSS = """
    #tplp-box {
        width: 52;
        max-width: 90%;
        max-height: 85%;
    }
    #tplp-list {
        height: auto;
        max-height: 20;
        margin-bottom: 1;
    }
    #tplp-list Button {
        width: 100%;
        min-width: 16;
        height: 3;
        margin-bottom: 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def __init__(self, projects: list[tuple[str, int]]) -> None:
        super().__init__()
        self.projects = projects

    def compose(self) -> ComposeResult:
        with Vertical(id="tplp-box"):
            yield Label(T("tplp_title"), id="tplp-title")
            with VerticalScroll(id="tplp-list"):
                for name, count in self.projects:
                    yield Button(
                        T("tplp_row", name=name, n=count),
                        id=f"tplp-{name}",
                        variant="default",
                    )
            yield Button(T("ui_close_esc"), id="tplp-close", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "tplp-close":
            self.dismiss(None)
        elif event.button.id.startswith("tplp-"):
            self.dismiss(event.button.id[len("tplp-") :])

    def on_mount(self) -> None:
        try:
            first = self.query("#tplp-list Button")
            (first.first() if first else self.query_one("#tplp-close", Button)).focus()
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss(None)


class ImportCsvScreen(ModalScreen[str | None]):
    """Sceglie un CSV da importare (lista + percorso manuale)."""

    CSS = """
    #impcsv-box {
        width: 64;
        max-width: 92%;
        max-height: 88%;
    }
    #impcsv-list {
        height: auto;
        max-height: 14;
        margin-bottom: 1;
    }
    #impcsv-list Button {
        width: 100%;
        min-width: 16;
        height: 3;
        margin-bottom: 1;
    }
    #impcsv-path {
        margin-bottom: 1;
    }
    #impcsv-buttons {
        width: 100%;
        height: 3;
    }
    #impcsv-buttons Button {
        width: 1fr;
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Annulla"),
        Binding("ctrl+enter", "submit", "Salva", show=False),
        Binding("s", "submit", "Salva", show=False),
    ]

    def __init__(self, files: list[Path]) -> None:
        super().__init__()
        self.files = files

    def compose(self) -> ComposeResult:
        with Vertical(id="impcsv-box"):
            yield Label(T("imp_title"), id="impcsv-title")
            with VerticalScroll(id="impcsv-list"):
                if not self.files:
                    yield Label(T("imp_empty"))
                for i, p in enumerate(self.files):
                    yield Button(f"{p.name}", id=f"impcsv-{i}", variant="default")
            yield Label(T("imp_path"))
            yield Input(placeholder=T("imp_path_ph"), id="impcsv-path")
            with Horizontal(id="impcsv-buttons"):
                yield Button(T("imp_ok"), id="impcsv-ok", variant="default")
                yield Button(T("form_cancel"), id="impcsv-cancel", variant="default")

    def on_mount(self) -> None:
        try:
            first = self.query("#impcsv-list Button")
            (first.first() if first else self.query_one("#impcsv-path", Input)).focus()
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "impcsv-cancel":
            self.dismiss(None)
        elif event.button.id == "impcsv-ok":
            self._submit()
        elif (event.button.id or "").startswith("impcsv-"):
            try:
                self.dismiss(str(self.files[int(event.button.id[len("impcsv-") :])]))
            except (ValueError, IndexError):
                pass

    def _submit(self) -> None:
        path = self.query_one("#impcsv-path", Input).value.strip()
        if not path:
            self.query_one("#impcsv-path", Input).focus()
            self.notify(T("n_imp_pick"), severity="warning")
            return
        self.dismiss(path)


class PomodoroScreen(ModalScreen[None]):
    """Timer pomodoro con durata impostabile, pausa/riprendi, live countdown."""

    CSS = """
    #pomo-box {
        width: 46;
        max-width: 90%;
        height: auto;
    }
    #pomo-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
        height: auto;
    }
    #pomo-task {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
        height: auto;
    }
    #pomo-time {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
        height: 3;
    }
    #pomo-dur-label {
        margin-bottom: 0;
        height: auto;
    }
    #pomo-durations {
        width: 100%;
        height: 3;
        margin-bottom: 1;
    }
    #pomo-durations Button {
        width: 1fr;
        min-width: 0;
        height: 3;
        margin: 0 1;
    }
    #pomo-buttons {
        width: 100%;
        height: auto;
    }
    #pomo-buttons Button {
        width: 100%;
        min-width: 0;
        height: 3;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Chiudi"),
        Binding("p", "pause_resume", "Pausa/Riprendi", show=False),
        Binding("x", "done", "Completa", show=False),
        Binding("X", "done", "Completa", show=False),
        Binding("1", "dur_0", "Durata 1", show=False),
        Binding("2", "dur_1", "Durata 2", show=False),
        Binding("3", "dur_2", "Durata 3", show=False),
    ]

    def __init__(
        self, get_state, on_pause_resume, on_stop, on_done, on_set_duration
    ) -> None:
        super().__init__()
        self.get_state = get_state
        self.on_pause_resume = on_pause_resume
        self.on_stop = on_stop
        self.on_done = on_done
        self.on_set_duration = on_set_duration
        self._timer = None

    def compose(self) -> ComposeResult:
        with Vertical(id="pomo-box"):
            yield Label("[b]🍅 Pomodoro[/b]", id="pomo-title")
            yield Label("", id="pomo-task")
            yield Label("", id="pomo-time")
            yield Label(T("pomo_dur_focus"), id="pomo-dur-label")
            with Horizontal(id="pomo-durations"):
                yield Button("", id="pomo-dur-0", variant="default")
                yield Button("", id="pomo-dur-1", variant="default")
                yield Button("", id="pomo-dur-2", variant="default")
            with Vertical(id="pomo-buttons"):
                yield Button(T("pomo_pause"), id="pause-btn", variant="default")
                yield Button(T("pomo_done"), id="done-btn", variant="default")
                yield Button(T("pomo_stop"), id="stop-btn", variant="default")
                yield Button(T("pomo_close"), id="pomo-close", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#pause-btn", Button).focus()
        except Exception:
            pass
        self._refresh()
        try:
            self._timer = self.set_interval(1, self._refresh)
        except Exception:
            pass

    def _refresh(self) -> None:
        try:
            state = self.get_state()
        except Exception:
            return
        if not isinstance(state, dict) or state.get("empty"):
            try:
                self.dismiss()
            except Exception:
                pass
            return
        try:
            is_break = bool(state.get("is_break"))
            if state.get("phase") == "long":
                title = T("pomo_t_long")
            elif is_break:
                title = T("pomo_t_short")
            else:
                title = T("pomo_t_focus")
            self.query_one("#pomo-title", Label).update(f"[b]{title}[/b]")
            self.query_one("#pomo-task", Label).update(state["task"])
            self.query_one("#pomo-time", Label).update(f"[b]{state['clock']}[/b]")
            self.query_one("#pause-btn", Button).label = (
                T("pomo_resume") if state["paused"] else T("pomo_pause")
            )
            self.query_one("#done-btn", Button).label = (
                T("pomo_skip") if is_break else T("pomo_done")
            )
            self.query_one("#pomo-dur-label", Label).update(
                T("pomo_dur_break") if is_break else T("pomo_dur_focus")
            )
            presets = state.get("presets") or (15, 25, 50)
            for i in range(3):
                try:
                    btn = self.query_one(f"#pomo-dur-{i}", Button)
                    btn.label = f"{presets[i]}'"
                    btn.variant = (
                        "primary" if state["total_min"] == presets[i] else "default"
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def _preset_value(self, index: int) -> int | None:
        try:
            presets = self.get_state().get("presets") or ()
            return int(presets[index])
        except (ValueError, TypeError, IndexError):
            return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "pomo-close":
            self.dismiss()
        elif bid == "pause-btn":
            self.on_pause_resume()
            self._refresh()
        elif bid == "stop-btn":
            self.on_stop()
            self.dismiss()
        elif bid == "done-btn":
            self.on_done()
            self.dismiss()
        elif bid.startswith("pomo-dur-"):
            try:
                minutes = self._preset_value(int(bid[len("pomo-dur-") :]))
            except ValueError:
                return
            if minutes is None:
                return
            self.on_set_duration(minutes)
            self._refresh()

    def action_close(self) -> None:
        self.dismiss()

    def action_pause_resume(self) -> None:
        self.on_pause_resume()
        self._refresh()

    def action_done(self) -> None:
        self.on_done()
        self.dismiss()

    def action_dur_0(self) -> None:
        minutes = self._preset_value(0)
        if minutes is None:
            return
        self.on_set_duration(minutes)
        self._refresh()

    def action_dur_1(self) -> None:
        minutes = self._preset_value(1)
        if minutes is None:
            return
        self.on_set_duration(minutes)
        self._refresh()

    def action_dur_2(self) -> None:
        minutes = self._preset_value(2)
        if minutes is None:
            return
        self.on_set_duration(minutes)
        self._refresh()


class KanbanScreen(ModalScreen[None]):
    """Board kanban Attivo / Sospeso / Completato."""

    CSS = """
    #kb-box {
        width: 96;
        max-width: 98%;
        max-height: 92%;
    }
    #kb-title {
        text-align: center;
        text-style: bold;
        color: $primary;
    }
    #kb-hint {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
        height: auto;
    }
    #kb-cols {
        width: 100%;
        height: 22;
    }
    #kb-col-attivo, #kb-col-sospeso, #kb-col-fatto {
        width: 1fr;
        height: 100%;
        margin: 0 1;
        border: solid $primary-darken-1;
        padding: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def __init__(self, all_todos: list[TodoItem]) -> None:
        super().__init__()
        self.all_todos = all_todos

    def _col(self, state: str) -> list[TodoItem]:
        items = [t for t in self.all_todos if not t.is_subtask and t.state == state]
        return sorted(
            items,
            key=lambda x: (
                (_due_date_part(x.due) or "9999"),
                PRIORITY_ORDER.get(x.priority.value, 9),
            ),
        )

    def compose(self) -> ComposeResult:
        cols = [
            ("attivo", T("kb_col_attivo"), self._col("attivo"), "red"),
            ("sospeso", T("kb_col_sospeso"), self._col("in_sospeso"), "yellow"),
            ("fatto", T("kb_col_fatto"), self._col("completato"), "green"),
        ]
        with Vertical(id="kb-box"):
            yield Label(T("kb_title"), id="kb-title")
            yield Label(
                T("kb_hint"),
                id="kb-hint",
            )
            with Horizontal(id="kb-cols"):
                for key, title, items, color in cols:
                    with VerticalScroll(id=f"kb-col-{key}"):
                        yield Label(f"[{color}][b]{title} ({len(items)})[/b][/]")
                        if not items:
                            yield Static("[dim]—[/]")
                        for t in items[:30]:
                            proj = f" @{t.project}" if t.project else ""
                            tm = (
                                f" {_due_date_part(t.due)}"
                                if _due_date_part(t.due)
                                else ""
                            )
                            yield Static(f"#{t.id} {t.title[:28]}{proj}{tm}")
                        if len(items) > 30:
                            yield Static(f"[dim]{T('kb_more', n=len(items) - 30)}[/]")
            yield Button(T("ui_close_esc"), id="kb-close", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "kb-close":
            self.dismiss()

    def on_mount(self) -> None:
        try:
            self.query_one("#kb-close", Button).focus()
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss()


class DetailScreen(ModalScreen[str | None]):
    """Screen to show todo details including notes and subtasks."""

    CSS = """
    #detail-box {
        width: 60;
        max-width: 90%;
        max-height: 85%;
    }
    #detail-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #detail-notes {
        height: auto;
        max-height: 10;
        margin-bottom: 1;
        padding: 0 1;
        border: solid $primary-darken-1;
    }
    #detail-scroll {
        height: auto;
        max-height: 22;
    }
    #detail-subtasks {
        height: auto;
        max-height: 15;
    }
    #detail-close {
        margin-top: 1;
        width: 1fr;
        min-width: 16;
        height: 3;
    }
    #detail-edit {
        margin-top: 1;
        width: 1fr;
        min-width: 16;
        height: 3;
    }
    #detail-buttons {
        width: 100%;
        height: auto;
        margin-top: 1;
    }
    #detail-buttons Button {
        width: 1fr;
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Chiudi"),
        Binding("e", "edit", "Modifica"),
    ]

    def __init__(self, todo: TodoItem, all_todos: list[TodoItem]) -> None:
        super().__init__()
        self.todo = todo
        self.all_todos = all_todos

    def _get_subtasks(self, parent_id: int) -> list[TodoItem]:
        return [t for t in self.all_todos if t.parent_id == parent_id]

    def _build_tree(
        self, todo: TodoItem, depth: int = 0, prefix: str = "", is_last: bool = True
    ) -> list[tuple[int, str, TodoItem]]:
        result = []
        status = _status(todo)
        if depth == 0:
            display = f"  {status} {todo.title}"
        else:
            connector = "└── " if is_last else "├── "
            display = f"  {prefix}{connector}{status} {todo.title}"
        result.append((depth, display, todo))

        subtasks = self._get_subtasks(todo.id)
        for i, sub in enumerate(subtasks):
            is_last_sub = i == len(subtasks) - 1
            new_prefix = prefix + ("    " if is_last else "│   ") if depth > 0 else ""
            result.extend(self._build_tree(sub, depth + 1, new_prefix, is_last_sub))
        return result

    def compose(self) -> ComposeResult:
        with Vertical(id="detail-box"):
            yield Label(f"[b]{self.todo.title}[/b]", id="detail-title")
            yield Label(
                f"{T('detail_prio')} [{self.todo.priority.color}]{prio_disp(self.todo.priority.value)}[/]"
            )
            if self.todo.project:
                yield Label(f"{T('form_project')} [blue]{self.todo.project}[/]")
            if self.todo.pomodoros or getattr(self.todo, "stima_pomo", 0):
                yield Label(f"{T('detail_pomo')} [red]{_pomo_label(self.todo)}[/]")
            if self.todo.tags:
                yield Label(
                    f"{T('form_tags')} "
                    + ", ".join(f"[magenta]#{t}[/]" for t in self.todo.tags)
                )
            yield Label(
                T("detail_dueline", due=self.todo.due or "-", created=self.todo.created)
            )
            if self.todo.recurrence != Recurrence.NONE:
                yield Label(
                    f"{T('detail_ric')} [cyan]{rec_disp(self.todo.recurrence.value)}[/]"
                )
            stato_label = {
                "attivo": f"[red]{T('state_attivo').capitalize()}[/red]",
                "in_sospeso": f"[yellow]{T('state_sospeso').capitalize()}[/yellow]",
                "completato": f"[green]{T('state_completato').capitalize()}[/green]",
            }[self.todo.state]
            yield Label(f"{T('detail_state')} {stato_label}")
            if self.todo.notes:
                yield Label(T("detail_notes"))
                pretty_notes = (
                    self.todo.notes.replace("- [ ]", "☐")
                    .replace("- [x]", "☑")
                    .replace("- [X]", "☑")
                )
                with VerticalScroll(id="detail-scroll"):
                    yield Static(pretty_notes, id="detail-notes")
            tree_items = self._build_tree(self.todo)
            if len(tree_items) > 1:
                yield Label(T("detail_subs"), id="detail-subtasks-label")
                with VerticalScroll(id="detail-subtasks"):
                    for depth, display, item in tree_items[1:]:
                        yield Static(display)
            else:
                yield Label(T("detail_nosubs"), id="detail-subtasks-label")
            with Horizontal(id="detail-buttons"):
                yield Button(T("detail_edit"), id="detail-edit", variant="default")
                yield Button(T("ui_close_esc"), id="detail-close", variant="default")

    def on_mount(self) -> None:
        # Focus su Chiudi: Enter/Esc chiude, e resta la via breve da tastiera.
        try:
            self.query_one("#detail-close", Button).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "detail-close":
            self.dismiss(None)
        elif event.button.id == "detail-edit":
            self.dismiss("edit")

    def action_close(self) -> None:
        self.dismiss(None)

    def action_edit(self) -> None:
        self.dismiss("edit")


class DayScreen(ModalScreen[None]):
    """Screen showing the todos due on a specific day."""

    CSS = """
    #day-box {
        width: 70;
        max-width: 90%;
        max-height: 90%;
    }
    #day-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #day-list {
        height: auto;
        max-height: 20;
        margin-bottom: 1;
    }
    #day-empty {
        height: auto;
        color: $text-muted;
        margin-bottom: 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def __init__(self, date_str: str, todos: list[TodoItem]) -> None:
        super().__init__()
        self.date_str = date_str
        self.todos = todos

    def compose(self) -> ComposeResult:
        label = _format_date_it(self.date_str)
        with Vertical(id="day-box"):
            yield Label(f"[b]{T('day_title', label=label)}[/b]", id="day-title")
            if self.todos:
                with VerticalScroll(id="day-list"):
                    for t in self.todos:
                        yield Static(
                            f"  {_status(t)} {t.title}  [{t.priority.color}]{prio_disp(t.priority.value)}[/]"
                        )
            else:
                yield Static(T("day_empty"), id="day-empty")
            yield Button(T("ui_close_esc"), id="day-close", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "day-close":
            self.dismiss()

    def on_mount(self) -> None:
        try:
            self.query_one("#day-close", Button).focus()
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss()


class CalendarScreen(ModalScreen[None]):
    """Screen to show todos on a monthly calendar grid."""

    CSS = """
    #calendar-box {
        width: 80;
        max-width: 95%;
        max-height: 90%;
    }
    #calendar-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #calendar-nav {
        align: center middle;
        margin-bottom: 1;
        width: 100%;
        height: 3;
    }
    #calendar-nav Button {
        margin: 0 1;
        width: 1fr;
        min-width: 14;
        height: 3;
    }
    #calendar-grid-wrap {
        height: auto;
        width: 100%;
        align: center middle;
    }
    #calendar-grid {
        height: auto;
        width: auto;
    }
    #calendar-legend {
        margin-top: 1;
        height: auto;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def __init__(self, all_todos: list[TodoItem], year: int, month: int) -> None:
        super().__init__()
        self.all_todos = all_todos
        self.year = year
        self.month = month

    def _todos_by_day(self) -> dict[int, list[TodoItem]]:
        result: dict[int, list[TodoItem]] = {}
        for t in self.all_todos:
            if t.due and t.state != "completato":
                try:
                    d = datetime.strptime(_due_date_part(t.due), "%Y-%m-%d").date()
                except ValueError:
                    continue
                if d.year == self.year and d.month == self.month:
                    result.setdefault(d.day, []).append(t)
        return result

    def compose(self) -> ComposeResult:
        month_name = months()[self.month]
        with Vertical(id="calendar-box"):
            yield Label(f"[b]{month_name} {self.year}[/b]", id="calendar-title")
            with Horizontal(id="calendar-nav"):
                yield Button(T("nav_prev"), id="prev-btn", variant="default")
                yield Button(T("nav_next"), id="next-btn", variant="default")
            with Horizontal(id="calendar-grid-wrap"):
                yield Static(self._render_grid(), id="calendar-grid")
            yield Static(T("cal_legend"), id="calendar-legend")
            yield Button(T("ui_close_esc"), id="calendar-close", variant="default")

    def _render_grid(self) -> str:
        cl = calendar.Calendar(firstweekday=0)
        header = " ".join(f"{g:^5}" for g in days_short())
        todos_by_day = self._todos_by_day()
        today = datetime.now().date()
        lines = [header]
        prio_color = {
            Priority.HIGH: ("red", prio_letters()["alta"]),
            Priority.MEDIUM: ("yellow", prio_letters()["media"]),
            Priority.LOW: ("green", prio_letters()["bassa"]),
        }
        for week in cl.monthdayscalendar(self.year, self.month):
            day_cells = []
            task_cells = []
            for day in week:
                if day == 0:
                    day_cells.append(" " * 5)
                    task_cells.append(" " * 5)
                    continue
                todos = todos_by_day.get(day, [])
                plain_num = str(day)
                number_markup = plain_num
                if any(t.priority == Priority.HIGH for t in todos):
                    number_markup = f"[red]{plain_num}[/]"
                elif any(t.priority == Priority.MEDIUM for t in todos):
                    number_markup = f"[yellow]{plain_num}[/]"
                elif any(t.priority == Priority.LOW for t in todos):
                    number_markup = f"[green]{plain_num}[/]"
                if datetime(self.year, self.month, day).date() == today:
                    number_markup = f"[bold reverse]{number_markup}[/]"
                number_markup = self._center_markup(number_markup, len(plain_num), 5)
                marks = ""
                plain_marks = ""
                for t in todos[:3]:
                    color, letter = prio_color[t.priority]
                    marks += f"[{color}]{letter}[/]"
                    plain_marks += letter
                if len(todos) > 3:
                    suffix = f"+{len(todos) - 3}"
                    if len(plain_marks) + len(suffix) > 5:
                        plain_marks = plain_marks[: max(0, 5 - len(suffix))]
                        marks = "".join(
                            f"[{prio_color[t.priority][0]}]{prio_color[t.priority][1]}[/]"
                            for t in todos[: len(plain_marks)]
                        )
                    marks += f"[dim]{suffix}[/]"
                    plain_marks += suffix
                day_cells.append(
                    f"[@click=app.open_day({self.year},{self.month},{day})]{number_markup}[/]"
                )
                task_cells.append(
                    self._center_markup(marks, len(plain_marks), 5)
                    if marks
                    else " " * 5
                )
            lines.append(" ".join(day_cells))
            lines.append(" ".join(task_cells))
        return "\n".join(lines)

    @staticmethod
    def _center_markup(marked: str, plain_len: int, width: int) -> str:
        total = max(0, width - plain_len)
        left = total // 2
        return " " * left + marked + " " * (total - left)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "calendar-close":
            self.dismiss()
        elif button_id == "prev-btn":
            self.month -= 1
            if self.month < 1:
                self.month = 12
                self.year -= 1
            self.refresh(recompose=True)
        elif button_id == "next-btn":
            self.month += 1
            if self.month > 12:
                self.month = 1
                self.year += 1
            self.refresh(recompose=True)

    def on_mount(self) -> None:
        try:
            self.query_one("#calendar-close", Button).focus()
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss()


class DailyPlanScreen(ModalScreen[None]):
    """Screen showing today's planned tasks with quick add/remove."""

    CSS = """
    #plan-box {
        width: 80;
        max-width: 95%;
        height: 90%;
    }
    #plan-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #plan-section {
        height: 1fr;
        margin-bottom: 1;
    }
    #plan-legend {
        margin-top: 1;
        height: auto;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Chiudi"),
        Binding("+", "add_planned", "Aggiungi al piano", show=False),
        Binding("x", "remove_planned", "Rimuovi", show=False),
        Binding("space", "toggle_done", "Sospendi", show=False),
    ]

    def __init__(
        self, all_todos: list[TodoItem], on_change, today: str | None = None
    ) -> None:
        super().__init__()
        self.all_todos = all_todos
        self.on_change = on_change
        self.today = today or datetime.now().strftime("%Y-%m-%d")

    def _planned_todos(self) -> list[TodoItem]:
        return [
            t
            for t in self.all_todos
            if t.planned_for == self.today and t.state == "attivo"
        ]

    def _due_today(self) -> list[TodoItem]:
        return [
            t
            for t in self.all_todos
            if _due_date_part(t.due) == self.today
            and t.state == "attivo"
            and t.planned_for != self.today
        ]

    def _overdue(self) -> list[TodoItem]:
        try:
            today_d = datetime.strptime(self.today, "%Y-%m-%d").date()
        except ValueError:
            return []
        result = []
        for t in self.all_todos:
            if t.state != "attivo" or not t.due:
                continue
            try:
                d = datetime.strptime(_due_date_part(t.due), "%Y-%m-%d").date()
            except ValueError:
                continue
            if d < today_d:
                result.append(t)
        return result

    def _unplanned(self) -> list[TodoItem]:
        return [
            t
            for t in self.all_todos
            if t.state == "attivo" and not t.due and not t.planned_for
        ]

    @staticmethod
    def _row(t: TodoItem, marker: str, extra: str = "") -> str:
        plbl = _pomo_label(t)
        pomo = f" [red]{plbl}[/]" if plbl else ""
        return (
            f"  [cyan]{marker}[/] {_status(t)} {t.title}{extra}  [dim]#{t.id}[/]{pomo}"
        )

    def compose(self) -> ComposeResult:
        today_display = _format_date_it(self.today)
        with Vertical(id="plan-box"):
            yield Label(
                f"[b]{T('plan_title', date=today_display)}[/b]", id="plan-title"
            )
            planned = self._planned_todos()
            due = self._due_today()
            overdue = self._overdue()
            unplanned = self._unplanned()
            load = ""
            if planned:
                load_f = sum(t.pomodoros for t in planned)
                load_s = sum(getattr(t, "stima_pomo", 0) or 0 for t in planned)
                load = T("plan_load", f=load_f, s=load_s) if load_s else ""
            sections = [
                (T("plan_sec_planned", load=load), "planned", planned, "x"),
                (T("plan_sec_due"), "due", due, "+"),
                (T("plan_sec_overdue"), "overdue", overdue, "+"),
                (T("plan_sec_unplanned"), "unplanned", unplanned, "+"),
            ]
            items = [t for _h, _k, todos, _m in sections for t in todos]
            if items:
                keep = getattr(self, "_keep_id", None)
                children = []
                found_keep: int | None = None
                for header, kind, todos, marker in sections:
                    if not todos:
                        continue
                    children.append(ListItem(Label(header), disabled=True))
                    for t in todos:
                        extra = (
                            T("plan_overdue_row", due=t.due)
                            if kind == "overdue"
                            else ""
                        )
                        row = ListItem(Label(self._row(t, marker, extra)))
                        row.task_id = t.id
                        row.section = kind
                        if found_keep is None and t.id == keep:
                            found_keep = len(children)
                        children.append(row)
                initial = found_keep if found_keep is not None else 1
                yield ListView(*children, id="plan-section", initial_index=initial)
            else:
                yield Static(T("plan_empty"))
            yield Static(T("plan_legend"), id="plan-legend")
            yield Button(T("ui_close_esc"), id="plan-close", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#plan-section", ListView).focus()
        except Exception:
            self.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "plan-close":
            self.dismiss()

    def _current(self) -> tuple:
        """(task_id, sezione) della riga evidenziata, o (None, None)."""
        try:
            item = self.query_one("#plan-section", ListView).highlighted_child
        except Exception:
            return None, None
        if item is None:
            return None, None
        return getattr(item, "task_id", None), getattr(item, "section", None)

    def _refresh_keep(self, task_id=None) -> None:
        self._keep_id = task_id
        self.on_change()
        self.refresh(recompose=True)

    def action_add_planned(self) -> None:
        tid, section = self._current()
        if tid is None or section not in ("due", "overdue", "unplanned"):
            self.notify(T("n_plan_noop"), severity="warning")
            return
        todo = next(
            (t for t in self.all_todos if t.id == tid and t.state == "attivo"), None
        )
        if todo is None:
            self.notify(T("n_plan_noop"), severity="warning")
            return
        todo.planned_for = self.today
        self._refresh_keep(tid)
        self.notify(T("n_plan_added", t=todo.title))

    def action_remove_planned(self) -> None:
        tid, section = self._current()
        if tid is None or section != "planned":
            self.notify(T("n_plan_noop"), severity="warning")
            return
        for t in self.all_todos:
            if t.id == tid and t.planned_for == self.today and t.state == "attivo":
                t.planned_for = ""
                self._refresh_keep(tid)
                return
        self.notify(T("n_plan_rm_none"), severity="warning")

    def action_toggle_done(self) -> None:
        tid, section = self._current()
        if tid is None or section != "planned":
            self.notify(T("n_plan_noop"), severity="warning")
            return
        for t in self.all_todos:
            if t.planned_for == self.today and t.id == tid and t.state == "attivo":
                t.paused = True
                self._refresh_keep(tid)
                return
        self.notify(T("n_plan_susp_none"), severity="warning")

    def action_close(self) -> None:
        self.dismiss()


class ReviewScreen(ModalScreen[None]):
    """Chiusura giornata: riepilogo di oggi + scelta del piano di domani."""

    CSS = """
    #rev-box {
        width: 100;
        max-width: 95%;
        height: 90%;
        max-height: 90%;
    }
    #rev-list {
        height: auto;
        margin-bottom: 1;
    }
    #rev-scroll {
        height: 1fr;
        margin-bottom: 1;
    }
    #rev-summary {
        height: auto;
        margin-bottom: 1;
    }
    #rev-additive {
        height: auto;
        margin-bottom: 1;
    }
    #rev-legend {
        height: auto;
    }
    #rev-buttons {
        width: 100%;
        height: 3;
        margin-top: 1;
    }
    #rev-buttons Button {
        width: 1fr;
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Chiudi"),
        Binding("ctrl+enter", "confirm", "Conferma", show=False),
        Binding("s", "confirm", "Conferma", show=False),
    ]

    def __init__(
        self,
        all_todos: list[TodoItem],
        on_change,
        today: str | None = None,
        daily_goal: int = 0,
    ) -> None:
        super().__init__()
        self.all_todos = all_todos
        self.on_change = on_change
        self.today = today or datetime.now().strftime("%Y-%m-%d")
        try:
            self.daily_goal = max(0, int(daily_goal or 0))
        except (ValueError, TypeError):
            self.daily_goal = 0
        try:
            self.tomorrow = (
                datetime.strptime(self.today, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
        except ValueError:
            self.tomorrow = self.today

    def _done_today(self) -> list[TodoItem]:
        return [
            t
            for t in self.all_todos
            if t.done and (t.completed_at or "")[:10] == self.today
        ]

    def _pomo_today(self) -> int:
        return sum(
            1
            for t in self.all_todos
            for ts in (t.pomodoro_log or [])
            if ts[:10] == self.today
        )

    def _is_overdue(self, t: TodoItem) -> bool:
        due = _due_date_part(t.due)
        return bool(due) and due < self.today

    def _candidates(self) -> list[TodoItem]:
        cands = [t for t in self.all_todos if t.state == "attivo"]
        cands.sort(
            key=lambda t: (
                not self._is_overdue(t),
                _due_date_part(t.due) != self.tomorrow,
                PRIORITY_ORDER.get(t.priority.value, 9),
                _due_date_part(t.due) or "9999",
                t.title.lower(),
            )
        )
        return cands

    @staticmethod
    def _option_label(t: TodoItem) -> str:
        due = _due_date_part(t.due)
        extra = f" (scad. {due})" if due else ""
        # Niente #id in coda (resta nel value) e quadre letterali nei titoli.
        return f"{_escape_markup(t.title)}{extra}"

    def compose(self) -> ComposeResult:
        with Vertical(id="rev-box"):
            yield Label(
                f"[b]{T('rev_title', date=_format_date_it(self.today))}[/b]",
                id="rev-title",
            )
            yield Static(T("rev_additive"), id="rev-additive")
            with VerticalScroll(id="rev-scroll"):
                done = self._done_today()
                yield Static(self._summary_text(len(done)), id="rev-summary")
                yield Label(T("rev_cand", date=_format_date_it(self.tomorrow)))
                cands = self._candidates()
                if cands:
                    yield SelectionList(
                        *[
                            (self._option_label(t), t.id, i < 3)
                            for i, t in enumerate(cands)
                        ],
                        id="rev-list",
                    )
                else:
                    yield Static(T("rev_empty_cand"))
            yield Static(T("rev_legend"), id="rev-legend")
            with Horizontal(id="rev-buttons"):
                yield Button(T("form_save"), id="rev-confirm", variant="default")
                yield Button(T("form_cancel"), id="rev-close", variant="default")

    def _summary_text(self, n_done: int) -> str:
        goal_txt = T("rev_goal", n=self.daily_goal) if self.daily_goal > 0 else ""
        return T("rev_summary", done=n_done, goal=goal_txt, pomo=self._pomo_today())

    def on_mount(self) -> None:
        try:
            self.query_one("#rev-list", SelectionList).focus()
        except Exception:
            try:
                self.query_one("#rev-confirm", Button).focus()
            except Exception:
                self.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "rev-close":
            self.dismiss()
        elif event.button.id == "rev-confirm":
            self._confirm()

    def action_close(self) -> None:
        self.dismiss()

    def action_confirm(self) -> None:
        self._confirm()

    def _selected_ids(self) -> set:
        try:
            return set(self.query_one("#rev-list", SelectionList).selected)
        except Exception:
            return set()

    def _confirm(self) -> None:
        selected = self._selected_ids()
        n = 0
        k = 0
        for t in self.all_todos:
            if t.state != "attivo":
                continue
            if t.id in selected:
                t.planned_for = self.tomorrow
                n += 1
            elif t.planned_for == self.tomorrow:
                t.planned_for = ""
                k += 1
        self.on_change()
        self.notify(T("n_rev_saved", n=n, k=k))
        self.dismiss()


class PlanProposalScreen(ModalScreen[None]):
    """Buongiorno: contesto di oggi + proposta da confermare (scrive planned_for)."""

    CSS = """
    #planp-box {
        width: 100;
        max-width: 95%;
        height: 90%;
    }
    #planp-context {
        height: auto;
        margin-bottom: 1;
    }
    #planp-additive {
        height: auto;
        margin-bottom: 1;
    }
    #planp-scroll {
        height: 1fr;
        margin-bottom: 1;
    }
    #planp-list {
        height: auto;
        margin-bottom: 1;
    }
    #planp-summary {
        height: auto;
        margin-bottom: 1;
    }
    #planp-legend {
        height: auto;
    }
    #planp-buttons {
        width: 100%;
        height: 3;
        margin-top: 1;
    }
    #planp-buttons Button {
        width: 1fr;
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Chiudi"),
        Binding("ctrl+enter", "confirm", "Conferma", show=False),
        Binding("s", "confirm", "Conferma", show=False),
    ]

    def __init__(
        self,
        all_todos: list[TodoItem],
        on_change,
        today: str | None = None,
        hours: float = 6.0,
    ) -> None:
        super().__init__()
        self.all_todos = all_todos
        self.on_change = on_change
        self.today = today or datetime.now().strftime("%Y-%m-%d")
        try:
            self.hours = max(1.0, float(hours))
        except (ValueError, TypeError):
            self.hours = 6.0
        self.plan = plan_day(self.all_todos, today=self.today, hours=self.hours)
        # Semantica additiva: i gia' pianificati non si ripropongono (per
        # togliere c'e' il piano giorno con x). Restano nel computo capacita'.
        planned_ids = {
            t.id
            for t in self.all_todos
            if t.state == "attivo" and t.planned_for == self.today
        }
        self.n_planned = len(planned_ids)
        self.plan = [row for row in self.plan if row[0] not in planned_ids]
        self.by_id = {t.id: t for t in self.all_todos if t.id is not None}

    @staticmethod
    def _is_cut(reasons) -> bool:
        return any(k == "plan_cut" for k, _p in reasons)

    @staticmethod
    def _is_skipped(reasons) -> bool:
        return any(k == "plan_skipped" for k, _p in reasons)

    @classmethod
    def _preselected(cls, reasons) -> bool:
        return not cls._is_cut(reasons) and not cls._is_skipped(reasons)

    def _option_label(self, t_id: int, reasons) -> str:
        t = self.by_id.get(t_id)
        title = _escape_markup(t.title) if t else f"#{t_id}"
        due = _due_date_part(t.due) if t else ""
        extra = f" (scad. {due})" if due else ""
        why = ", ".join(
            T(k, **p) for k, p in reasons if k not in ("plan_cut", "plan_skipped")
        )
        # Niente []: le option del SelectionList interpretano il markup Rich.
        # Niente #id in coda: gli id interni restano nel value, cosi' i motivi
        # (il vero contenuto della riga) non vengono troncati dal terminale.
        flags = "".join(
            f" — {T(k)}"
            for k in ("plan_cut", "plan_skipped")
            if any(k == kk for kk, _p in reasons)
        )
        return f"{title}{extra} ({why}){flags}" if why else f"{title}{extra}{flags}"

    def _context_lines(self) -> list[str]:
        """Contesto di oggi (ex briefing mattina): conteggi, carico, ieri, serie."""
        active = [t for t in self.all_todos if t.state == "attivo"]
        if not active:
            return []
        planned = [t for t in active if t.planned_for == self.today]
        due = [t for t in active if _due_date_part(t.due) == self.today]
        overdue = [
            t
            for t in active
            if _due_date_part(t.due) and _due_date_part(t.due) < self.today
        ]
        load = sum(int(t.stima_pomo or 0) for t in planned)
        cap = int(self.hours / 0.5)
        try:
            yest = (
                datetime.strptime(self.today, "%Y-%m-%d") - timedelta(days=1)
            ).strftime("%Y-%m-%d")
        except ValueError:
            yest = self.today
        lines = [
            T("brief_m_sec_today"),
            _hero_row(T("brief_k_plan"), str(len(planned))),
            _hero_row(T("brief_k_due"), str(len(due))),
            _hero_row(T("brief_k_over"), str(len(overdue))),
            "  " + T("brief_m_load", s=load, c=cap, h=int(self.hours)),
            "  "
            + T(
                "brief_m_yest",
                d=len(_done_on_day(self.all_todos, yest)),
                p=_pomo_on_day(self.all_todos, yest),
            ),
        ]
        by_date: dict[str, int] = {}
        for t in self.all_todos:
            if t.completed_at:
                day = t.completed_at[:10]
                by_date[day] = by_date.get(day, 0) + 1
        streak = _streak_days(by_date, self.today)
        streak_txt = (
            T("stats_serie", n=streak) if streak else T("stats_serie_off")
        ).lstrip()
        lines.append("  " + streak_txt)
        return lines

    def compose(self) -> ComposeResult:
        with Vertical(id="planp-box"):
            yield Label(
                f"[b]{T('planp_title', date=_format_date_it(self.today))}[/b]",
                id="planp-title",
            )
            yield Static(T("planp_additive"), id="planp-additive")
            with VerticalScroll(id="planp-scroll"):
                ctx = self._context_lines()
                if ctx:
                    yield Static("\n".join(ctx), id="planp-context")
                n_in = sum(1 for _i, _s, r in self.plan if self._preselected(r))
                yield Static(
                    T(
                        "planp_summary",
                        n=n_in,
                        m=self.n_planned,
                        c=len(self.plan) - n_in,
                        h=int(self.hours),
                    ),
                    id="planp-summary",
                )
                if self.plan:
                    yield SelectionList(
                        *[
                            (
                                self._option_label(t_id, reasons),
                                t_id,
                                self._preselected(reasons),
                            )
                            for t_id, _score, reasons in self.plan
                        ],
                        id="planp-list",
                    )
                else:
                    yield Static(T("planp_done" if self.n_planned else "planp_empty"))
            yield Static(T("rev_legend"), id="planp-legend")
            with Horizontal(id="planp-buttons"):
                yield Button(T("form_save"), id="planp-confirm", variant="default")
                yield Button(T("form_cancel"), id="planp-close", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#planp-list", SelectionList).focus()
        except Exception:
            try:
                self.query_one("#planp-confirm", Button).focus()
            except Exception:
                self.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "planp-close":
            self.dismiss()
        elif event.button.id == "planp-confirm":
            self._confirm()

    def action_close(self) -> None:
        self.dismiss()

    def action_confirm(self) -> None:
        self._confirm()

    def _selected_ids(self) -> set:
        try:
            return set(self.query_one("#planp-list", SelectionList).selected)
        except Exception:
            return set()

    def _confirm(self) -> None:
        # Solo additivo: aggiunge i selezionati, non toglie mai i pianificati.
        selected = self._selected_ids()
        n = 0
        r = 0
        for t in self.all_todos:
            if t.state != "attivo":
                continue
            if t.id in selected:
                t.planned_for = self.today
                t.plan_skip = ""
                n += 1
            elif t.planned_for != self.today:
                if t.plan_skip != self.today:
                    r += 1
                t.plan_skip = self.today
        self.on_change()
        self.notify(T("n_planp_saved", n=n, k=self.n_planned, r=r))
        self.dismiss()


class BriefingScreen(ModalScreen[str | None]):
    """Resoconto sera: solo composizione di dati esistenti (zero rete)."""

    CSS = """
    #brief-box {
        width: 80;
        max-width: 95%;
        height: 90%;
    }
    #brief-scroll {
        height: 1fr;
    }
    #brief-buttons {
        width: 100%;
        height: 3;
        margin-top: 1;
    }
    #brief-buttons Button {
        width: 1fr;
        height: 3;
    }
    #brief-hint {
        height: auto;
        margin-top: 1;
    }
    #brief-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    .brief-line {
        height: auto;
        margin-bottom: 0;
    }
    .brief-head {
        height: auto;
        margin-top: 1;
        margin-bottom: 0;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Chiudi"),
        Binding("p", "print_brief", "Stampa", show=False),
    ]

    def __init__(
        self,
        all_todos: list[TodoItem],
        today: str | None = None,
        daily_goal: int = 0,
        on_print=None,
    ) -> None:
        super().__init__()
        self.all_todos = all_todos
        self.today = today or datetime.now().strftime("%Y-%m-%d")
        try:
            self.daily_goal = max(0, int(daily_goal or 0))
        except (ValueError, TypeError):
            self.daily_goal = 0
        self.on_print = on_print

    def _by_date(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for t in self.all_todos:
            if t.completed_at:
                day = t.completed_at[:10]
                result[day] = result.get(day, 0) + 1
        return result

    def _streak(self, by_date: dict[str, int]) -> int:
        return _streak_days(by_date, self.today)

    def _done_on(self, day: str) -> list[TodoItem]:
        return _done_on_day(self.all_todos, day)

    def _pomo_on(self, day: str) -> int:
        return _pomo_on_day(self.all_todos, day)

    def _evening_lines(self) -> list[str]:
        done = self._done_on(self.today)
        left = [
            t
            for t in self.all_todos
            if t.state == "attivo" and t.planned_for == self.today
        ]
        pomo = self._pomo_on(self.today)
        if self.daily_goal > 0:
            filled = min(10, max(0, round(len(done) / self.daily_goal * 10)))
            bar = "█" * filled + "░" * (10 - filled)
            count = f"{len(done)}/{self.daily_goal} · {pomo} 🍅  {bar}"
        else:
            count = f"{len(done)} · {pomo} 🍅"
        lines = [T("brief_e_sec_done"), f"  {count}"]
        streak = self._streak(self._by_date())
        streak_txt = (
            T("stats_serie", n=streak) if streak else T("stats_serie_off")
        ).lstrip()
        lines.append("  " + streak_txt)
        lines.append(T("brief_e_sec_left"))
        if left:
            for t in left:
                lines.append(f"  • {_escape_markup(t.title)}")
        elif any((t.planned_for or "") == self.today for t in self.all_todos):
            lines.append("  " + T("brief_e_left_empty"))
        else:
            lines.append("  " + T("brief_e_left_never"))
        return lines

    def compose(self) -> ComposeResult:
        with Vertical(id="brief-box"):
            yield Label(
                f"[b]{T('brief_e_title', date=_format_date_it(self.today))}[/b]",
                id="brief-title",
            )
            with VerticalScroll(id="brief-scroll"):
                lines = self._evening_lines()
                first = True
                for line in lines:
                    yield Static(
                        line,
                        classes="brief-line" if first else "brief-head",
                    )
                    first = False
            yield Static(T("brief_e_hint"), id="brief-hint")
            with Horizontal(id="brief-buttons"):
                yield Button(T("brief_print"), id="brief-print", variant="default")
                yield Button(T("brief_goto"), id="brief-goto", variant="default")
                yield Button(T("ui_close_esc"), id="brief-close", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#brief-close", Button).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "brief-close":
            self.dismiss()
        elif event.button.id == "brief-print":
            self._print()
        elif event.button.id == "brief-goto":
            self.dismiss("review")

    def action_close(self) -> None:
        self.dismiss()

    def action_print_brief(self) -> None:
        self._print()

    @classmethod
    def _plain(cls, line: str) -> str:
        return _strip_rich_tags(line)

    def _print(self) -> None:
        """Esporta il resoconto in Markdown (via callback dell'app)."""
        if self.on_print is None:
            return
        lines = self._evening_lines()
        text = "# " + T("brief_e_title", date=self.today) + "\n\n"
        text += "\n".join(self._plain(line) for line in lines) + "\n"
        try:
            path = self.on_print("evening", self.today, text)
        except Exception as exc:
            self.notify(T("n_exp_err", e=exc), severity="error")
            return
        self.notify(T("n_brief_printed", p=path))


class GoalsScreen(ModalScreen[dict | None]):
    """Imposta obiettivi giornaliero/settimanale (0 = disattivato)."""

    CSS = """
    #goals-box {
        width: 52;
        max-width: 90%;
        height: auto;
    }
    #goals-hint {
        color: $text-muted;
        margin-bottom: 1;
        height: auto;
    }
    #goals-box Input {
        margin-bottom: 1;
    }
    #goals-buttons {
        width: 100%;
        height: 3;
        margin-top: 1;
    }
    #goals-buttons Button {
        width: 1fr;
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Annulla"),
        Binding("ctrl+enter", "submit", "Salva", show=False),
        Binding("s", "submit", "Salva", show=False),
    ]

    def __init__(self, daily: int = 5, weekly: int = 25, pomo_daily: int = 8) -> None:
        super().__init__()
        self.daily = daily
        self.weekly = weekly
        self.pomo_daily = pomo_daily

    def compose(self) -> ComposeResult:
        with Vertical(id="goals-box"):
            yield Label(T("goals_title"), id="goals-title")
            yield Label(T("goals_hint"), id="goals-hint")
            yield Label(T("goals_daily"))
            yield Input(str(self.daily), id="goals-daily")
            yield Label(T("goals_weekly"))
            yield Input(str(self.weekly), id="goals-weekly")
            yield Label(T("goals_pomo"))
            yield Input(str(self.pomo_daily), id="goals-pomo")
            with Horizontal(id="goals-buttons"):
                yield Button(T("form_save"), id="goals-save", variant="default")
                yield Button(T("form_cancel"), id="goals-cancel", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#goals-daily", Input).focus()
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "goals-cancel":
            self.dismiss(None)
        elif event.button.id == "goals-save":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        try:
            daily = int(self.query_one("#goals-daily", Input).value.strip() or 0)
            weekly = int(self.query_one("#goals-weekly", Input).value.strip() or 0)
            pomo = int(self.query_one("#goals-pomo", Input).value.strip() or 0)
        except (ValueError, TypeError):
            self.notify(T("n_goals_int"), severity="error")
            return
        if not (0 <= daily <= 100 and 0 <= weekly <= 500 and 0 <= pomo <= 100):
            self.notify(T("n_goals_range"), severity="error")
            return
        self.dismiss({"daily": daily, "weekly": weekly, "pomo_daily": pomo})


class StatsScreen(ModalScreen[None]):
    """Screen to show productivity statistics."""

    CSS = """
    #stats-box {
        width: 58;
        max-width: 92%;
        height: 90%;
    }
    #stats-scroll {
        height: 1fr;
    }
    #stats-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #stats-section {
        height: auto;
        margin-bottom: 1;
    }
    .stats-line {
        height: auto;
        margin-bottom: 0;
    }
    .stats-caption {
        height: auto;
        margin-bottom: 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def __init__(
        self,
        all_todos: list[TodoItem],
        daily_goal: int = 5,
        weekly_goal: int = 25,
        pomo_goal: int = 8,
    ) -> None:
        super().__init__()
        self.all_todos = all_todos
        self.daily_goal = daily_goal
        self.weekly_goal = weekly_goal
        self.pomo_goal = pomo_goal

    STATS_SPAN = 14

    def _completed_by_date(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for t in self.all_todos:
            if t.completed_at:
                date_str = t.completed_at[:10]
                result[date_str] = result.get(date_str, 0) + 1
        return result

    def _pomodoros_by_date(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for t in self.all_todos:
            for ts in getattr(t, "pomodoro_log", []) or []:
                date_str = str(ts)[:10]
                result[date_str] = result.get(date_str, 0) + 1
        return result

    def _count_in_range(
        self, start: datetime.date, end: datetime.date, by_date: dict[str, int]
    ) -> int:
        count = 0
        d = start
        while d <= end:
            count += by_date.get(d.strftime("%Y-%m-%d"), 0)
            d += timedelta(days=1)
        return count

    def _series_14(self, by_date: dict[str, int]) -> tuple[list[int], list[str]]:
        today = datetime.now().date()
        values, labels = [], []
        for offset in range(self.STATS_SPAN - 1, -1, -1):
            d = today - timedelta(days=offset)
            date_str = d.strftime("%Y-%m-%d")
            values.append(by_date.get(date_str, 0))
            labels.append(date_str)
        return values, labels

    def _peak_caption(self, values: list[int], labels: list[str]) -> str:
        top = max(values) if values else 0
        if top <= 0:
            return T("stats_peak_none")
        day = labels[values.index(top)][8:10] + "/" + labels[values.index(top)][5:7]
        return T("stats_peak", n=top, d=day)

    def _axis_caption(self) -> str:
        today = datetime.now().date()
        start = today - timedelta(days=self.STATS_SPAN - 1)
        return T(
            "stats_axis", start=start.strftime("%d/%m"), today=today.strftime("%d/%m")
        )

    HEATMAP_WEEKS = 26
    HEATMAP_LEVELS = ("·", "░", "▒", "▓", "█")

    def _heatmap_26(self) -> str:
        """Heatmap 🍅 stile GitHub: 26 settimane x 7 giorni, oggi evidenziato."""
        today = datetime.now().date()
        monday_this = today - timedelta(days=today.weekday())
        start = monday_this - timedelta(weeks=self.HEATMAP_WEEKS - 1)
        pomo_by_date = self._pomodoros_by_date()
        grid: list[list[int]] = [[0] * self.HEATMAP_WEEKS for _ in range(7)]
        future: list[list[bool]] = [[False] * self.HEATMAP_WEEKS for _ in range(7)]
        for c in range(self.HEATMAP_WEEKS):
            for r in range(7):
                d = start + timedelta(days=c * 7 + r)
                if d > today:
                    future[r][c] = True
                    continue
                grid[r][c] = pomo_by_date.get(d.strftime("%Y-%m-%d"), 0)

        def cell(v: int) -> str:
            if v <= 0:
                return self.HEATMAP_LEVELS[0]
            if v == 1:
                return self.HEATMAP_LEVELS[1]
            if v <= 3:
                return self.HEATMAP_LEVELS[2]
            if v <= 5:
                return self.HEATMAP_LEVELS[3]
            return self.HEATMAP_LEVELS[4]

        month_row = [" "] * self.HEATMAP_WEEKS
        prev_month = -1
        for c in range(self.HEATMAP_WEEKS):
            m = (start + timedelta(days=c * 7)).month
            if m != prev_month:
                month_row[c] = months()[m][:1].lower()
                prev_month = m
        lines = ["    " + "".join(month_row)]
        for r in range(7):
            row = [f"{days_short()[r]} "]
            for c in range(self.HEATMAP_WEEKS):
                if future[r][c]:
                    row.append(" ")
                elif start + timedelta(days=c * 7 + r) == today:
                    row.append(f"[bold yellow]{cell(grid[r][c])}[/]")
                else:
                    row.append(cell(grid[r][c]))
            lines.append("".join(row))
        return "\n".join(lines)

    def _render_14_histogram(self, values: list[int], labels: list[str]) -> str:
        """Istogramma 14 colonne a larghezza fissa: barra + giorno sotto, oggi evidenziato."""
        mx = max(values) if values and max(values) > 0 else 1
        rows: list[str] = []
        for level in range(4, 0, -1):
            cells = []
            for i, v in enumerate(values):
                filled = "██" if v * 4 >= mx * level else "  "
                if i == len(values) - 1:
                    cells.append(f"[bold yellow]{filled}[/]")
                elif v == mx:
                    cells.append(f"[green]{filled}[/]")
                else:
                    cells.append(filled)
            rows.append(" ".join(cells))
        day_cells = []
        for i, lab in enumerate(labels):
            dd = lab[8:10]
            day_cells.append(f"[bold]{dd}[/]" if i == len(labels) - 1 else dd)
        rows.append(" ".join(day_cells))
        return "\n".join(rows)

    def _streak(self, by_date: dict[str, int]) -> int:
        """Giorni consecutivi con >=1 completamento (oggi o da ieri se oggi e' a zero)."""
        today = datetime.now().date()
        d = (
            today
            if by_date.get(today.strftime("%Y-%m-%d"), 0) > 0
            else today - timedelta(days=1)
        )
        streak = 0
        while by_date.get(d.strftime("%Y-%m-%d"), 0) > 0:
            streak += 1
            d -= timedelta(days=1)
        return streak

    def _goal_streaks(self, by_date: dict[str, int]) -> dict:
        """Streak attuali e massime vs obiettivi giornaliero/settimanale."""
        today = datetime.now().date()
        dg, wg = self.daily_goal, self.weekly_goal
        out = {"d_cur": 0, "d_max": 0, "w_cur": 0, "w_max": 0, "w_now": 0}
        if dg > 0:
            d = (
                today
                if by_date.get(today.strftime("%Y-%m-%d"), 0) >= dg
                else today - timedelta(days=1)
            )
            while by_date.get(d.strftime("%Y-%m-%d"), 0) >= dg:
                out["d_cur"] += 1
                d -= timedelta(days=1)
            if by_date:
                first = min(datetime.strptime(k, "%Y-%m-%d").date() for k in by_date)
                dd, run = first, 0
                while dd <= today:
                    if by_date.get(dd.strftime("%Y-%m-%d"), 0) >= dg:
                        run += 1
                        out["d_max"] = max(out["d_max"], run)
                    else:
                        run = 0
                    dd += timedelta(days=1)
        if wg > 0 and by_date:
            weeks: dict[tuple[int, int], int] = {}
            for k, v in by_date.items():
                try:
                    dt = datetime.strptime(k, "%Y-%m-%d").date()
                except ValueError:
                    continue
                wk = (dt.isocalendar()[0], dt.isocalendar()[1])
                weeks[wk] = weeks.get(wk, 0) + v
            cur_wk = (today.isocalendar()[0], today.isocalendar()[1])
            out["w_now"] = weeks.get(cur_wk, 0)
            wk = cur_wk if out["w_now"] >= wg else self._prev_week(cur_wk)
            while weeks.get(wk, 0) >= wg:
                out["w_cur"] += 1
                wk = self._prev_week(wk)
            run = 0
            for wk in sorted(weeks):
                if weeks[wk] >= wg:
                    run += 1
                    out["w_max"] = max(out["w_max"], run)
                else:
                    run = 0
        return out

    @staticmethod
    def _prev_week(wk: tuple[int, int]) -> tuple[int, int]:
        y, w = wk
        if w > 1:
            return (y, w - 1)
        prev_dec28 = datetime(y - 1, 12, 28).date()
        return (y - 1, prev_dec28.isocalendar()[1])

    TIME_SLOTS: tuple[tuple[str, int, int], ...] = (
        (T("slot_night"), 0, 6),
        (T("slot_morning"), 6, 12),
        (T("slot_afternoon"), 12, 18),
        (T("slot_evening"), 18, 24),
    )

    @staticmethod
    def _hour_of(ts: str) -> int | None:
        try:
            h = int(str(ts)[11:13])
            return h if 0 <= h <= 23 else None
        except (ValueError, TypeError, IndexError):
            return None

    def _slot_counts(self, days: int = 30) -> list[tuple[str, int, int]]:
        """(fascia, completati, pomodori) negli ultimi N giorni."""
        start = (datetime.now().date() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        comp = [0] * len(self.TIME_SLOTS)
        pomo = [0] * len(self.TIME_SLOTS)
        for t in self.all_todos:
            if t.completed_at and t.completed_at[:10] >= start:
                h = self._hour_of(t.completed_at)
                if h is not None:
                    for i, (_, lo, hi) in enumerate(self.TIME_SLOTS):
                        if lo <= h < hi:
                            comp[i] += 1
                            break
            for ts in getattr(t, "pomodoro_log", []) or []:
                if str(ts)[:10] >= start:
                    h = self._hour_of(str(ts))
                    if h is not None:
                        for i, (_, lo, hi) in enumerate(self.TIME_SLOTS):
                            if lo <= h < hi:
                                pomo[i] += 1
                                break
        return [
            (name, comp[i], pomo[i]) for i, (name, _, _) in enumerate(self.TIME_SLOTS)
        ]

    def _weekday_counts(self, weeks: int = 8) -> list[tuple[str, int, int]]:
        """(giorno Lun-Dom, completati, pomodori) nelle ultime N settimane."""
        start = (datetime.now().date() - timedelta(weeks=weeks)).strftime("%Y-%m-%d")
        comp = [0] * 7
        pomo = [0] * 7
        for t in self.all_todos:
            if t.completed_at and t.completed_at[:10] >= start:
                try:
                    wd = (
                        datetime.strptime(t.completed_at[:10], "%Y-%m-%d")
                        .date()
                        .weekday()
                    )
                    comp[wd] += 1
                except ValueError:
                    pass
            for ts in getattr(t, "pomodoro_log", []) or []:
                if str(ts)[:10] >= start:
                    try:
                        wd = (
                            datetime.strptime(str(ts)[:10], "%Y-%m-%d").date().weekday()
                        )
                        pomo[wd] += 1
                    except ValueError:
                        pass
        return [(days_short()[i], comp[i], pomo[i]) for i in range(7)]

    def _punctuality(self) -> tuple[int, int, int]:
        """(puntuali, con scadenza, %) sui completati datati che avevano una scadenza."""
        on_time = total = 0
        for t in self.all_todos:
            if t.done and t.completed_at and t.due:
                total += 1
                if t.completed_at[:10] <= _due_date_part(t.due):
                    on_time += 1
        pct = round(on_time * 100 / total) if total else 0
        return on_time, total, pct

    def _project_breakdown(self, days: int = 7) -> list[tuple[str, int, int]]:
        """(progetto, completati, pomodori) negli ultimi N giorni, i migliori prima."""
        start = (datetime.now().date() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        comp: dict[str, int] = {}
        for t in self.all_todos:
            if t.completed_at and t.completed_at[:10] >= start:
                proj = t.project or "—"
                comp[proj] = comp.get(proj, 0) + 1
        pomo: dict[str, int] = {}
        for t in self.all_todos:
            for ts in getattr(t, "pomodoro_log", []) or []:
                if str(ts)[:10] >= start:
                    proj = t.project or "—"
                    pomo[proj] = pomo.get(proj, 0) + 1
        rows = [(p, comp.get(p, 0), pomo.get(p, 0)) for p in set(comp) | set(pomo)]
        rows.sort(key=lambda r: (r[1] + r[2], r[1]), reverse=True)
        return rows[:8]

    def compose(self) -> ComposeResult:
        by_date = self._completed_by_date()
        pomo_by_date = self._pomodoros_by_date()
        today = datetime.now().date()
        span_ago = today - timedelta(days=self.STATS_SPAN - 1)
        week_ago = today - timedelta(days=6)
        month_ago = today - timedelta(days=29)
        today_c = by_date.get(today.strftime("%Y-%m-%d"), 0)
        week_c = self._count_in_range(week_ago, today, by_date)
        month_c = self._count_in_range(month_ago, today, by_date)
        total_done = sum(1 for t in self.all_todos if t.done)
        dated_done = sum(by_date.values())
        undated_done = total_done - dated_done
        alta = sum(1 for t in self.all_todos if t.done and t.priority == Priority.HIGH)
        media = sum(
            1 for t in self.all_todos if t.done and t.priority == Priority.MEDIUM
        )
        bassa = sum(1 for t in self.all_todos if t.done and t.priority == Priority.LOW)
        pomo_today = pomo_by_date.get(today.strftime("%Y-%m-%d"), 0)
        pomo_14 = self._count_in_range(span_ago, today, pomo_by_date)
        pomo_total = sum(t.pomodoros for t in self.all_todos)
        pomo_dated = sum(pomo_by_date.values())
        pomo_undated = pomo_total - pomo_dated
        streak = self._streak(by_date)
        gs = self._goal_streaks(by_date)
        done_values, done_labels = self._series_14(by_date)
        pomo_values, _ = self._series_14(pomo_by_date)

        with Vertical(id="stats-box"):
            yield Label(T("stats_title"), id="stats-title")
            with VerticalScroll(id="stats-scroll"):
                if self.daily_goal > 0:
                    yield Static(
                        T(
                            "stats_goal_today",
                            done=today_c,
                            goal=self.daily_goal,
                            cur=gs["d_cur"],
                            mx=gs["d_max"],
                        ),
                        id="stats-section",
                    )
                else:
                    yield Static(T("stats_goal_off"), id="stats-section")
                if self.weekly_goal > 0:
                    yield Static(
                        T(
                            "stats_week",
                            now=gs["w_now"],
                            goal=self.weekly_goal,
                            cur=gs["w_cur"],
                            mx=gs["w_max"],
                        ),
                        classes="stats-line",
                    )
                yield Static(
                    T("stats_serie", n=streak) if streak else T("stats_serie_off"),
                    classes="stats-line",
                )
                yield Static(T("stats_today", n=today_c), classes="stats-line")
                yield Static(T("stats_7", n=week_c), classes="stats-line")
                yield Static(T("stats_30", n=month_c), classes="stats-line")
                yield Static(T("stats_tot", n=total_done), classes="stats-line")
                if undated_done:
                    yield Static(
                        T("stats_undated", n=undated_done), classes="stats-line"
                    )
                yield Static(
                    T("stats_prio", a=alta, m=media, b=bassa),
                    classes="stats-line",
                )
                proj_rows = self._project_breakdown(7)
                if proj_rows:
                    yield Label(T("stats_proj_t"), classes="stats-line")
                    for proj, nc, np in proj_rows:
                        yield Static(
                            f"  [blue]{proj}[/]: {nc} · {np}", classes="stats-line"
                        )
                yield Label(T("stats_when_t"), classes="stats-line")
                slot_rows = {n: (c, p) for n, c, p in self._slot_counts(30)}
                for name, lo, hi in self.TIME_SLOTS:
                    sc, sp = slot_rows.get(name, (0, 0))
                    yield Static(
                        f"  {name} ({lo}-{hi}): {sc} · {sp}", classes="stats-line"
                    )
                yield Label(T("stats_wday_t"), classes="stats-line")
                for g, wc, wp in self._weekday_counts(8):
                    yield Static(f"  {g}: {wc} · {wp}", classes="stats-line")
                pt_on, pt_tot, pt_pct = self._punctuality()
                if pt_tot:
                    yield Static(
                        T("stats_punct", pct=pt_pct, ok=pt_on, tot=pt_tot),
                        classes="stats-line",
                    )
                pomo_goal_txt = (
                    f"{pomo_today}/{self.pomo_goal}"
                    if self.pomo_goal > 0
                    else str(pomo_today)
                )
                yield Static(
                    T("stats_pomo", t=pomo_goal_txt, f=pomo_14, tot=pomo_total),
                    classes="stats-line",
                )
                if pomo_undated:
                    yield Static(
                        T("stats_undated", n=pomo_undated), classes="stats-line"
                    )
                yield Label(T("stats_done14"), classes="stats-line")
                yield Static(
                    self._render_14_histogram(done_values, done_labels),
                    id="stats-hist-done",
                )
                yield Static(f" [dim]{self._axis_caption()}[/]", classes="stats-line")
                yield Static(
                    f" [dim]{self._peak_caption(done_values, done_labels)} · {T('stats_last_today')}[/]",
                    classes="stats-caption",
                )
                yield Label(T("stats_pomo14"), classes="stats-line")
                yield Static(
                    self._render_14_histogram(pomo_values, done_labels),
                    id="stats-hist-pomo",
                )
                yield Static(f" [dim]{self._axis_caption()}[/]", classes="stats-line")
                yield Static(
                    f" [dim]{self._peak_caption(pomo_values, done_labels)} · {T('stats_last_today')}[/]",
                    classes="stats-caption",
                )
                yield Label(T("stats_heat_t"), classes="stats-line")
                yield Static(self._heatmap_26(), id="stats-heatmap")
                yield Static(T("stats_heat_leg"), classes="stats-caption")
            yield Button(T("ui_close_esc"), id="stats-close", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "stats-close":
            self.dismiss()

    def on_mount(self) -> None:
        try:
            self.query_one("#stats-close", Button).focus()
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss()


class KeysScreen(ModalScreen[None]):
    """Popup con tutte le combinazioni di tasti (voce Tasti del menu)."""

    CSS = """
    #keys-box {
        width: 66;
        max-width: 92%;
        max-height: 90%;
    }
    #keys-list {
        height: auto;
        max-height: 24;
        margin-bottom: 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def compose(self) -> ComposeResult:
        with Vertical(id="keys-box"):
            yield Label(f"[b]{T('keys_title')}[/b]", id="keys-title")
            with VerticalScroll(id="keys-list"):
                for section, rows in key_sections():
                    yield Label(f"[b]{section}[/b]")
                    for key, desc in rows:
                        yield Static(f"  [b]{key}[/b]  {desc}")
            yield Button(f"{T('b_close')} [escape]", id="keys-close", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "keys-close":
            self.dismiss()

    def on_mount(self) -> None:
        try:
            self.query_one("#keys-close", Button).focus()
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss()


class SettingsScreen(ModalScreen[dict | None]):
    """Impostazioni app: tema, vista, obiettivi, durate pomodoro."""

    CSS = """
    #set-box {
        width: 60;
        max-width: 92%;
        height: 90%;
        max-height: 90%;
    }
    #set-body {
        width: 100%;
        height: 1fr;
    }
    #set-body Input {
        margin-bottom: 1;
    }
    #set-body Label {
        margin-bottom: 0;
    }
    #set-buttons {
        width: 100%;
        height: 3;
        dock: bottom;
        margin-top: 1;
    }
    #set-buttons Button {
        width: 1fr;
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Annulla"),
        Binding("ctrl+enter", "submit", "Salva", show=False),
        Binding("s", "submit", "Salva", show=False),
    ]

    def __init__(self, themes: list[str], current: dict) -> None:
        super().__init__()
        self.themes = themes
        self.current = dict(current)

    def compose(self) -> ComposeResult:
        filt = self.current.get("filter_state") or "tutti"
        with Vertical(id="set-box"):
            yield Label(T("set_title"), id="set-title")
            with VerticalScroll(id="set-body", can_focus=False):
                yield Label(T("set_theme"))
                yield Select(
                    [(t, t) for t in self.themes],
                    value=self.current.get("theme", "matrix"),
                    id="set-theme",
                )
                yield Label(T("set_lang"))
                yield Select(
                    [
                        (T("set_lang_auto"), "auto"),
                        ("Italiano", "it"),
                        ("English", "en"),
                    ],
                    value=self.current.get("lang", "auto"),
                    id="set-lang",
                )
                yield Label(T("set_kanban"))
                yield Select(
                    [(T("set_kanban_on"), True), (T("set_kanban_off"), False)],
                    value=bool(self.current.get("kanban_visible", True)),
                    id="set-kanban",
                )
                yield Label(T("set_filter"))
                yield Select(
                    [
                        (T("set_filter_attivo"), "attivo"),
                        (T("set_filter_sospeso"), "in_sospeso"),
                        (T("set_filter_completati"), "completati"),
                        (T("set_filter_tutti"), "tutti"),
                    ],
                    value=filt,
                    id="set-filter",
                )
                yield Label(T("set_daily"))
                yield Input(str(self.current.get("daily_goal", 5)), id="set-daily")
                yield Label(T("set_weekly"))
                yield Input(str(self.current.get("weekly_goal", 25)), id="set-weekly")
                yield Label(T("set_pomo"))
                yield Input(
                    str(self.current.get("pomo_daily_goal", 8)), id="set-pomo-goal"
                )
                yield Label(T("set_hours"))
                yield Input(str(self.current.get("day_hours", 6)), id="set-hours")
                yield Label(T("set_focus"))
                yield Input(str(self.current.get("focus_min", 25)), id="set-focus")
                yield Label(T("set_short"))
                yield Input(str(self.current.get("short_min", 5)), id="set-short")
                yield Label(T("set_long"))
                yield Input(str(self.current.get("long_min", 15)), id="set-long")
                yield Label(T("set_every"))
                yield Input(str(self.current.get("long_every", 4)), id="set-every")
                yield Label(T("set_reminder"))
                yield Input(
                    str(self.current.get("reminder_min", 10)), id="set-reminder"
                )
                yield Label(T("set_sounds"))
                yield Select(
                    [(T("set_yes"), True), (T("set_no"), False)],
                    value=bool(self.current.get("sounds", True)),
                    id="set-sounds",
                )
            with Horizontal(id="set-buttons"):
                yield Button(T("form_save"), id="set-save", variant="default")
                yield Button(T("form_cancel"), id="set-cancel", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#set-theme", Select).focus()
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "set-cancel":
            self.dismiss(None)
        elif event.button.id == "set-save":
            self._submit()

    def _num(self, vid: str, lo: int, hi: int) -> int | None:
        try:
            v = int(self.query_one(f"#{vid}", Input).value.strip() or 0)
        except (ValueError, TypeError):
            self.query_one(f"#{vid}", Input).focus()
            self.notify(T("n_set_num", lo=lo, hi=hi), severity="error")
            return None
        if not (lo <= v <= hi):
            self.query_one(f"#{vid}", Input).focus()
            self.notify(T("n_set_range", lo=lo, hi=hi), severity="error")
            return None
        return v

    def _submit(self) -> None:
        theme = self.query_one("#set-theme", Select).value
        kanban = self.query_one("#set-kanban", Select).value
        filt = self.query_one("#set-filter", Select).value
        lang = self.query_one("#set-lang", Select).value
        daily = self._num("set-daily", 0, 100)
        weekly = self._num("set-weekly", 0, 500)
        pomo = self._num("set-pomo-goal", 0, 100)
        hours = self._num("set-hours", 1, 16)
        focus = self._num("set-focus", 1, 180)
        short = self._num("set-short", 1, 60)
        longm = self._num("set-long", 1, 60)
        every = self._num("set-every", 2, 12)
        reminder = self._num("set-reminder", 0, 120)
        sounds = self.query_one("#set-sounds", Select).value
        if None in (daily, weekly, pomo, focus, short, longm, every, reminder, hours):
            return
        self.dismiss(
            {
                "theme": theme,
                "kanban_visible": bool(kanban),
                "filter_state": None if filt == "tutti" else filt,
                "daily_goal": daily,
                "weekly_goal": weekly,
                "pomo_daily_goal": pomo,
                "day_hours": hours,
                "focus_min": focus,
                "short_min": short,
                "long_min": longm,
                "long_every": every,
                "lang": lang if lang in ("auto", "it", "en") else "auto",
                "reminder_min": reminder,
                "sounds": bool(sounds),
            }
        )


class ArchiveScreen(ModalScreen[tuple | None]):
    """Archivio completati: ripristina singoli o tutti."""

    CSS = """
    #arc-box {
        width: 64;
        max-width: 92%;
        max-height: 88%;
    }
    #arc-list {
        height: auto;
        max-height: 22;
        margin-bottom: 1;
    }
    #arc-list Button {
        width: 100%;
        min-width: 16;
        height: 3;
        margin-bottom: 1;
    }
    #arc-actions {
        width: 100%;
        height: 3;
    }
    #arc-actions Button {
        width: 1fr;
        min-width: 12;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def __init__(self, archived: list[TodoItem]) -> None:
        super().__init__()
        self.archived = archived

    def compose(self) -> ComposeResult:
        with Vertical(id="arc-box"):
            yield Label(T("arc_title", n=len(self.archived)), id="arc-title")
            with VerticalScroll(id="arc-list"):
                if not self.archived:
                    yield Label(T("arc_empty"))
                for i, t in enumerate(self.archived):
                    when = (t.completed_at or "?")[:10]
                    proj = f" @{t.project}" if t.project else ""
                    yield Button(
                        f"#{t.id} {t.title[:36]}{proj} ({when})",
                        id=f"arc-{i}",
                        variant="default",
                    )
            with Horizontal(id="arc-actions"):
                yield Button(T("arc_all"), id="arc-all", variant="default")
                yield Button(T("ui_close_esc"), id="arc-close", variant="default")

    def on_mount(self) -> None:
        try:
            first = self.query("#arc-list Button")
            (first.first() if first else self.query_one("#arc-close", Button)).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "arc-close":
            self.dismiss(None)
        elif bid == "arc-all":
            self.dismiss(("all", None))
        elif bid.startswith("arc-"):
            try:
                self.dismiss(("one", int(bid[len("arc-") :])))
            except ValueError:
                pass

    def action_close(self) -> None:
        self.dismiss(None)


class RestoreScreen(ModalScreen[str | None]):
    """Sceglie uno snapshot da ripristinare."""

    CSS = """
    #rst-box {
        width: 64;
        max-width: 92%;
        max-height: 88%;
    }
    #rst-list {
        height: auto;
        max-height: 20;
        margin-bottom: 1;
    }
    #rst-list Button {
        width: 100%;
        min-width: 16;
        height: 3;
        margin-bottom: 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def __init__(self, snapshots: list[Path]) -> None:
        super().__init__()
        self.snapshots = snapshots

    def compose(self) -> ComposeResult:
        with Vertical(id="rst-box"):
            yield Label(T("rst_title"), id="rst-title")
            with VerticalScroll(id="rst-list"):
                if not self.snapshots:
                    yield Label(T("rst_empty"))
                for i, p in enumerate(self.snapshots):
                    info = snapshot_info(p)
                    files = info.get("files", {})
                    n = files.get("todos", "?")
                    kb = info.get("size", 0) // 1024
                    yield Button(
                        T("rst_row", created=info.get("created", "?"), n=n, kb=kb),
                        id=f"rst-{i}",
                        variant="default",
                    )
            yield Button(T("ui_close_esc"), id="rst-close", variant="default")

    def on_mount(self) -> None:
        try:
            first = self.query("#rst-list Button")
            (first.first() if first else self.query_one("#rst-close", Button)).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "rst-close":
            self.dismiss(None)
        elif bid.startswith("rst-"):
            try:
                self.dismiss(str(self.snapshots[int(bid[len("rst-") :])]))
            except (ValueError, IndexError):
                pass

    def action_close(self) -> None:
        self.dismiss(None)


class WelcomeScreen(ModalScreen[str | None]):
    """Benvenuto con scelta demo/vuoto (solo al primo avvio senza task)."""

    CSS = """
    #wel-box {
        width: 60;
        max-width: 92%;
        height: auto;
    }
    #wel-body {
        text-align: center;
        margin-bottom: 1;
        height: auto;
    }
    #wel-buttons {
        width: 100%;
        height: 3;
    }
    #wel-buttons Button {
        width: 1fr;
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "empty", "Vuoto")]

    def compose(self) -> ComposeResult:
        with Vertical(id="wel-box"):
            yield Label(T("welcome_title"), id="wel-title")
            yield Label(T("welcome_body"), id="wel-body")
            with Horizontal(id="wel-buttons"):
                yield Button(T("welcome_demo"), id="wel-demo", variant="default")
                yield Button(T("welcome_empty"), id="wel-empty", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#wel-demo", Button).focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "wel-empty":
            self.dismiss("empty")
        elif event.button.id == "wel-demo":
            self.dismiss("demo")

    def action_empty(self) -> None:
        self.dismiss("empty")


class LockScreen(ModalScreen[bool]):
    """Blocco password all'avvio (solo se dati cifrati)."""

    CSS = """
    #lock-box {
        width: 52;
        max-width: 90%;
        height: auto;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }
    #lock-title {
        text-align: center;
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
        height: auto;
    }
    #lock-hint {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
        height: auto;
    }
    #lock-pw {
        margin-bottom: 1;
    }
    #lock-buttons {
        width: 100%;
        height: 3;
    }
    #lock-buttons Button {
        width: 1fr;
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "abort", "Esci")]

    def compose(self) -> ComposeResult:
        with Vertical(id="lock-box"):
            yield Label("[b]🔒 Tasko protetto[/b]", id="lock-title")
            yield Label(T("lock_hint"), id="lock-hint")
            yield Input(placeholder="Password", password=True, id="lock-pw")
            with Horizontal(id="lock-buttons"):
                yield Button(T("lock_open"), id="lock-ok", variant="default")
                yield Button(T("lock_exit"), id="lock-exit", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#lock-pw", Input).focus()
        except Exception:
            pass

    def action_abort(self) -> None:
        self.dismiss(False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "lock-exit":
            self.dismiss(False)
        elif event.button.id == "lock-ok":
            self._submit()

    def _submit(self) -> None:
        pw_input = self.query_one("#lock-pw", Input)
        password = pw_input.value
        if not password:
            pw_input.focus()
            return
        ok = True
        for name, path in _backup_sources():
            if name == "config":
                continue
            try:
                if path.exists() and not _crypto.try_password(password, path):
                    ok = False
                    break
            except OSError:
                pass
        if not ok:
            pw_input.value = ""
            pw_input.disabled = True
            self.notify(T("n_lock_bad"), severity="error")
            self.set_timer(1.0, self._reenable)
            return
        _crypto.set_key(_crypto.password_to_key(password))
        self.dismiss(True)

    def _reenable(self) -> None:
        try:
            pw_input = self.query_one("#lock-pw", Input)
            pw_input.disabled = False
            pw_input.focus()
        except Exception:
            pass


class PasswordScreen(ModalScreen[list[str] | None]):
    """Raccoglie 1-3 password (niente logica: valida il chiamante)."""

    CSS = """
    #pw-box {
        width: 52;
        max-width: 90%;
        height: auto;
    }
    #pw-box Input {
        margin-bottom: 1;
    }
    #pw-box Label {
        margin-bottom: 0;
    }
    #pw-buttons {
        width: 100%;
        height: 3;
        margin-top: 1;
    }
    #pw-buttons Button {
        width: 1fr;
        min-width: 14;
        height: 3;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Annulla"),
        Binding("ctrl+enter", "submit", "Conferma", show=False),
        Binding("s", "submit", "Conferma", show=False),
    ]

    def __init__(self, title_key: str, fields: list[str], validate=None) -> None:
        super().__init__()
        self.title_key = title_key
        self.fields = fields
        self._validate = validate

    def compose(self) -> ComposeResult:
        with Vertical(id="pw-box"):
            yield Label(T(self.title_key), id="pw-title")
            with Vertical(id="pw-body"):
                for i, label_key in enumerate(self.fields):
                    yield Label(T(label_key))
                    yield Input(password=True, id=f"pw-{i}")
            with Horizontal(id="pw-buttons"):
                yield Button(T("form_save"), id="pw-ok", variant="default")
                yield Button(T("form_cancel"), id="pw-cancel", variant="default")

    def on_mount(self) -> None:
        try:
            self.query_one("#pw-0", Input).focus()
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "pw-cancel":
            self.dismiss(None)
        elif event.button.id == "pw-ok":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def _submit(self) -> None:
        try:
            values = [
                self.query_one(f"#pw-{i}", Input).value for i in range(len(self.fields))
            ]
        except Exception:
            return
        if self._validate is not None:
            err = self._validate(values)
            if err:
                self.notify(err, severity="error")
                try:
                    self.query_one("#pw-0", Input).focus()
                except Exception:
                    pass
                return
        self.dismiss(values)


class SecurityScreen(ModalScreen[str | None]):
    """Stato cifratura + azioni (dismiss 'enable'/'change'/'disable'/None)."""

    CSS = """
    #sec-box {
        width: 56;
        max-width: 92%;
        height: auto;
    }
    #sec-status {
        text-align: center;
        margin-bottom: 1;
        height: auto;
    }
    #sec-hint {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
        height: auto;
    }
    #sec-buttons {
        width: 100%;
        height: auto;
    }
    #sec-buttons Button {
        width: 100%;
        min-width: 0;
        height: 3;
        margin-bottom: 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def __init__(self, enabled: bool) -> None:
        super().__init__()
        self.enabled = enabled

    def compose(self) -> ComposeResult:
        with Vertical(id="sec-box"):
            yield Label(T("sec_title"), id="sec-title")
            yield Label(T("sec_on") if self.enabled else T("sec_off"), id="sec-status")
            yield Label(T("sec_hint"), id="sec-hint")
            with Vertical(id="sec-buttons"):
                if self.enabled:
                    yield Button(T("sec_change"), id="sec-change", variant="default")
                    yield Button(T("sec_disable"), id="sec-disable", variant="default")
                else:
                    yield Button(T("sec_enable"), id="sec-enable", variant="default")
                yield Button(T("ui_close_esc"), id="sec-close", variant="default")

    def on_mount(self) -> None:
        try:
            first = self.query("#sec-buttons Button")
            if first:
                first.first().focus()
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        if bid == "sec-close":
            self.dismiss(None)
        elif bid in ("sec-enable", "sec-change", "sec-disable"):
            self.dismiss(bid[len("sec-") :])

    def action_close(self) -> None:
        self.dismiss(None)


# Soglie salute progetti (modificabili in un punto solo).


class HealthScreen(ModalScreen[None]):
    """Salute progetti: avanzamento, ritardi, momentum, verdetto."""

    CSS = """
    #hea-box {
        width: 64;
        max-width: 92%;
        height: 90%;
        max-height: 90%;
    }
    #hea-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
        height: auto;
    }
    #hea-hint {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
        height: auto;
    }
    #hea-list {
        height: 1fr;
        margin-bottom: 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

    def __init__(self, all_todos: list[TodoItem]) -> None:
        super().__init__()
        self.all_todos = all_todos

    def _rows(self) -> list[tuple]:
        """(progetto, verdetto, colore, fatti, tot, ritardo, momentum7). Peggiori prima."""
        today = datetime.now().date()
        today_s = today.strftime("%Y-%m-%d")
        w0 = (today - timedelta(days=6)).strftime("%Y-%m-%d")
        w1 = (today - timedelta(days=13)).strftime("%Y-%m-%d")
        agg: dict[str, dict] = {}

        def bucket(proj: str) -> dict:
            return agg.setdefault(
                proj, {"tot": 0, "done": 0, "late": 0, "now": 0, "prev": 0}
            )

        for t in self.all_todos:
            if t.is_subtask or not t.project:
                continue
            if t.done:
                a = bucket(t.project)
                a["tot"] += 1
                a["done"] += 1
                d = (t.completed_at or "")[:10]
                if w0 <= d <= today_s:
                    a["now"] += 1
                elif w1 <= d < w0:
                    a["prev"] += 1
            elif t.state != "completato":
                a = bucket(t.project)
                a["tot"] += 1
                if _due_date_part(t.due) and _due_date_part(t.due) < today_s:
                    a["late"] += 1
        out = []
        for proj, a in agg.items():
            if a["tot"] <= 0:
                continue
            ratio = a["done"] / a["tot"]
            if a["late"] >= HEALTH_CRIT_LATE or (
                ratio < HEALTH_CRIT_RATIO and a["late"] > 0
            ):
                verdict, color, rank = T("health_crit"), "red", 0
            elif a["late"] > 0 or (a["now"] - a["prev"]) < 0:
                verdict, color, rank = T("health_risk"), "yellow", 1
            else:
                verdict, color, rank = T("health_ok"), "green", 2
            out.append(
                (
                    rank,
                    proj,
                    verdict,
                    color,
                    a["done"],
                    a["tot"],
                    a["late"],
                    a["now"] - a["prev"],
                )
            )
        out.sort(key=lambda r: (r[0], r[1]))
        return [(p, v, c, d, t, ll, mm) for _, p, v, c, d, t, ll, mm in out]

    def compose(self) -> ComposeResult:
        with Vertical(id="hea-box"):
            yield Label(T("health_title"), id="hea-title")
            yield Label(T("health_hint"), id="hea-hint")
            with VerticalScroll(id="hea-list"):
                rows = self._rows()
                if not rows:
                    yield Label(T("health_empty"))
                for proj, verdict, color, done, tot, late, mom in rows:
                    sign = "+" if mom > 0 else ""
                    yield Label(f"[{color}][b]{verdict}[/b][/] {proj}")
                    yield Static(
                        T(
                            "health_row",
                            done=done,
                            tot=tot,
                            late=late,
                            mom=f"{sign}{mom}",
                        )
                    )
            yield Button(T("ui_close_esc"), id="hea-close", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "hea-close":
            self.dismiss()

    def on_mount(self) -> None:
        try:
            self.query_one("#hea-close", Button).focus()
        except Exception:
            pass

    def action_close(self) -> None:
        self.dismiss()


class MenuRow(Label):
    """Riga selezionabile del menu: focus + click, senza debounce dei Button."""

    can_focus = True

    async def on_click(self, event) -> None:
        # Gestito qui (la riga conosce il proprio id): alle coordinate
        # dell'evento in bolla non ci si puo' affidare (offset consumati).
        try:
            event.stop()
        except Exception:
            pass
        try:
            cb = getattr(self.screen, "menu_row_clicked", None)
            if callable(cb):
                cb(self.id or "")
        except Exception:
            pass


class MenuScreen(ModalScreen[str | None]):
    """Menu per funzioni: voci a sinistra, sottomenu a destra.

    Riceve categorie gia' risolte nella lingua corrente:
    [(titolo_cat, aiuto_cat, [(titolo, aiuto, action, shortcut|None), ...]), ...].
    La colonna di sinistra mostra solo i titoli delle categorie; click/Enter su
    una voce apre il sottomenu nel pannello di destra, un nuovo click sulla
    stessa voce lo chiude. Tutto allineato a sinistra, righe compatte
    (titolo + aiuto grigio sotto). Su/giu scorrono le voci (con anteprima) e le
    righe del sottomenu, destra/Enter entra ed esegue, sinistra torna alle voci,
    1-4 saltano alle categorie, la digitazione filtra le voci, esc chiude
    (prima svuota il filtro, poi il sottomenu, poi il menu).
    Il dismiss ritorna il nome dell'action scelta (es. "action_open_settings")
    oppure None se chiuso senza scelta. Non importa mai app/commands.

    Nota: le righe sono MenuRow (Label), non Button — cosi' il Click del mouse
    (gestito in on_click) e l'Enter da tastiera (binding activate) restano
    distinguibili (Button.Pressed li confonde) e non c'e' debounce -active.
    """

    CSS = """
    #menu-box {
        width: 80;
        max-width: 94%;
        height: 100%;
        max-height: 100%;
        dock: right;
    }
    #menu-title {
        text-align: left;
    }
    #menu-count {
        height: auto;
        color: $text-muted;
        text-align: left;
        margin-bottom: 1;
    }
    #menu-count.hidden {
        display: none;
    }
    #menu-main {
        width: 100%;
        height: 1fr;
        margin-bottom: 1;
    }
    #menu-bar {
        width: 24;
        height: 100%;
        margin-top: 1;
        margin-right: 1;
    }
    #menu-bar MenuRow {
        width: 100%;
        height: 1;
        margin-bottom: 1;
    }
    #menu-bar MenuRow.active {
        text-style: bold;
        background: $primary-darken-2;
    }
    #menu-bar MenuRow:focus, #menu-drop MenuRow:focus {
        background: $primary-darken-1;
        text-style: bold;
    }
    #menu-bar MenuRow:hover, #menu-drop MenuRow:hover {
        text-style: underline;
    }
    #menu-drop {
        width: 1fr;
        height: 100%;
        border: solid $primary;
        background: $surface;
    }
    #menu-drop .hidden {
        display: none;
    }
    #menu-drop MenuRow {
        width: 100%;
        height: 2;
        margin-bottom: 0;
    }
    #menu-empty {
        height: auto;
        padding: 1 2;
        color: $text-muted;
    }
    #menu-hint {
        height: auto;
        color: $text-muted;
        text-align: left;
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        Binding("left", "cursor_left", "Indietro", show=False),
        Binding("right", "cursor_right", "Avanti", show=False),
        Binding("up", "cursor_up", "Su", show=False),
        Binding("down", "cursor_down", "Giu", show=False),
        Binding("enter", "activate", "Apri/Esegui", show=False),
        Binding("space", "activate", "Apri/Esegui", show=False),
        Binding("backspace", "filter_back", "Cancella filtro", show=False),
        Binding("escape", "close_or_shrink", "Chiudi"),
    ]

    def __init__(
        self,
        categories: list[tuple[str, str, list[tuple[str, str, str, str | None]]]],
    ) -> None:
        super().__init__()
        self.categories = categories
        self._open_idx: int | None = None
        self._filter: str = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="menu-box"):
            yield Label(T("menu_title"), id="menu-title")
            yield Label(T("menu_hint"), id="menu-hint")
            yield Static("", id="menu-count", classes="hidden")
            with Horizontal(id="menu-main"):
                with Vertical(id="menu-bar"):
                    for i in range(len(self.categories)):
                        yield MenuRow("", id=f"menu-cat-{i}")
                with VerticalScroll(id="menu-drop", can_focus=False):
                    yield Static(T("menu_pick"), id="menu-empty")
                    for gi, (_ct, _ch, gitems) in enumerate(self.categories):
                        with Vertical(
                            id=f"menu-drop-{gi}", classes="menu-drop-group hidden"
                        ):
                            for gj in range(len(gitems)):
                                yield MenuRow("", id=f"menu-item-{gi}-{gj}")
            yield Button(T("ui_close_esc"), id="menu-close", variant="default")

    def on_mount(self) -> None:
        self._refresh_texts()
        self._open(0, focus_item=None)
        self._focus_cat(0)

    # -- helpers ---------------------------------------------------------
    def _cat_rows(self) -> list[MenuRow]:
        return [
            w
            for w in self.query("#menu-bar MenuRow")
            if (w.id or "").startswith("menu-cat-")
        ]

    def _group_visible(self, gi: int) -> bool:
        try:
            return not self.query_one(f"#menu-drop-{gi}").has_class("hidden")
        except Exception:
            return False

    def _item_rows(self) -> list[MenuRow]:
        out: list[MenuRow] = []
        for gi in range(len(self.categories)):
            if not self._group_visible(gi):
                continue
            try:
                out.extend(
                    w
                    for w in self.query(f"#menu-drop-{gi} MenuRow")
                    if not w.has_class("hidden")
                )
            except Exception:
                pass
        return out

    def _parse_item_id(self, fid: str) -> tuple[int, int] | None:
        parts = (fid or "").split("-")
        if len(parts) == 4 and parts[0] == "menu" and parts[1] == "item":
            try:
                return int(parts[2]), int(parts[3])
            except ValueError:
                return None
        return None

    def _focused_cat(self) -> int | None:
        fid = getattr(self.focused, "id", "") or ""
        if fid.startswith("menu-cat-"):
            try:
                return int(fid[len("menu-cat-") :])
            except ValueError:
                return None
        return None

    def _focused_item(self) -> tuple[int, int] | None:
        parsed = self._parse_item_id(getattr(self.focused, "id", "") or "")
        if parsed is None or not self._group_visible(parsed[0]):
            return None
        return parsed

    def _focus_cat(self, i: int) -> None:
        try:
            self.query_one(f"#menu-cat-{i}", MenuRow).focus()
        except Exception:
            pass

    def _focus_item(self, i: int, j: int) -> None:
        try:
            self.query_one(f"#menu-item-{i}-{j}", MenuRow).focus()
        except Exception:
            pass

    def _set_active(self, i: int | None) -> None:
        for k, w in enumerate(self._cat_rows()):
            try:
                w.set_class(k == i, "active")
            except Exception:
                pass
        self._refresh_bar()

    def _refresh_bar(self) -> None:
        for i in range(len(self.categories)):
            try:
                self.query_one(f"#menu-cat-{i}", MenuRow).update(self._cat_label(i))
            except Exception:
                pass

    # -- testi -----------------------------------------------------------
    def _cat_label(self, i: int) -> str:
        ct = self.categories[i][0]
        n = len(self.categories[i][2])
        mark = "›" if self._open_idx == i else " "
        return f"{mark} {ct} ({n})"

    def _item_text(self, t: str, h: str, sc: str | None) -> Text:
        title = f"{t} ({sc})" if sc else t
        return Text.from_markup(f"{title}\n[dim]{h}[/]")

    def _refresh_texts(self) -> None:
        for i in range(len(self.categories)):
            try:
                self.query_one(f"#menu-cat-{i}", MenuRow).update(self._cat_label(i))
            except Exception:
                pass
            for j, (t, h, _action, sc) in enumerate(self.categories[i][2]):
                try:
                    self.query_one(f"#menu-item-{i}-{j}", MenuRow).update(
                        self._item_text(t, h, sc)
                    )
                except Exception:
                    pass

    # -- filtro ----------------------------------------------------------
    def _match(self, gi: int, gj: int) -> bool:
        q = self._filter.strip().lower()
        if not q:
            return True
        try:
            t, h, _action, sc = self.categories[gi][2][gj]
        except IndexError:
            return False
        return q in f"{t} {h} {sc or ''}".lower()

    def _apply_filter(self) -> None:
        n = 0
        for gi in range(len(self.categories)):
            shown = 0
            for gj in range(len(self.categories[gi][2])):
                try:
                    w = self.query_one(f"#menu-item-{gi}-{gj}", MenuRow)
                except Exception:
                    continue
                if self._filter.strip():
                    ok = self._match(gi, gj)
                    try:
                        w.set_class(not ok, "hidden")
                    except Exception:
                        pass
                    if ok:
                        shown += 1
                else:
                    try:
                        w.remove_class("hidden")
                    except Exception:
                        pass
            try:
                grp = self.query_one(f"#menu-drop-{gi}")
                if self._filter.strip():
                    grp.set_class(shown == 0, "hidden")
                else:
                    grp.set_class(gi != self._open_idx, "hidden")
            except Exception:
                pass
            n += shown
        try:
            count = self.query_one("#menu-count", Static)
            empty = self.query_one("#menu-empty", Static)
            if self._filter.strip():
                count.update(T("menu_filter", q=self._filter, n=n))
                count.remove_class("hidden")
                if n == 0:
                    empty.update(T("menu_no_match", q=self._filter))
                    empty.remove_class("hidden")
                else:
                    empty.add_class("hidden")
            else:
                count.update("")
                count.add_class("hidden")
                if self._open_idx is None:
                    empty.update(T("menu_pick"))
                    empty.remove_class("hidden")
                else:
                    empty.add_class("hidden")
        except Exception:
            pass

    # -- apertura/chiusura sottomenu --------------------------------------
    def _open(self, i: int, focus_item: int | None = 0) -> None:
        if not 0 <= i < len(self.categories):
            return
        self._open_idx = i
        self._apply_filter()
        self._set_active(i)
        if focus_item is None:
            return

        def _defer() -> None:
            if self._open_idx != i:
                return
            self._focus_item(i, focus_item)

        try:
            self.call_after_refresh(_defer)
        except Exception:
            _defer()

    def _close_drop(self, focus_cat: bool = True) -> None:
        idx = self._open_idx
        self._open_idx = None
        self._apply_filter()
        self._set_active(None)
        if focus_cat:
            self._focus_cat(idx if idx is not None else 0)

    def _run_item(self, gi: int, gj: int) -> None:
        try:
            action = self.categories[gi][2][gj][2]
        except IndexError:
            return
        self.dismiss(action)

    # -- eventi ----------------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if (event.button.id or "") == "menu-close":
            self.dismiss(None)

    def menu_row_clicked(self, bid: str) -> None:
        if bid.startswith("menu-cat-"):
            try:
                idx = int(bid[len("menu-cat-") :])
            except ValueError:
                return
            if self._open_idx == idx:
                self._close_drop()
            else:
                self._open(idx)
        elif bid.startswith("menu-item-"):
            parsed = self._parse_item_id(bid)
            if parsed is None or not self._group_visible(parsed[0]):
                return
            self._run_item(*parsed)

    def on_key(self, event) -> None:
        ch = getattr(event, "character", None)
        if not ch or len(ch) != 1 or not ch.isprintable() or ch == " ":
            return
        if getattr(event, "ctrl", False) or getattr(event, "meta", False):
            return
        # Consuma il tasto qui: i binding globali dell'app (b, c, k, ...)
        # non devono scattare mentre si filtra nel menu.
        try:
            event.prevent_default()
            event.stop()
        except Exception:
            pass
        if ch in ("1", "2", "3", "4") and not self._filter.strip():
            idx = int(ch) - 1
            if idx < len(self.categories):
                self._open(idx)
            return
        self._filter += ch
        self._apply_filter()

    # -- tastiera: frecce, invio, esc -------------------------------------
    def action_activate(self) -> None:
        fid = getattr(self.focused, "id", "") or ""
        if fid == "menu-close":
            return
        cat = self._focused_cat()
        if cat is not None:
            self._open(cat, focus_item=0)
            return
        item = self._focused_item()
        if item is not None:
            self._run_item(*item)

    def action_cursor_left(self) -> None:
        focused = self._focused_item()
        if focused is not None:
            self._focus_cat(focused[0])

    def action_cursor_right(self) -> None:
        cat = self._focused_cat()
        if cat is not None:
            self._open(cat, focus_item=0)
        elif self._open_idx is None and not self._filter.strip():
            self._open(0, focus_item=0)

    def action_cursor_down(self) -> None:
        focused = self._focused_item()
        if focused is not None:
            rows = self._item_rows()
            ids = [w.id for w in rows]
            try:
                pos = ids.index(f"menu-item-{focused[0]}-{focused[1]}")
            except ValueError:
                pos = -1
            if rows:
                nxt = rows[(pos + 1) % len(rows)]
                try:
                    nxt.focus()
                except Exception:
                    pass
            return
        cat = self._focused_cat()
        if cat is None:
            cat = self._open_idx if self._open_idx is not None else 0
        if self._filter.strip():
            rows = self._item_rows()
            if rows:
                try:
                    rows[0].focus()
                except Exception:
                    pass
            return
        nxt = (cat + 1) % len(self.categories)
        self._open(nxt, focus_item=None)
        self._focus_cat(nxt)

    def action_cursor_up(self) -> None:
        focused = self._focused_item()
        if focused is not None:
            if self._filter.strip():
                rows = self._item_rows()
                ids = [w.id for w in rows]
                try:
                    pos = ids.index(f"menu-item-{focused[0]}-{focused[1]}")
                except ValueError:
                    pos = 0
                if rows:
                    try:
                        rows[(pos - 1) % len(rows)].focus()
                    except Exception:
                        pass
                return
            if focused[1] <= 0:
                self._focus_cat(focused[0])
            else:
                self._focus_item(focused[0], focused[1] - 1)
            return
        cat = self._focused_cat()
        if cat is None:
            cat = self._open_idx if self._open_idx is not None else 0
        if self._filter.strip():
            rows = self._item_rows()
            if rows:
                try:
                    rows[-1].focus()
                except Exception:
                    pass
            return
        nxt = (cat - 1) % len(self.categories)
        self._open(nxt, focus_item=None)
        self._focus_cat(nxt)

    def action_filter_back(self) -> None:
        if self._filter:
            self._filter = self._filter[:-1]
            self._apply_filter()

    def action_close_or_shrink(self) -> None:
        if self._filter.strip():
            self._filter = ""
            self._apply_filter()
            return
        if self._open_idx is not None:
            self._close_drop()
        else:
            self.dismiss(None)
