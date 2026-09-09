"""TUI To-Do application built with Textual."""

import calendar
import json
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.command import CommandPalette, DiscoveryHit, Hit, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Static,
    TextArea,
)

try:
    from src.lang import (
        T,
        days_long,
        days_short,
        format_date_long,
        key_sections,
        months,
        prio_disp,
        prio_letters,
        rec_disp,
        resolve_lang,
        set_lang,
    )
except ImportError:  # esecuzione come script: python src/main.py
    from lang import (
        T,
        days_long,
        days_short,
        format_date_long,
        key_sections,
        months,
        prio_disp,
        prio_letters,
        rec_disp,
        resolve_lang,
        set_lang,
    )

try:
    from src import crypto as _crypto
except ImportError:  # esecuzione come script: python src/main.py
    import crypto as _crypto


def _read_state_file(path: Path):
    """Legge JSON con envelope cifrato opzionale.

    Solleva ValueError se il file e' cifrato e la password manca/errata,
    o se il contenuto non e' JSON valido.
    """
    text = path.read_text(encoding="utf-8")  # OSError se manca
    obj, _ = _crypto.unprotect_text(text)
    return obj


def _dump_state_text(obj) -> str:
    """Serializza JSON applicando la cifratura se il lock e' attivo."""
    return _crypto.protect_text(json.dumps(obj, indent=2, ensure_ascii=False))


def _apply_startup_lang() -> str:
    """Legge TASKO_LANG/config e imposta la lingua PRIMA delle classi (BINDINGS fissi)."""
    import os

    env = os.environ.get("TASKO_LANG", "").strip().lower()
    if env.startswith("it"):
        return set_lang("it")
    if env.startswith("en"):
        return set_lang("en")
    try:
        raw = json.loads(
            (Path.home() / ".todo_config.json").read_text(encoding="utf-8")
        )
        val = raw.get("lang", "auto") if isinstance(raw, dict) else "auto"
    except (OSError, ValueError):
        val = "auto"
    return set_lang(resolve_lang(val))


_apply_startup_lang()

DATA_FILE = Path.home() / ".todo_app.json"
MAX_DEPTH = 6

# Nomi giorni/mesi localizzati: vedi lang.months(), lang.days_short(),
# lang.days_long(), lang.format_date_long().


def _format_date_it(date_str: str) -> str:
    """Compat: formattazione data lunga localizzata."""
    return format_date_long(date_str)


PRIORITY_ORDER = {"alta": 0, "media": 1, "bassa": 2}


def _is_valid_date(value: str) -> bool:
    if not value:
        return True
    return _is_valid_due(value)


def _due_date_part(due: str) -> str:
    """Ritorna solo la parte YYYY-MM-DD di un due che può avere HH:MM."""
    if not due:
        return ""
    return due.strip().split()[0]


def _due_time_part(due: str) -> str:
    parts = (due or "").strip().split()
    if len(parts) >= 2 and len(parts[1]) == 5 and parts[1][2] == ":":
        return parts[1]
    return ""


def _is_valid_due(value: str) -> bool:
    if not value:
        return True
    v = value.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            datetime.strptime(v, fmt)
            return True
        except ValueError:
            continue
    return False


def _format_date_it(date_str: str) -> str:
    """Compat: formattazione data lunga localizzata."""
    return format_date_long(date_str)


def _normalize_date(value: str) -> str:
    return _normalize_due(value)


def _normalize_due(value: str) -> str:
    if not value:
        return ""
    v = value.strip().lower()
    today = datetime.now().date()
    if v in ("oggi", "today"):
        return today.strftime("%Y-%m-%d")
    if v in ("domani", "tomorrow"):
        return (today + timedelta(days=1)).strftime("%Y-%m-%d")
    # Separa eventuale orario HH:MM
    time_part = ""
    date_part = value.strip()
    m = None
    import re as _re

    m = _re.search(r"(\d{1,2}:\d{2})\s*$", date_part)
    if m:
        time_part = m.group(1)
        # valida orario
        try:
            datetime.strptime(time_part, "%H:%M")
        except ValueError:
            return value.strip()
        date_part = date_part[: m.start()].strip()
        if len(time_part) == 4:  # es. 9:00 -> 09:00
            time_part = f"0{time_part}"
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            d = datetime.strptime(date_part, fmt).date().strftime("%Y-%m-%d")
            return f"{d} {time_part}" if time_part else d
        except ValueError:
            continue
    return value.strip()


class ClickableDataTable(DataTable):
    """DataTable that opens a row detail on a single click."""

    async def _on_click(self, event) -> None:
        try:
            self._set_hover_cursor(True)
            meta = getattr(event.style, "meta", {}) or {}
            if (
                "row" in meta
                and "column" in meta
                and meta["row"] is not None
                and meta["row"] >= 0
            ):
                row_index = meta["row"]
                if 0 <= row_index < len(self.ordered_rows):
                    self.move_cursor(row=row_index, scroll=True)
                    self.post_message(
                        self.RowSelected(
                            self, row_index, self.ordered_rows[row_index].key
                        )
                    )
                    event.stop()
                    return
        except Exception:
            pass
        await super()._on_click(event)


class Priority(str, Enum):
    HIGH = "alta"
    MEDIUM = "media"
    LOW = "bassa"

    @property
    def color(self) -> str:
        return {
            Priority.HIGH: "red",
            Priority.MEDIUM: "yellow",
            Priority.LOW: "green",
        }[self]


class Recurrence(str, Enum):
    NONE = "nessuna"
    DAILY = "giornaliero"
    WEEKLY = "settimanale"
    MONTHLY = "mensile"
    YEARLY = "annuale"

    def next_date(self, current_date: str) -> str:
        if not current_date:
            return ""
        # Preserva eventuale orario HH:MM
        time_part = _due_time_part(current_date)
        date_part = _due_date_part(current_date)
        try:
            date = datetime.strptime(date_part, "%Y-%m-%d").date()
        except ValueError:
            return current_date
        if self == Recurrence.DAILY:
            out = (date + timedelta(days=1)).strftime("%Y-%m-%d")
        elif self == Recurrence.WEEKLY:
            out = (date + timedelta(weeks=1)).strftime("%Y-%m-%d")
        elif self == Recurrence.MONTHLY:
            month = date.month + 1
            year = date.year
            if month > 12:
                month = 1
                year += 1
            last_day = calendar.monthrange(year, month)[1]
            out = f"{year}-{month:02d}-{min(date.day, last_day):02d}"
        elif self == Recurrence.YEARLY:
            try:
                out = date.replace(year=date.year + 1).strftime("%Y-%m-%d")
            except ValueError:
                # 29 feb -> 28 feb negli anni non bisestili
                out = date.replace(year=date.year + 1, day=28).strftime("%Y-%m-%d")
        else:
            return current_date
        return f"{out} {time_part}" if time_part else out


class TodoItem:
    def __init__(
        self,
        title: str,
        priority: Priority = Priority.MEDIUM,
        done: bool = False,
        paused: bool = False,
        created: str = "",
        due: str = "",
        notes: str = "",
        parent_id: int | None = None,
        todo_id: int | None = None,
        recurrence: Recurrence = Recurrence.NONE,
        tags: list[str] | None = None,
        planned_for: str = "",
        completed_at: str = "",
        project: str = "",
        pomodoros: int = 0,
        pomodoro_log: list[str] | None = None,
        stima_pomo: int = 0,
    ):
        self.id = todo_id
        self.title = title
        self.priority = priority
        self.done = done
        self.paused = paused
        self.created = created or datetime.now().strftime("%Y-%m-%d %H:%M")
        self.due = due
        self.notes = notes
        self.parent_id = parent_id
        self.recurrence = recurrence
        self.tags = tags or []
        self.planned_for = planned_for
        self.completed_at = completed_at
        self.project = (project or "").strip().lower()
        try:
            self.pomodoros = int(pomodoros or 0)
        except (ValueError, TypeError):
            self.pomodoros = 0
        try:
            self.stima_pomo = max(0, int(stima_pomo or 0))
        except (ValueError, TypeError):
            self.stima_pomo = 0
        # Log timestamp dei pomodori completati ("YYYY-MM-DD HH:MM"), per i trend.
        # I task vecchi non ce l'hanno: resta [] e il totale resta in pomodoros.
        if isinstance(pomodoro_log, list):
            self.pomodoro_log = [
                str(x)[:16] for x in pomodoro_log if isinstance(x, str) and x.strip()
            ]
        else:
            self.pomodoro_log = []

    @property
    def is_subtask(self) -> bool:
        return self.parent_id is not None

    @property
    def state(self) -> str:
        if self.done:
            return "completato"
        if self.paused:
            return "in_sospeso"
        return "attivo"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "priority": self.priority.value,
            "done": self.done,
            "paused": self.paused,
            "created": self.created,
            "due": self.due,
            "notes": self.notes,
            "parent_id": self.parent_id,
            "recurrence": self.recurrence.value,
            "tags": self.tags,
            "planned_for": self.planned_for,
            "completed_at": self.completed_at,
            "project": self.project,
            "pomodoros": self.pomodoros,
            "pomodoro_log": self.pomodoro_log,
            "stima_pomo": self.stima_pomo,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TodoItem":
        try:
            priority = Priority(data.get("priority", "media"))
        except ValueError:
            priority = Priority.MEDIUM
        try:
            recurrence = Recurrence(data.get("recurrence", "nessuna"))
        except ValueError:
            recurrence = Recurrence.NONE
        raw_tags = data.get("tags", [])
        tags = (
            [
                str(t).strip().lower()
                for t in raw_tags
                if isinstance(t, str) and t.strip()
            ]
            if isinstance(raw_tags, list)
            else []
        )
        try:
            parent_id = (
                int(data["parent_id"]) if data.get("parent_id") is not None else None
            )
        except (ValueError, TypeError):
            parent_id = None
        try:
            todo_id = int(data["id"]) if data.get("id") is not None else None
        except (ValueError, TypeError):
            todo_id = None
        return cls(
            todo_id=todo_id,
            title=str(data.get("title") or "Senza titolo"),
            priority=priority,
            done=bool(data.get("done", False)),
            paused=bool(data.get("paused", False)),
            created=str(data.get("created", "")),
            due=_normalize_date(str(data.get("due", "") or "")),
            notes=str(data.get("notes", "") or ""),
            parent_id=parent_id,
            recurrence=recurrence,
            tags=tags,
            planned_for=str(data.get("planned_for", "") or ""),
            completed_at=str(data.get("completed_at", "") or ""),
            project=str(data.get("project", "") or ""),
            pomodoros=data.get("pomodoros", 0),
            pomodoro_log=data.get("pomodoro_log", []),
            stima_pomo=data.get("stima_pomo", 0),
        )


def load_todos() -> list[TodoItem]:
    if not DATA_FILE.exists():
        return []
    try:
        data = _read_state_file(DATA_FILE)
    except (json.JSONDecodeError, OSError, ValueError):
        backup = DATA_FILE.with_suffix(".corrotto.json")
        try:
            backup.write_bytes(DATA_FILE.read_bytes())
        except OSError:
            pass
        return []
    if not isinstance(data, list):
        return []
    todos: list[TodoItem] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            todos.append(TodoItem.from_dict(item))
        except Exception:
            continue
    return todos


def save_todos(todos: list[TodoItem]) -> None:
    import os
    import shutil

    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_dump_state_text([t.to_dict() for t in todos]))
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    # Backup dell'ultima versione valida prima di sovrascrivere.
    if DATA_FILE.exists():
        try:
            shutil.copy2(DATA_FILE, DATA_FILE.with_suffix(".bak.json"))
        except OSError:
            pass
    tmp.replace(DATA_FILE)


class TodoFormScreen(ModalScreen[dict | None]):
    """Modal screen to add or edit a todo item."""

    CSS = """
    TodoFormScreen {
        align: center middle;
    }
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
    ]

    def __init__(
        self, todo: TodoItem | None = None, title: str = "", preset_project: str = ""
    ) -> None:
        super().__init__()
        self.todo = todo
        self.screen_title = title or T("form_new")
        self.preset_project = (preset_project or "").strip().lower()

    def compose(self) -> ComposeResult:
        with Vertical(id="form-container"):
            with Horizontal(id="form-title-wrap"):
                yield Label(self.screen_title, id="form-title")
            with VerticalScroll(id="form-body", can_focus=False):
                yield Input(placeholder=T("form_title_ph"), id="title-input")
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


class ConfirmScreen(ModalScreen[bool]):
    """Simple confirmation dialog."""

    CSS = """
    ConfirmScreen {
        align: center middle;
    }
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
    StateChoiceScreen {
        align: center middle;
    }
    #state-box {
        width: 36;
        max-width: 90%;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #state-msg {
        text-align: center;
        margin-bottom: 1;
        height: auto;
    }
    #state-buttons {
        width: 100%;
        height: auto;
    }
    #state-buttons Button {
        width: 100%;
        min-width: 0;
        height: 3;
        margin: 0 0 1 0;
    }
    #cancel-btn {
        width: 100%;
        min-width: 0;
        height: 3;
        margin-top: 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Annulla"),
        Binding("1", "pick_attivo", "Attivo", show=False),
        Binding("2", "pick_sospeso", "Sospeso", show=False),
        Binding("3", "pick_completato", "Completato", show=False),
    ]

    def __init__(self, title: str, current: str) -> None:
        super().__init__()
        self.todo_title = title
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical(id="state-box"):
            yield Label(
                T("state_title", title=self.todo_title, current=self.current),
                id="state-msg",
            )
            with Vertical(id="state-buttons"):
                yield Button(T("state_btn_attivo"), id="attivo-btn", variant="default")
                yield Button(
                    T("state_btn_sospeso"), id="sospeso-btn", variant="default"
                )
                yield Button(
                    T("state_btn_completato"), id="completato-btn", variant="default"
                )
                yield Button(T("ui_cancel_esc"), id="cancel-btn", variant="default")

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

    def on_mount(self) -> None:
        try:
            self.query_one("#attivo-btn", Button).focus()
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_pick_attivo(self) -> None:
        self.dismiss("attivo")

    def action_pick_sospeso(self) -> None:
        self.dismiss("in_sospeso")

    def action_pick_completato(self) -> None:
        self.dismiss("completato")


class ThemeListScreen(ModalScreen[str | None]):
    """Popup con lista temi selezionabile."""

    CSS = """
    ThemeListScreen {
        align: center middle;
    }
    #theme-box {
        width: 52;
        max-width: 90%;
        max-height: 85%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
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
    }
    #theme-close {
        width: 100%;
        min-width: 16;
        height: 3;
        margin-top: 1;
    }
    """

    BINDINGS = [Binding("escape", "close", "Chiudi")]

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

    def action_close(self) -> None:
        self.dismiss(None)


TEMPLATE_FILE = Path.home() / ".todo_templates.json"

DEFAULT_TEMPLATES: dict[str, list[dict]] = {
    T("tpldef_client"): [
        {"title": T("tpldef_kickoff"), "priority": Priority.HIGH},
        {"title": T("tpldef_req"), "priority": Priority.MEDIUM},
        {"title": T("tpldef_quote"), "priority": Priority.HIGH},
        {"title": T("tpldef_contract"), "priority": Priority.MEDIUM},
        {"title": T("tpldef_setup"), "priority": Priority.LOW},
    ],
    T("tpldef_trip"): [
        {"title": T("tpldef_flights"), "priority": Priority.HIGH},
        {"title": T("tpldef_hotel"), "priority": Priority.HIGH},
        {"title": T("tpldef_checkin"), "priority": Priority.MEDIUM},
        {"title": T("tpldef_luggage"), "priority": Priority.LOW},
        {"title": T("tpldef_docs"), "priority": Priority.MEDIUM},
    ],
    T("tpldef_site"): [
        {"title": T("tpldef_wireframe"), "priority": Priority.MEDIUM},
        {"title": T("tpldef_design"), "priority": Priority.MEDIUM},
        {"title": T("tpldef_dev"), "priority": Priority.HIGH},
        {"title": T("tpldef_test"), "priority": Priority.HIGH},
        {"title": T("tpldef_deploy"), "priority": Priority.HIGH},
    ],
}


def _coerce_template_item(raw: dict) -> dict | None:
    title = str(raw.get("title", "") or "").strip()
    if not title:
        return None
    try:
        priority = Priority(str(raw.get("priority", "media")))
    except ValueError:
        # Accetta anche "Priority.HIGH" o "alta" maiuscola
        try:
            priority = Priority(
                str(raw.get("priority", "media")).split(".")[-1].lower()
            )
        except ValueError:
            priority = Priority.MEDIUM
    return {"title": title, "priority": priority}


def load_templates() -> dict[str, list[dict]]:
    if not TEMPLATE_FILE.exists():
        return {
            k: [{"title": i["title"], "priority": i["priority"]} for i in v]
            for k, v in DEFAULT_TEMPLATES.items()
        }
    try:
        data = _read_state_file(TEMPLATE_FILE)
    except (json.JSONDecodeError, OSError, ValueError):
        return {
            k: [{"title": i["title"], "priority": i["priority"]} for i in v]
            for k, v in DEFAULT_TEMPLATES.items()
        }
    if not isinstance(data, dict):
        return {
            k: [{"title": i["title"], "priority": i["priority"]} for i in v]
            for k, v in DEFAULT_TEMPLATES.items()
        }
    out: dict[str, list[dict]] = {}
    for name, items in data.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(items, list):
            continue
        clean = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            item = _coerce_template_item(raw)
            if item:
                clean.append(item)
        if clean:
            out[name.strip()] = clean
    return out or {
        k: [{"title": i["title"], "priority": i["priority"]} for i in v]
        for k, v in DEFAULT_TEMPLATES.items()
    }


def save_templates(templates: dict[str, list[dict]]) -> None:
    import os

    serializable = {
        name: [
            {
                "title": i["title"],
                "priority": i["priority"].value
                if isinstance(i["priority"], Priority)
                else str(i["priority"]),
            }
            for i in items
        ]
        for name, items in templates.items()
    }
    tmp = TEMPLATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_dump_state_text(serializable))
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    tmp.replace(TEMPLATE_FILE)


TEMPLATES: dict[str, list[dict]] = load_templates()


CONFIG_FILE = Path.home() / ".todo_config.json"
DEFAULT_CONFIG: dict = {
    "theme": "matrix",
    "kanban_visible": True,
    "filter_state": "attivo",
    "daily_goal": 5,
    "weekly_goal": 25,
    "pomo_daily_goal": 8,
    "lang": "auto",
    "onboarded": False,
}
FILTER_STATES = ("attivo", "in_sospeso", "completati", None)


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if not CONFIG_FILE.exists():
        return cfg
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    if isinstance(data.get("theme"), str) and data["theme"].strip():
        cfg["theme"] = data["theme"].strip()
    if isinstance(data.get("kanban_visible"), bool):
        cfg["kanban_visible"] = data["kanban_visible"]
    if "filter_state" in data and data["filter_state"] in FILTER_STATES:
        cfg["filter_state"] = data["filter_state"]
    try:
        daily = int(data.get("daily_goal", 5))
        cfg["daily_goal"] = daily if 0 <= daily <= 100 else 5
    except (ValueError, TypeError):
        cfg["daily_goal"] = 5
    try:
        weekly = int(data.get("weekly_goal", 25))
        cfg["weekly_goal"] = weekly if 0 <= weekly <= 500 else 25
    except (ValueError, TypeError):
        cfg["weekly_goal"] = 25
    try:
        pomo = int(data.get("pomo_daily_goal", 8))
        cfg["pomo_daily_goal"] = pomo if 0 <= pomo <= 100 else 8
    except (ValueError, TypeError):
        cfg["pomo_daily_goal"] = 8
    lang = str(data.get("lang", "auto")).lower()
    cfg["lang"] = lang if lang in ("auto", "it", "en") else "auto"
    cfg["onboarded"] = bool(data.get("onboarded", False))
    return cfg


def save_config(cfg: dict) -> None:
    import os

    payload = {
        "theme": str(cfg.get("theme", DEFAULT_CONFIG["theme"])),
        "kanban_visible": bool(cfg.get("kanban_visible", True)),
        "filter_state": cfg.get("filter_state")
        if cfg.get("filter_state") in FILTER_STATES
        else None,
        "daily_goal": _clamp_int(cfg.get("daily_goal", 5), 5, 0, 100),
        "weekly_goal": _clamp_int(cfg.get("weekly_goal", 25), 25, 0, 500),
        "pomo_daily_goal": _clamp_int(cfg.get("pomo_daily_goal", 8), 8, 0, 100),
        "onboarded": bool(cfg.get("onboarded", False)),
        "lang": str(cfg.get("lang", "auto")).lower()
        if str(cfg.get("lang", "auto")).lower() in ("auto", "it", "en")
        else "auto",
    }
    tmp = CONFIG_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    tmp.replace(CONFIG_FILE)


ARCHIVE_FILE = Path.home() / ".todo_archive.json"


def load_archive() -> list[dict]:
    if not ARCHIVE_FILE.exists():
        return []
    try:
        data = _read_state_file(ARCHIVE_FILE)
    except (json.JSONDecodeError, OSError, ValueError):
        return []
    return [d for d in data] if isinstance(data, list) else []


def save_archive(items: list[dict]) -> None:
    import os

    tmp = ARCHIVE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_dump_state_text(items))
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    tmp.replace(ARCHIVE_FILE)


BACKUP_DIR = Path.home() / "Tasko_backups"
BACKUP_KEEP = 14


def _backup_sources() -> tuple[tuple[str, Path], ...]:
    return (
        ("todos", DATA_FILE),
        ("templates", TEMPLATE_FILE),
        ("pomodoro", POMODORO_FILE),
        ("config", CONFIG_FILE),
        ("archive", ARCHIVE_FILE),
    )


def list_snapshots() -> list[Path]:
    try:
        files = sorted(BACKUP_DIR.glob("tasko_*.zip"), reverse=True)
    except OSError:
        return []
    return [p for p in files if p.is_file()]


def _snapshot_manifest(files: dict[str, int]) -> dict:
    return {
        "app": "tasko",
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": files,
    }


def create_backup() -> Path:
    """Crea uno snapshot zip di tutti i file di stato + manifest. Ritorna il path."""
    import zipfile

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = BACKUP_DIR / f"tasko_{ts}.zip"
    counts: dict[str, int] = {}
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, path in _backup_sources():
            if path.exists():
                data = path.read_bytes()
                zf.writestr(f"{name}.json", data)
                try:
                    counts[name] = (
                        len(json.loads(data)) if name in ("todos", "archive") else 1
                    )
                except (json.JSONDecodeError, OSError):
                    counts[name] = -1
        zf.writestr("manifest.json", json.dumps(_snapshot_manifest(counts), indent=2))
    # Verifica integrita' subito.
    with zipfile.ZipFile(out) as zf:
        bad = zf.testzip()
    if bad is not None:
        try:
            out.unlink()
        except OSError:
            pass
        raise OSError(f"Snapshot corrotto, scartato: {bad}")
    prune_snapshots()
    return out


def prune_snapshots(keep: int = BACKUP_KEEP) -> None:
    for old in list_snapshots()[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def snapshot_info(path: Path) -> dict:
    """Legge il manifest di uno snapshot (mai eccezioni)."""
    import zipfile

    info: dict = {"name": path.name, "size": 0, "created": "?", "files": {}}
    try:
        info["size"] = path.stat().st_size
        with zipfile.ZipFile(path) as zf:
            raw = zf.read("manifest.json")
        manifest = json.loads(raw)
        info["created"] = str(manifest.get("created", "?"))
        info["files"] = dict(manifest.get("files", {}))
    except Exception:
        pass
    return info


def restore_snapshot(path: Path) -> None:
    """Sostituisce i file di stato con quelli dello snapshot (solo file presenti)."""
    import shutil
    import zipfile

    try:
        zf = zipfile.ZipFile(path)
    except Exception as exc:
        raise OSError(f"Snapshot illeggibile: {exc}")
    with zf:
        bad = zf.testzip()
        if bad is not None:
            raise OSError(f"Snapshot danneggiato: {bad}")
        names = set(zf.namelist())
        for name, dest in _backup_sources():
            if f"{name}.json" not in names:
                continue
            tmp = dest.with_suffix(".restore_tmp")
            with open(tmp, "wb") as f:
                f.write(zf.read(f"{name}.json"))
            shutil.move(str(tmp), str(dest))


POMODORO_FILE = Path.home() / ".todo_pomodoro.json"
POMO_PHASES = ("focus", "short", "long")
POMO_PHASE_PRESETS: dict[str, tuple[int, ...]] = {
    "focus": (15, 25, 50),
    "short": (3, 5, 10),
    "long": (10, 15, 30),
}

POMO_DEFAULTS: dict = {
    "default_minutes": 25,
    "short_minutes": 5,
    "long_minutes": 15,
    "long_every": 4,
    "cycle": 0,
    "session": None,
}


def _clamp_int(value, default: int, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (ValueError, TypeError):
        return default
    return v if lo <= v <= hi else default


def load_pomodoro() -> dict:
    """Ritorna config ciclo + sessione. Retrocompatibile coi file vecchi."""
    cfg = dict(POMO_DEFAULTS)
    if not POMODORO_FILE.exists():
        return cfg
    try:
        data = _read_state_file(POMODORO_FILE)
    except (json.JSONDecodeError, OSError, ValueError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    cfg["default_minutes"] = _clamp_int(data.get("default_minutes", 25), 25, 1, 180)
    cfg["short_minutes"] = _clamp_int(data.get("short_minutes", 5), 5, 1, 60)
    cfg["long_minutes"] = _clamp_int(data.get("long_minutes", 15), 15, 1, 60)
    cfg["long_every"] = _clamp_int(data.get("long_every", 4), 4, 2, 12)
    cfg["cycle"] = _clamp_int(data.get("cycle", 0), 0, 0, 1000)
    session = data.get("session")
    if isinstance(session, dict):
        if session.get("phase") not in POMO_PHASES:
            session["phase"] = "focus"
        cfg["session"] = session
    return cfg


def save_pomodoro(state: dict) -> None:
    import os

    payload = {
        "default_minutes": _clamp_int(state.get("default_minutes", 25), 25, 1, 180),
        "short_minutes": _clamp_int(state.get("short_minutes", 5), 5, 1, 60),
        "long_minutes": _clamp_int(state.get("long_minutes", 15), 15, 1, 60),
        "long_every": _clamp_int(state.get("long_every", 4), 4, 2, 12),
        "cycle": _clamp_int(state.get("cycle", 0), 0, 0, 1000),
        "session": state.get("session")
        if isinstance(state.get("session"), dict)
        else None,
    }
    tmp = POMODORO_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_dump_state_text(payload))
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    tmp.replace(POMODORO_FILE)


class SearchScreen(ModalScreen[str | None]):
    """Popup ricerca full-text con / ."""

    CSS = """
    SearchScreen {
        align: center middle;
    }
    #search-box {
        width: 60;
        max-width: 90%;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
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


class WeekScreen(ModalScreen[None]):
    """Vista settimana Lun-Dom."""

    CSS = """
    WeekScreen {
        align: center middle;
    }
    #week-box {
        width: 80;
        max-width: 95%;
        max-height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
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
        height: auto;
        max-height: 22;
        margin-bottom: 1;
    }
    #week-close {
        width: 100%;
        min-width: 16;
        height: 3;
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
    TemplateScreen {
        align: center middle;
    }
    #tpl-box {
        width: 60;
        max-width: 92%;
        max-height: 88%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #tpl-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
        height: auto;
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
        self.templates = templates if templates is not None else TEMPLATES

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
    TemplateCreateScreen {
        align: center middle;
    }
    #tplc-box {
        width: 64;
        max-width: 92%;
        height: 90%;
        max-height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #tplc-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
        height: auto;
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
    TemplateProjectScreen {
        align: center middle;
    }
    #tplp-box {
        width: 52;
        max-width: 90%;
        max-height: 85%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #tplp-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
        height: auto;
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
    #tplp-close {
        width: 100%;
        min-width: 16;
        height: 3;
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
    ImportCsvScreen {
        align: center middle;
    }
    #impcsv-box {
        width: 64;
        max-width: 92%;
        max-height: 88%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #impcsv-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
        height: auto;
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
        Binding("ctrl+enter", "submit", "Importa", show=False),
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
    PomodoroScreen {
        align: center middle;
    }
    #pomo-box {
        width: 46;
        max-width: 90%;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
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
    KanbanScreen {
        align: center middle;
    }
    #kb-box {
        width: 96;
        max-width: 98%;
        max-height: 92%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
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
    #kb-close {
        width: 100%;
        min-width: 16;
        height: 3;
        margin-top: 1;
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
    DetailScreen {
        align: center middle;
    }
    #detail-box {
        width: 60;
        max-width: 90%;
        max-height: 85%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
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
    DayScreen {
        align: center middle;
    }
    #day-box {
        width: 70;
        max-width: 90%;
        max-height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
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
    #day-close {
        margin-top: 1;
        width: 100%;
        min-width: 16;
        height: 3;
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
    CalendarScreen {
        align: center middle;
    }
    #calendar-box {
        width: 80;
        max-width: 95%;
        max-height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
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
    #calendar-close {
        margin-top: 1;
        width: 100%;
        min-width: 16;
        height: 3;
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
    DailyPlanScreen {
        align: center middle;
    }
    #plan-box {
        width: 80;
        max-width: 95%;
        max-height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #plan-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #plan-section {
        height: auto;
        max-height: 20;
        margin-bottom: 1;
    }
    #plan-legend {
        margin-top: 1;
        height: auto;
    }
    #plan-close {
        margin-top: 1;
        width: 100%;
        min-width: 16;
        height: 3;
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
            lines = []

            def _row(t: TodoItem, marker: str, extra: str = "") -> str:
                plbl = _pomo_label(t)
                pomo = f" [red]{plbl}[/]" if plbl else ""
                return f"  [cyan]{marker}[/] {_status(t)} {t.title}{extra}  [dim]#{t.id}[/]{pomo}"

            if planned:
                load_f = sum(t.pomodoros for t in planned)
                load_s = sum(getattr(t, "stima_pomo", 0) or 0 for t in planned)
                load = T("plan_load", f=load_f, s=load_s) if load_s else ""
                lines.append(T("plan_sec_planned", load=load))
                lines.extend(_row(t, "x") for t in planned)
            if due:
                lines.append(T("plan_sec_due"))
                lines.extend(_row(t, "+") for t in due)
            if overdue:
                lines.append(T("plan_sec_overdue"))
                lines.extend(
                    _row(t, "+", T("plan_overdue_row", due=t.due)) for t in overdue
                )
            if unplanned:
                lines.append(T("plan_sec_unplanned"))
                lines.extend(_row(t, "+") for t in unplanned)
            if not lines:
                lines.append(T("plan_empty"))
            with VerticalScroll(id="plan-section"):
                for line in lines:
                    yield Static(line)
            yield Static(T("plan_legend"), id="plan-legend")
            yield Button(T("ui_close_esc"), id="plan-close", variant="default")

    def on_mount(self) -> None:
        self.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "plan-close":
            self.dismiss()

    def _is_overdue(self, t: TodoItem) -> bool:
        if t.state != "attivo" or not t.due or t.planned_for == self.today:
            return False
        try:
            d = datetime.strptime(_due_date_part(t.due), "%Y-%m-%d").date()
            today_d = datetime.strptime(self.today, "%Y-%m-%d").date()
        except ValueError:
            return False
        return d < today_d

    def action_add_planned(self) -> None:
        candidates = [
            t
            for t in self.all_todos
            if t.state == "attivo"
            and t.planned_for != self.today
            and (
                _due_date_part(t.due) == self.today or not t.due or self._is_overdue(t)
            )
        ]
        # Priorità: in ritardo e in scadenza prima, poi senza scadenza
        candidates.sort(
            key=lambda t: (
                t.due != self.today and not self._is_overdue(t),
                t.due or "9999",
            )
        )
        if not candidates:
            self.notify(T("n_plan_add_none"))
            return
        t = candidates[0]
        t.planned_for = self.today
        self.on_change()
        self.refresh(recompose=True)
        self.notify(T("n_plan_added", t=t.title))

    def action_remove_planned(self) -> None:
        for t in self.all_todos:
            if t.planned_for == self.today and t.state == "attivo":
                t.planned_for = ""
                self.on_change()
                self.refresh(recompose=True)
                return
        self.notify(T("n_plan_rm_none"))

    def action_toggle_done(self) -> None:
        for t in self.all_todos:
            if t.planned_for == self.today and t.state == "attivo":
                t.paused = True
                self.on_change()
                self.refresh(recompose=True)
                return
        self.notify(T("n_plan_susp_none"))

    def action_close(self) -> None:
        self.dismiss()


def _status(t: TodoItem) -> str:
    if t.done:
        return "[green]X[/green]"
    if t.paused:
        return "[yellow]P[/yellow]"
    return "[red]O[/red]"


def _pomo_label(t: TodoItem) -> str:
    """'🍅fatti/stimati' se stimato, '🍅xN' se solo fatti, '' altrimenti."""
    try:
        done = int(t.pomodoros or 0)
    except (ValueError, TypeError):
        done = 0
    try:
        stima = int(getattr(t, "stima_pomo", 0) or 0)
    except (ValueError, TypeError):
        stima = 0
    if stima > 0:
        return f"🍅{done}/{stima}"
    if done > 0:
        return f"🍅x{done}"
    return ""


class GoalsScreen(ModalScreen[dict | None]):
    """Imposta obiettivi giornaliero/settimanale (0 = disattivato)."""

    CSS = """
    GoalsScreen {
        align: center middle;
    }
    #goals-box {
        width: 52;
        max-width: 90%;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #goals-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
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
    StatsScreen {
        align: center middle;
    }
    #stats-box {
        width: 58;
        max-width: 92%;
        max-height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #stats-scroll {
        height: auto;
        max-height: 22;
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
    #stats-close {
        margin-top: 1;
        width: 100%;
        min-width: 16;
        height: 3;
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
    KeysScreen {
        align: center middle;
    }
    #keys-box {
        width: 66;
        max-width: 92%;
        max-height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #keys-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
        height: auto;
    }
    #keys-list {
        height: auto;
        max-height: 24;
        margin-bottom: 1;
    }
    #keys-close {
        width: 100%;
        min-width: 16;
        height: 3;
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
    SettingsScreen {
        align: center middle;
    }
    #set-box {
        width: 60;
        max-width: 92%;
        height: 90%;
        max-height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #set-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
        height: auto;
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
                yield Label(T("set_focus"))
                yield Input(str(self.current.get("focus_min", 25)), id="set-focus")
                yield Label(T("set_short"))
                yield Input(str(self.current.get("short_min", 5)), id="set-short")
                yield Label(T("set_long"))
                yield Input(str(self.current.get("long_min", 15)), id="set-long")
                yield Label(T("set_every"))
                yield Input(str(self.current.get("long_every", 4)), id="set-every")
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
        focus = self._num("set-focus", 1, 180)
        short = self._num("set-short", 1, 60)
        longm = self._num("set-long", 1, 60)
        every = self._num("set-every", 2, 12)
        if None in (daily, weekly, pomo, focus, short, longm, every):
            return
        self.dismiss(
            {
                "theme": theme,
                "kanban_visible": bool(kanban),
                "filter_state": None if filt == "tutti" else filt,
                "daily_goal": daily,
                "weekly_goal": weekly,
                "pomo_daily_goal": pomo,
                "focus_min": focus,
                "short_min": short,
                "long_min": longm,
                "long_every": every,
                "lang": lang if lang in ("auto", "it", "en") else "auto",
            }
        )


class ArchiveScreen(ModalScreen[tuple | None]):
    """Archivio completati: ripristina singoli o tutti."""

    CSS = """
    ArchiveScreen {
        align: center middle;
    }
    #arc-box {
        width: 64;
        max-width: 92%;
        max-height: 88%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #arc-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
        height: auto;
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
    RestoreScreen {
        align: center middle;
    }
    #rst-box {
        width: 64;
        max-width: 92%;
        max-height: 88%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #rst-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
        height: auto;
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
    #rst-close {
        width: 100%;
        min-width: 16;
        height: 3;
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


def _demo_todos(start_id: int = 1) -> list[TodoItem]:
    """Dati di esempio con date relative a oggi (onboarding)."""
    today = datetime.now().date()

    def iso(offset: int) -> str:
        return (today + timedelta(days=offset)).strftime("%Y-%m-%d")

    nid = start_id
    items: list[TodoItem] = []

    def add(**kw) -> TodoItem:
        nonlocal nid
        t = TodoItem(todo_id=nid, **kw)
        nid += 1
        items.append(t)
        return t

    padre = add(
        title="Preventivo cliente Acme",
        priority=Priority.HIGH,
        due=iso(2),
        project="acme",
        tags=["preventivo"],
        notes="- [ ] Voce manodopera\n- [ ] Voce materiali",
        stima_pomo=4,
    )
    add(
        title="Raccogli requisiti",
        priority=Priority.MEDIUM,
        parent_id=padre.id,
        project="acme",
    )
    add(
        title="Sopralluogo",
        priority=Priority.MEDIUM,
        due=iso(1),
        parent_id=padre.id,
        project="acme",
    )
    add(
        title="Chiamare Banca",
        priority=Priority.MEDIUM,
        due=iso(0),
        project="personale",
        tags=["call"],
    )
    add(title="Spesa settimanale", priority=Priority.LOW, due=iso(5))
    add(
        title="Leggere report",
        priority=Priority.LOW,
        done=True,
        completed_at=(today - timedelta(days=1)).strftime("%Y-%m-%d") + " 18:00",
    )
    return items


class WelcomeScreen(ModalScreen[str | None]):
    """Benvenuto con scelta demo/vuoto (solo al primo avvio senza task)."""

    CSS = """
    WelcomeScreen {
        align: center middle;
    }
    #wel-box {
        width: 60;
        max-width: 92%;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #wel-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
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


def _needs_unlock() -> bool:
    """True se almeno un file dati e' cifrato."""
    for name, path in _backup_sources():
        if name == "config":
            continue
        try:
            if path.exists() and _crypto.is_envelope(path.read_text(encoding="utf-8")):
                return True
        except OSError:
            pass
    return False


class LockScreen(ModalScreen[bool]):
    """Blocco password all'avvio (solo se dati cifrati)."""

    CSS = """
    LockScreen {
        align: center middle;
    }
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
    PasswordScreen {
        align: center middle;
    }
    #pw-box {
        width: 52;
        max-width: 90%;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #pw-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
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
    SecurityScreen {
        align: center middle;
    }
    #sec-box {
        width: 56;
        max-width: 92%;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #sec-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
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


class TaskoMenuProvider(Provider):
    """Voci del menu principale (m): solo configurazione, import/export e utility senza tasto."""

    # (titolo, aiuto, nome action di TodoApp)
    MENU_IT: tuple[tuple[str, str, str], ...] = (
        (T("menu_settings_t"), T("menu_settings_h"), "action_open_settings"),
        (T("menu_security_t"), T("menu_security_h"), "action_open_security"),
        (T("menu_goals_t"), T("menu_goals_h"), "action_edit_goals"),
        (T("menu_clearf_t"), T("menu_clearf_h"), "action_clear_filters"),
        (T("menu_backup_now_t"), T("menu_backup_now_h"), "action_backup_now"),
        (
            T("menu_backup_restore_t"),
            T("menu_backup_restore_h"),
            "action_restore_backup",
        ),
        (T("menu_exp_md_t"), T("menu_exp_md_h"), "action_export_data"),
        (T("menu_exp_csv_t"), T("menu_exp_csv_h"), "action_export_csv"),
        (T("menu_exp_stats_t"), T("menu_exp_stats_h"), "action_export_stats_csv"),
        (T("menu_imp_csv_t"), T("menu_imp_csv_h"), "action_import_csv"),
        (T("menu_archive_do_t"), T("menu_archive_do_h"), "action_archive_done"),
        (T("menu_archive_view_t"), T("menu_archive_view_h"), "action_view_archive"),
    )

    def _iter(self):
        for title, help_text, action_name in self.MENU_IT:
            callback = getattr(self.app, action_name, None)
            if callable(callback):
                yield title, help_text, callback

    async def discover(self):
        for title, help_text, callback in self._iter():
            yield DiscoveryHit(title, callback, help=help_text)

    async def search(self, query: str):
        matcher = self.matcher(query)
        for title, help_text, callback in self._iter():
            if (match := matcher.match(title)) > 0:
                yield Hit(match, matcher.highlight(title), callback, help=help_text)


class TodoApp(App):
    """A TUI To-Do application."""

    TITLE = "Tasko"
    SUB_TITLE = "Gestisci le tue attivita'"

    CSS = """
    Screen {
        layout: vertical;
    }
    Button {
        min-width: 16;
        height: 3;
    }
    #stats-bar {
        height: auto;
        min-height: 1;
        dock: bottom;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    DataTable {
        height: 1fr;
    }
    #help-panel {
        height: auto;
        max-height: 12;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
        margin: 0 1;
    }
    #help-panel.hidden {
        display: none;
    }
    #kanban-bar {
        height: 7;
        border: solid $primary;
        background: $surface;
        padding: 0 1;
        margin: 0 1;
    }
    #kanban-bar.hidden {
        display: none;
    }
    #pomodoro-bar {
        height: 3;
        border: solid $error;
        background: $error-darken-2;
        color: $text;
        text-style: bold;
        padding: 0 1;
        margin: 0 1;
    }
    #pomodoro-bar.paused {
        border: solid $warning;
        background: $warning-darken-2;
    }
    #pomodoro-bar.break {
        border: solid $success;
        background: $success-darken-2;
    }
    #pomodoro-bar.hidden {
        display: none;
    }
    Footer {
        padding-left: 1;
    }
    """

    BINDINGS = [
        Binding("n", "new_todo", T("b_new")),
        Binding("s", "add_subtask", T("b_subtask")),
        Binding("space", "toggle_done", T("b_status")),
        Binding("e", "edit_todo", T("b_edit")),
        Binding("d", "delete_todo", T("b_delete")),
        Binding("h", "toggle_help", T("b_help")),
        Binding("enter", "view_detail", "Dettagli", show=False),
        Binding("f", "filter_todos", "Filtro stato", show=False),
        Binding("t", "filter_by_tag", "Filtro tag", show=False),
        Binding("g", "filter_by_project", "Filtro progetto", show=False),
        Binding("slash", "search_todos", T("b_search"), show=True),
        Binding("q", "quit", T("b_quit")),
        Binding("c", "view_calendar", "Calendario", show=False),
        Binding("w", "view_week", "Settimana", show=False),
        Binding("b", "toggle_kanban", "Kanban", show=False),
        Binding("B", "view_kanban", "Kanban full", show=False),
        Binding("p", "view_daily_plan", "Piano", show=False),
        Binding("k", "view_stats", "Statistiche", show=False),
        Binding("o", "start_pomodoro", "Pomodoro", show=False),
        Binding("O", "pomodoro_pause", "Pausa/Riprendi", show=False),
        Binding("X", "pomodoro_finish", "Completa pomo", show=False),
        Binding("u", "undo_delete", "Annulla", show=False),
        Binding("T", "new_from_template", "Template", show=False),
        Binding("v", "choose_theme", "Tema...", show=False),
        Binding("ctrl+s", "save_screenshot", "Screenshot", show=False),
        Binding("ctrl+e", "export_data", "Export", show=False),
        Binding("r", "refresh", "Ricarica", show=False),
        Binding(
            "ctrl+p",
            "command_palette",
            T("b_menu"),
            show=False,
            tooltip=T("menu_tooltip"),
        ),
        Binding(
            "m", "command_palette", T("b_menu"), show=False, tooltip=T("menu_tooltip")
        ),
    ]

    COMMAND_PALETTE_BINDING = "m"

    COMMANDS = App.COMMANDS | {TaskoMenuProvider}

    def get_system_commands(self, screen: Screen):
        """Comandi di sistema della palette, localizzati."""
        yield SystemCommand(
            T("sys_theme_t"), T("sys_theme_h"), self.action_choose_theme
        )
        yield SystemCommand(T("sys_quit_t"), T("sys_quit_h"), self.action_quit)
        yield SystemCommand(T("sys_keys_t"), T("sys_keys_h"), self.action_show_keys)
        if screen.maximized is not None:
            yield SystemCommand(
                T("sys_zoom_out_t"), T("sys_zoom_out_h"), screen.action_minimize
            )
        elif screen.focused is not None and screen.focused.allow_maximize:
            yield SystemCommand(
                T("sys_zoom_in_t"), T("sys_zoom_in_h"), screen.action_maximize
            )
        yield SystemCommand(
            T("sys_snap_t"),
            T("sys_snap_h"),
            lambda: self.set_timer(0.1, self.deliver_screenshot),
        )

    def action_command_palette(self) -> None:
        """Mostra il menu localizzato."""
        if self.use_command_palette and not CommandPalette.is_open(self):
            self.push_screen(
                CommandPalette(id="--command-palette", placeholder=T("pal_placeholder"))
            )

    def __init__(self) -> None:
        super().__init__()
        from textual.theme import Theme

        self.register_theme(
            Theme(
                name="matrix",
                primary="#00ff41",
                secondary="#33ff00",
                warning="#ffd500",
                error="#ff0033",
                success="#00ff41",
                accent="#00cc88",
                foreground="#00ff41",
                background="#000000",
                surface="#0a1a0a",
                panel="#062206",
                boost="#00ff41",
                dark=True,
                variables={
                    "footer-key-foreground": "#012601",
                    "footer-key-background": "#00ff41",
                    "footer-description-foreground": "#65ff9f",
                    "footer-description-background": "#011001",
                },
            )
        )
        self.theme = "matrix"
        self.config: dict = load_config()
        try:
            if self.config.get("theme") in self.available_themes:
                self.theme = self.config["theme"]
        except Exception:
            pass
        self.todos: list[TodoItem] = self._load_data()
        self.templates: dict[str, list[dict]] = load_templates()
        self.filter_state: str | None = self.config.get("filter_state", "attivo")
        if self.filter_state not in FILTER_STATES:
            self.filter_state = "attivo"
        self.filter_tag: str | None = None
        self.filter_project: str | None = None
        self.filter_search: str = ""
        self.next_id = max((t.id or 0 for t in self.todos), default=0) + 1
        self._row_map: list[TodoItem] = []
        self._undo_stack: list[list[TodoItem]] = []
        self._trash: list[TodoItem] = []
        self.focus_task_id: int | None = None
        self.focus_end: datetime | None = None
        self.focus_paused_secs: int | None = None
        self.focus_phase: str | None = None  # None=pronto, altrimenti focus/short/long
        self.focus_total_secs: int = 25 * 60
        self.POMODORO_MIN = 25
        self.POMO_SHORT_MIN = 5
        self.POMO_LONG_MIN = 15
        self.POMO_LONG_EVERY = 4
        self.pomo_cycle = 0
        self._pending_pomo: dict = load_pomodoro()
        try:
            self.POMODORO_MIN = int(self._pending_pomo.get("default_minutes", 25))
        except (ValueError, TypeError):
            self.POMODORO_MIN = 25
        self.focus_total_secs = self.POMODORO_MIN * 60

    def export_screenshot(
        self, *, title: str | None = None, simplify: bool = False
    ) -> str:
        try:
            return super().export_screenshot(title=title, simplify=simplify)
        except KeyError:
            orig_theme = self.theme
            try:
                self.theme = "textual-dark"
                return super().export_screenshot(title=title, simplify=simplify)
            finally:
                self.theme = orig_theme

    def _load_data(self) -> list[TodoItem]:
        return load_todos()

    def _save_data(self) -> None:
        save_todos(self.todos)

    def _save_config(self) -> None:
        try:
            save_config(self.config)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        yield Header()
        yield ClickableDataTable(id="todo-table")
        yield Static(
            "",
            id="kanban-bar",
            classes="" if self.config.get("kanban_visible", True) else "hidden",
        )
        yield Static("", id="pomodoro-bar", classes="hidden")
        yield Static(self._stats_text(), id="stats-bar")
        yield Static(self._help_text(), id="help-panel", classes="hidden")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#todo-table", DataTable)
        table.add_columns(
            "ID",
            T("col_state"),
            T("col_title"),
            T("col_proj"),
            "Tags",
            T("col_notes"),
            T("col_prio"),
            T("col_recur"),
            T("col_due"),
        )
        table.cursor_type = "row"
        try:
            self.set_interval(1, self._tick_focus)
        except Exception:
            pass
        self._populate_table()
        if _needs_unlock() and not _crypto.is_unlocked():
            self.push_screen(LockScreen(), self._on_unlocked)
            return
        self._continue_startup(reload=False)

    def _on_unlocked(self, ok: bool | None) -> None:
        if not ok:
            self.exit()
            return
        self._continue_startup(reload=True)

    def _continue_startup(self, reload: bool) -> None:
        if reload:
            self._reload_all()
        else:
            self._pending_pomo = load_pomodoro()
            self._restore_pomodoro()
            self._auto_backup()
        if not self.todos:
            self.query_one("#help-panel").remove_class("hidden")
            if not self.config.get("onboarded"):
                self.push_screen(WelcomeScreen(), self._on_welcome)
            else:
                self.notify(T("n_welcome"))

    def _on_welcome(self, choice: str | None) -> None:
        self.config["onboarded"] = True
        self._save_config()
        if choice == "demo":
            self.todos = _demo_todos(self.next_id)
            self.next_id = max((t.id or 0 for t in self.todos), default=0) + 1
            self._save_data()
            self._populate_table()
            self.notify(T("n_welcome_demo"))
        else:
            self.notify(T("n_welcome"))

    def _help_text(self) -> str:
        return "\n".join(T(f"help_l{i}") for i in range(1, 6))

    def _stats_text(self) -> str:
        parents = [t for t in self.todos if not t.is_subtask]
        attivi = sum(1 for t in parents if t.state == "attivo")
        sospesi = sum(1 for t in parents if t.state == "in_sospeso")
        completati = sum(1 for t in parents if t.state == "completato")
        sub_count = sum(1 for t in self.todos if t.is_subtask)
        planned_count = sum(
            1
            for t in self.todos
            if t.planned_for == datetime.now().strftime("%Y-%m-%d")
        )
        base = f" O:{attivi} P:{sospesi} X:{completati} | Sub:{sub_count} Piano:{planned_count}"
        if getattr(self, "focus_task_id", None):
            base += f" | 🍅 {self._focus_label()}"
        active_filter = (
            self.filter_state is not None
            or self.filter_tag is not None
            or getattr(self, "filter_project", None)
            or getattr(self, "filter_search", "")
        )
        if not active_filter:
            return f"{base} | {T('bar_all')}"
        parts = []
        if self.filter_state is not None:
            parts.append(T("bar_filter", v=self.filter_state.replace("_", " ")))
        if self.filter_tag is not None:
            parts.append(T("bar_tag", v=self.filter_tag))
        if getattr(self, "filter_project", None):
            parts.append(T("bar_proj", v=self.filter_project))
        if getattr(self, "filter_search", ""):
            parts.append(T("bar_search", v=self.filter_search))
        return f"{base} | [black on yellow] {' + '.join(parts)} [/]"

    def _kanban_text(self) -> str:
        def top(state: str) -> str:
            items = [t for t in self.todos if not t.is_subtask and t.state == state]
            items = sorted(items, key=self._sort_key)[:3]
            if not items:
                return "-"
            return " · ".join(f"#{t.id} {t.title[:18]}" for t in items)

        n_att = sum(1 for t in self.todos if not t.is_subtask and t.state == "attivo")
        n_sos = sum(
            1 for t in self.todos if not t.is_subtask and t.state == "in_sospeso"
        )
        n_fat = sum(
            1 for t in self.todos if not t.is_subtask and t.state == "completato"
        )
        return (
            f"{T('kb_head')}\n"
            f" [red]○ {T('kb_attivo')} ({n_att})[/red]: {top('attivo')}\n"
            f" [yellow]◐ {T('kb_sospeso')} ({n_sos})[/yellow]: {top('in_sospeso')}\n"
            f" [green]● {T('kb_fatto')} ({n_fat})[/green]: {top('completato')}"
        )

    def _update_kanban(self) -> None:
        try:
            self.query_one("#kanban-bar", Static).update(self._kanban_text())
        except Exception:
            pass

    def _get_parents(self) -> list[TodoItem]:
        ids = {t.id for t in self.todos}
        # Gli orfani (parent_id puntato a id inesistente) vengono mostrati come radici
        # invece di sparire dalla tabella.
        return [t for t in self.todos if not t.is_subtask or t.parent_id not in ids]

    def _matches_state(self, todo: TodoItem) -> bool:
        if self.filter_state is None:
            return True
        target = {
            "attivo": "attivo",
            "in_sospeso": "in_sospeso",
            "completati": "completato",
        }[self.filter_state]
        if todo.state == target:
            return True
        return any(self._matches_state(sub) for sub in self._get_subtasks(todo.id))

    def _matches_tag(self, todo: TodoItem) -> bool:
        if self.filter_tag is None:
            return True
        if self.filter_tag in todo.tags:
            return True
        return any(self._matches_tag(sub) for sub in self._get_subtasks(todo.id))

    def _sort_key(self, todo: TodoItem):
        due_key = todo.due if _is_valid_due(todo.due) and todo.due else "9999-99-99"
        return (due_key, PRIORITY_ORDER.get(todo.priority.value, 9), todo.title.lower())

    def _matches_project(self, todo: TodoItem) -> bool:
        if not getattr(self, "filter_project", None):
            return True
        if todo.project == self.filter_project:
            return True
        return any(self._matches_project(sub) for sub in self._get_subtasks(todo.id))

    def _matches_search(self, todo: TodoItem) -> bool:
        q = (getattr(self, "filter_search", "") or "").strip().lower()
        if not q:
            return True
        hay = f"{todo.title} {todo.notes} {todo.project} {' '.join(todo.tags)}".lower()
        if q in hay:
            return True
        return any(self._matches_search(sub) for sub in self._get_subtasks(todo.id))

    def _filtered_todos(self) -> list[TodoItem]:
        parents = self._get_parents()
        if self.filter_state is not None:
            parents = [t for t in parents if self._matches_state(t)]
        if self.filter_tag is not None:
            parents = [t for t in parents if self._matches_tag(t)]
        if getattr(self, "filter_project", None):
            parents = [t for t in parents if self._matches_project(t)]
        if getattr(self, "filter_search", ""):
            parents = [t for t in parents if self._matches_search(t)]
        return sorted(parents, key=self._sort_key)

    def _get_subtasks(self, parent_id: int) -> list[TodoItem]:
        return [t for t in self.todos if t.parent_id == parent_id]

    def _get_depth(self, todo: TodoItem) -> int:
        depth = 0
        current = todo
        while current.parent_id is not None:
            parent = next((t for t in self.todos if t.id == current.parent_id), None)
            if parent is None:
                break
            depth += 1
            current = parent
        return depth

    def _get_all_descendants(self, todo_id: int) -> list[TodoItem]:
        result = []
        for t in self.todos:
            if t.parent_id == todo_id:
                result.append(t)
                result.extend(self._get_all_descendants(t.id))
        return result

    def _populate_table(self) -> None:
        table = self.query_one("#todo-table", DataTable)
        selected = self._get_selected_todo()
        selected_id = selected.id if selected else None
        table.clear()
        self._row_map = []
        for todo in self._filtered_todos():
            self._add_todo_rows(table, todo, depth=0, prefix="", is_last=True)
        if not self._row_map:
            table.add_row(
                "-",
                "-",
                "Nessun task — premi 'n' per crearne uno",
                "-",
                "-",
                "-",
                "-",
                "-",
                "-",
            )
        elif selected_id is not None:
            for idx, t in enumerate(self._row_map):
                if t.id == selected_id:
                    try:
                        table.move_cursor(row=idx, scroll=True)
                    except Exception:
                        pass
                    break
        self.query_one("#stats-bar", Static).update(self._stats_text())
        self._update_kanban()
        self._update_pomodoro_bar()

    def _add_todo_rows(
        self, table: DataTable, todo: TodoItem, depth: int, prefix: str, is_last: bool
    ) -> None:
        status = f"{_status(todo)}{' ○' if todo.state == 'attivo' else ' ◐' if todo.state == 'in_sospeso' else ' ●'}"
        priority_str = f"[{todo.priority.color}]{prio_disp(todo.priority.value)}[/]"
        raw_notes = (
            todo.notes.replace("- [ ]", "☐").replace("- [x]", "☑").replace("- [X]", "☑")
        )
        notes_preview = (
            (raw_notes[:30] + "...") if len(raw_notes) > 30 else (raw_notes or "-")
        )
        recurrence_str = (
            f"[cyan]{rec_disp(todo.recurrence.value)}[/]"
            if todo.recurrence != Recurrence.NONE
            else "-"
        )
        tags_str = (
            ", ".join(f"[magenta]#{t}[/]" for t in todo.tags) if todo.tags else "-"
        )
        project_str = f"[blue]{todo.project}[/]" if todo.project else "-"

        if depth == 0:
            title_display = todo.title
        else:
            connector = "└── " if is_last else "├── "
            title_display = f"{prefix}{connector}{todo.title}"
        # Progresso figli + pomodori
        children = self._get_subtasks(todo.id)
        if children:
            done_c = sum(1 for c in children if c.done)
            title_display += f" [dim]({done_c}/{len(children)})[/]"
        if todo.pomodoros or getattr(todo, "stima_pomo", 0):
            title_display += f" [red]{_pomo_label(todo)}[/]"
        if todo.done:
            title_display = f"[strike]{title_display}[/strike]"

        table.add_row(
            str(todo.id),
            status,
            title_display,
            project_str,
            tags_str,
            notes_preview,
            priority_str,
            recurrence_str,
            todo.due or "-",
        )
        self._row_map.append(todo)

        if depth < MAX_DEPTH:
            subtasks = self._get_subtasks(todo.id)
            if self.filter_state is not None:
                subtasks = [s for s in subtasks if self._matches_state(s)]
            if self.filter_tag is not None:
                subtasks = [s for s in subtasks if self._matches_tag(s)]
            if getattr(self, "filter_project", None):
                subtasks = [s for s in subtasks if self._matches_project(s)]
            if getattr(self, "filter_search", ""):
                subtasks = [s for s in subtasks if self._matches_search(s)]
            subtasks = sorted(subtasks, key=self._sort_key)
            for i, sub in enumerate(subtasks):
                is_last_sub = i == len(subtasks) - 1
                if depth == 0:
                    new_prefix = ""
                else:
                    new_prefix = prefix + ("    " if is_last else "│   ")
                self._add_todo_rows(table, sub, depth + 1, new_prefix, is_last_sub)

    def _get_selected_todo(self) -> TodoItem | None:
        table = self.query_one("#todo-table", DataTable)
        if not table.rows:
            return None
        row_idx = table.cursor_row
        if 0 <= row_idx < len(self._row_map):
            return self._row_map[row_idx]
        return None

    def action_new_todo(self) -> None:
        def on_submit(result: dict | None) -> None:
            if result:
                todo = TodoItem(
                    title=result["title"],
                    priority=result["priority"],
                    due=result["due"],
                    notes=result["notes"],
                    recurrence=result["recurrence"],
                    tags=result["tags"],
                    project=result.get("project", ""),
                    stima_pomo=result.get("stima_pomo", 0),
                    todo_id=self.next_id,
                )
                self.next_id += 1
                self.todos.append(todo)
                self._save_data()
                self._populate_table()
                self.notify(T("n_added", t=todo.title))

        self.push_screen(TodoFormScreen(title=T("form_new")), on_submit)

    def action_edit_todo(self) -> None:
        todo = self._get_selected_todo()
        if not todo:
            self.notify(T("n_nosel"), severity="warning")
            return
        self._open_edit_form(todo)

    def _open_edit_form(self, todo: TodoItem, reopen_detail: bool = False) -> None:
        def on_submit(result: dict | None) -> None:
            if result:
                todo.title = result["title"]
                todo.priority = result["priority"]
                todo.due = result["due"]
                todo.notes = result["notes"]
                todo.recurrence = result["recurrence"]
                todo.tags = result["tags"]
                todo.project = result.get("project", "")
                todo.stima_pomo = result.get("stima_pomo", 0)
                self._save_data()
                self._populate_table()
                self.notify(T("n_updated", t=todo.title))
                if reopen_detail:
                    self.push_screen(
                        DetailScreen(todo, self.todos), self._on_detail_closed
                    )

        self.push_screen(TodoFormScreen(todo=todo, title=T("form_edit")), on_submit)

    def _on_detail_closed(self, choice: str | None) -> None:
        # Callback riusabile quando il dettaglio viene richiuso dopo una modifica:
        # al momento non serve riaprire altro, il dettaglio aggiornato e' gia' visibile.
        return

    def action_delete_todo(self) -> None:
        todo = self._get_selected_todo()
        if not todo:
            self.notify(T("n_nosel"), severity="warning")
            return

        descendants = self._get_all_descendants(todo.id)
        msg = T("n_del_t", t=todo.title)
        if descendants:
            msg += T("n_del_sub", n=len(descendants))

        def on_confirm(confirmed: bool) -> None:
            if confirmed:
                desc_ids = {d.id for d in descendants}
                removed = [t for t in self.todos if t.id == todo.id or t.id in desc_ids]
                self._undo_stack.append(removed)
                self._trash.extend(removed)
                self.todos = [
                    t for t in self.todos if t.id != todo.id and t.id not in desc_ids
                ]
                self._save_data()
                self._populate_table()
                self.notify(T("n_deleted", t=todo.title))

        self.push_screen(ConfirmScreen(msg), on_confirm)

    def action_toggle_done(self) -> None:
        todo = self._get_selected_todo()
        if not todo:
            self.notify(T("n_nosel"), severity="warning")
            return
        if not self._row_map or todo.id is None:
            return
        current_label = {
            "attivo": T("state_attivo"),
            "in_sospeso": T("state_sospeso"),
            "completato": T("state_completato"),
        }[todo.state]

        def on_pick(choice: str | None) -> None:
            if choice is None or choice == todo.state:
                return
            self._apply_state(todo, choice)

        self.push_screen(StateChoiceScreen(todo.title, current_label), on_pick)

    def _apply_state(self, todo: TodoItem, choice: str) -> None:
        if choice == "attivo":
            todo.done = False
            todo.paused = False
            todo.completed_at = ""
            nuovo = T("n_to_active")
        elif choice == "in_sospeso":
            todo.done = False
            todo.paused = True
            todo.completed_at = ""
            nuovo = T("n_to_paused")
        else:  # completato
            todo.paused = False
            todo.done = True
            todo.planned_for = ""
            todo.completed_at = datetime.now().strftime("%Y-%m-%d %H:%M")
            nuovo = T("n_to_done")
            if todo.recurrence != Recurrence.NONE and todo.due:
                new_due = todo.recurrence.next_date(todo.due)
                new_todo = TodoItem(
                    title=todo.title,
                    priority=todo.priority,
                    due=new_due,
                    notes=todo.notes,
                    parent_id=todo.parent_id,
                    recurrence=todo.recurrence,
                    tags=list(todo.tags),
                    project=todo.project,
                    todo_id=self.next_id,
                )
                self.next_id += 1
                self.todos.append(new_todo)
                self.notify(T("n_recur", t=new_todo.title, d=new_due))
        self._save_data()
        self._populate_table()
        self.notify(T("n_state", t=todo.title, s=nuovo))

    def action_add_subtask(self) -> None:
        todo = self._get_selected_todo()
        if not todo:
            self.notify(T("n_nosel"), severity="warning")
            return
        current_depth = self._get_depth(todo)
        if current_depth >= MAX_DEPTH:
            self.notify(T("n_maxdepth", n=MAX_DEPTH), severity="error")
            return
        parent_id = todo.id
        parent_title = todo.title
        parent_project = todo.project

        def on_submit(result: dict | None) -> None:
            if result:
                sub = TodoItem(
                    title=result["title"],
                    priority=result["priority"],
                    due=result["due"],
                    notes=result["notes"],
                    parent_id=parent_id,
                    todo_id=self.next_id,
                    recurrence=result["recurrence"],
                    tags=result["tags"],
                    project=result.get("project", "") or parent_project,
                    stima_pomo=result.get("stima_pomo", 0),
                )
                self.next_id += 1
                self.todos.append(sub)
                self._save_data()
                self._populate_table()
                self.notify(T("n_sub_added", s=sub.title, p=parent_title))

        self.push_screen(
            TodoFormScreen(
                title=T("form_sub", parent=parent_title), preset_project=parent_project
            ),
            on_submit,
        )

    def action_view_detail(self) -> None:
        todo = self._get_selected_todo()
        if not todo:
            self.notify(T("n_nosel"), severity="warning")
            return

        def on_detail(choice: str | None) -> None:
            if choice == "edit":
                self._open_edit_form(todo, reopen_detail=True)

        self.push_screen(DetailScreen(todo, self.todos), on_detail)

    def on_data_table_row_selected(self, event) -> None:
        # Guardia anti-doppio-push: un singolo click puo' generare due RowSelected
        # (manuale + highlight-click nativo). Se il dettaglio e' gia' aperto, ignora.
        if isinstance(self.screen, DetailScreen):
            return
        self.action_view_detail()

    def action_view_calendar(self) -> None:
        today = datetime.now().date()
        self.push_screen(CalendarScreen(self.todos, today.year, today.month))

    def action_open_day(self, year: int, month: int, day: int) -> None:
        date_str = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        todos = [
            t
            for t in self.todos
            if _due_date_part(t.due) == date_str and t.state != "completato"
        ]
        self.push_screen(DayScreen(date_str, todos))

    def action_view_daily_plan(self) -> None:
        def on_change() -> None:
            self._save_data()
            self._populate_table()

        self.push_screen(DailyPlanScreen(self.todos, on_change))

    def action_view_stats(self) -> None:
        self.push_screen(
            StatsScreen(
                self.todos,
                self.config.get("daily_goal", 5),
                self.config.get("weekly_goal", 25),
                self.config.get("pomo_daily_goal", 8),
            )
        )

    def action_filter_todos(self) -> None:
        order = ["attivo", "in_sospeso", "completati", None]
        labels = {
            "attivo": T("n_f_attivo"),
            "in_sospeso": T("n_f_sospeso"),
            "completati": T("n_f_fatti"),
            None: T("n_f_tutti"),
        }
        idx = order.index(self.filter_state)
        self.filter_state = order[(idx + 1) % len(order)]
        self.config["filter_state"] = self.filter_state
        self._save_config()
        self.notify(T("n_filter", v=labels[self.filter_state]))
        self._populate_table()

    def action_clear_filters(self) -> None:
        """Pulisce stato, tag, progetto e ricerca in un colpo (solo dal menu)."""
        self.filter_state = None
        self.filter_tag = None
        self.filter_project = None
        self.filter_search = ""
        self._populate_table()
        self.notify(T("n_filters_clear"))

    def action_filter_by_tag(self) -> None:
        all_tags = sorted({t for todo in self.todos for t in todo.tags})
        if not all_tags:
            self.notify(T("n_notags"), severity="warning")
            return
        # Ciclo: tutti -> primo tag -> ... -> ultimo tag -> tutti
        order: list[str | None] = [None] + all_tags
        try:
            idx = order.index(self.filter_tag)
        except ValueError:
            idx = 0
        self.filter_tag = order[(idx + 1) % len(order)]
        if self.filter_tag is None:
            self.notify(T("n_ftag_all"))
        else:
            self.notify(T("n_ftag", t=self.filter_tag))
        self._populate_table()

    def action_filter_by_project(self) -> None:
        all_projects = sorted({t.project for t in self.todos if t.project})
        if not all_projects:
            self.notify(T("n_noproj"), severity="warning")
            return
        order: list[str | None] = [None] + all_projects
        try:
            idx = order.index(self.filter_project)
        except ValueError:
            idx = 0
        self.filter_project = order[(idx + 1) % len(order)]
        self.notify(
            T("n_fproj_all")
            if self.filter_project is None
            else T("n_fproj", p=self.filter_project)
        )
        self._populate_table()

    def action_search_todos(self) -> None:
        def on_submit(result: str | None) -> None:
            if result is None:
                return
            self.filter_search = result
            self.notify(T("n_search_clear") if not result else T("n_search", q=result))
            self._populate_table()

        self.push_screen(SearchScreen(self.filter_search), on_submit)

    def action_view_week(self) -> None:
        today = datetime.now().date()
        monday = today - timedelta(days=today.weekday())
        self.push_screen(WeekScreen(self.todos, monday))

    def _open_pomodoro_popup(self) -> None:
        self.push_screen(
            PomodoroScreen(
                self._pomodoro_state,
                self._pomodoro_pause_resume,
                self._pomodoro_stop,
                self._pomodoro_done,
                self._pomodoro_set_duration,
            )
        )

    def _phase_total_secs(self, phase: str) -> int:
        if phase == "short":
            return self.POMO_SHORT_MIN * 60
        if phase == "long":
            return self.POMO_LONG_MIN * 60
        return self.POMODORO_MIN * 60

    def _start_phase(self, phase: str, task_id: int) -> None:
        self.focus_phase = phase
        self.focus_task_id = task_id
        self.focus_total_secs = self._phase_total_secs(phase)
        self.focus_end = datetime.now() + timedelta(seconds=self.focus_total_secs)
        self.focus_paused_secs = None
        self._save_pomodoro()
        self._populate_table()

    def action_start_pomodoro(self) -> None:
        if self.focus_task_id is not None:
            # Timer già attivo: apri il popup ovunque tu sia, senza vincoli di selezione.
            self._open_pomodoro_popup()
            return
        todo = self._get_selected_todo()
        if not todo:
            self.notify(T("n_nosel"), severity="warning")
            return
        self._start_phase("focus", todo.id)
        self.notify(T("n_pomo_start", t=todo.title, m=self.POMODORO_MIN))
        self._open_pomodoro_popup()

    def action_pomodoro_pause(self) -> None:
        """Pausa/riprendi globale: funziona da ovunque, senza popup."""
        if self.focus_task_id is None:
            self.notify(T("n_pomo_none"), severity="warning")
            return
        self._pomodoro_pause_resume()

    def action_pomodoro_finish(self) -> None:
        """Completa il focus o salta la pausa (globale)."""
        if self.focus_task_id is None:
            self.notify(T("n_timer_none"), severity="warning")
            return
        self._pomodoro_done()

    def _cycle_dots(self) -> str:
        n = min(self.pomo_cycle, self.POMO_LONG_EVERY)
        return "●" * n + "○" * (self.POMO_LONG_EVERY - n)

    def _pomo_today_count(self) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        n = 0
        for t in self.todos:
            for ts in getattr(t, "pomodoro_log", []) or []:
                if str(ts)[:10] == today:
                    n += 1
        return n

    def _pomo_goal_text(self) -> str:
        goal = self.config.get("pomo_daily_goal", 8)
        try:
            goal = int(goal)
        except (ValueError, TypeError):
            goal = 0
        if goal <= 0:
            return ""
        return f" · oggi {self._pomo_today_count()}/{goal} 🍅"

    def _is_break(self) -> bool:
        return self.focus_phase in ("short", "long")

    def _pomodoro_text(self) -> str:
        todo = next((t for t in self.todos if t.id == self.focus_task_id), None)
        name = todo.title[:28] if todo else f"#{self.focus_task_id}"
        plbl = _pomo_label(todo) if todo else ""
        total = f" ({plbl})" if plbl else ""
        secs = self._pomodoro_remaining_secs()
        clock = f"{secs // 60:02d}:{secs % 60:02d}"
        total_min = max(1, self.focus_total_secs // 60)
        dots = self._cycle_dots()
        x_key = "pomo_hint_skip" if self._is_break() else "pomo_hint_done"
        hints = (
            f" [dim][o] [@click=app.start_pomodoro][underline]{T('pomo_hint_open')}[/underline][/]"
            f"  [O] [@click=app.pomodoro_pause][underline]{T('pomo_hint_pause')}[/underline][/]"
            f"  [X] [@click=app.pomodoro_finish][underline]{T(x_key)}[/underline][/][/dim]"
        )
        if self.focus_paused_secs is not None:
            state = f"[yellow]⏸ {T('pomo_paused')} {clock}/{total_min:02d}:00[/yellow]"
        elif self._is_break():
            state = f"[green]☕ {T('pomo_phase_long') if self.focus_phase == 'long' else T('pomo_phase_short')} {clock}/{total_min:02d}:00 {dots}[/green]"
            return f" {state}  {T('pomo_break_after', name=name)}{self._pomo_goal_text()}{hints}"
        elif secs <= 60:
            state = f"[green]🍅 {clock}/{total_min:02d}:00 {dots} — {T('pomo_almost')}[/green]"
        else:
            state = f"[red]🍅 {clock}/{total_min:02d}:00 {dots}[/red]"
        return f" {state}  {name}{total}{self._pomo_goal_text()}{hints}"

    def _update_pomodoro_bar(self) -> None:
        try:
            bar = self.query_one("#pomodoro-bar", Static)
        except Exception:
            return
        if self.focus_task_id is None:
            bar.add_class("hidden")
            return
        bar.remove_class("hidden")
        bar.set_class(self.focus_paused_secs is not None, "paused")
        bar.set_class(self._is_break() and self.focus_paused_secs is None, "break")
        bar.update(self._pomodoro_text())

    def _pomodoro_remaining_secs(self) -> int:
        if self.focus_task_id is None:
            return 0
        if self.focus_paused_secs is not None:
            return self.focus_paused_secs
        if not self.focus_end:
            return 0
        return max(0, int((self.focus_end - datetime.now()).total_seconds()))

    def _pomodoro_state(self) -> dict:
        if self.focus_task_id is None:
            return {"empty": True}
        todo = next((t for t in self.todos if t.id == self.focus_task_id), None)
        secs = self._pomodoro_remaining_secs()
        paused = self.focus_paused_secs is not None
        phase = self.focus_phase or "focus"
        is_break = phase in ("short", "long")
        total_min = max(1, self.focus_total_secs // 60)
        name = todo.title if todo else "-"
        plbl = _pomo_label(todo) if todo else ""
        count = f"  {plbl}" if plbl else ""
        dots = self._cycle_dots()
        if is_break:
            info = f"{T('pomo_break_after', name=name)}\n{T('pomo_cycle', dots=dots)}"
        else:
            coming = (
                T("pomo_next_long")
                if (self.pomo_cycle + 1) % self.POMO_LONG_EVERY == 0
                else T("pomo_next_short")
            )
            info = f"{name}{count}\n{T('pomo_cycle', dots=dots)} · {coming}"
        return {
            "empty": False,
            "clock": f"{secs // 60:02d}:{secs % 60:02d} / {total_min:02d}:00{T('pomo_paused_tag') if paused else ''}",
            "total_min": total_min,
            "task": f"{name}{count}",
            "info": info,
            "paused": paused,
            "phase": phase,
            "is_break": is_break,
            "presets": POMO_PHASE_PRESETS.get(phase, (15, 25, 50)),
        }

    def _pomodoro_set_duration(self, minutes: int) -> None:
        """Cambia la durata della fase corrente e riavvia da capo."""
        if self.focus_task_id is None:
            return
        phase = self.focus_phase or "focus"
        lo, hi = (1, 180) if phase == "focus" else (1, 60)
        if minutes not in range(lo, hi + 1):
            self.notify(T("n_dur_bad", lo=lo, hi=hi), severity="error")
            return
        if phase == "short":
            self.POMO_SHORT_MIN = minutes
        elif phase == "long":
            self.POMO_LONG_MIN = minutes
        else:
            self.POMODORO_MIN = minutes
        self.focus_total_secs = minutes * 60
        if self.focus_paused_secs is not None:
            self.focus_paused_secs = self.focus_total_secs
        else:
            self.focus_end = datetime.now() + timedelta(seconds=self.focus_total_secs)
        self._save_pomodoro()
        self._populate_table()
        self.notify(T("n_dur_set", m=minutes))

    def _save_pomodoro(self) -> None:
        if self.focus_task_id is None:
            session = None
        else:
            session = {
                "task_id": self.focus_task_id,
                "phase": self.focus_phase or "focus",
                "total_secs": self.focus_total_secs,
                "end": self.focus_end.isoformat() if self.focus_end else None,
                "paused_secs": self.focus_paused_secs,
            }
        save_pomodoro(
            {
                "default_minutes": self.POMODORO_MIN,
                "short_minutes": self.POMO_SHORT_MIN,
                "long_minutes": self.POMO_LONG_MIN,
                "long_every": self.POMO_LONG_EVERY,
                "cycle": self.pomo_cycle,
                "session": session,
            }
        )

    def _clear_pomodoro_state(self) -> None:
        self.focus_task_id = None
        self.focus_end = None
        self.focus_paused_secs = None
        self.focus_phase = None

    def _restore_pomodoro(self) -> None:
        """Ripristina ciclo e timer (focus o pausa) dall'ultima sessione salvata."""
        data = getattr(self, "_pending_pomo", None) or load_pomodoro()
        self.POMODORO_MIN = _clamp_int(data.get("default_minutes", 25), 25, 1, 180)
        self.POMO_SHORT_MIN = _clamp_int(data.get("short_minutes", 5), 5, 1, 60)
        self.POMO_LONG_MIN = _clamp_int(data.get("long_minutes", 15), 15, 1, 60)
        self.POMO_LONG_EVERY = _clamp_int(data.get("long_every", 4), 4, 2, 12)
        self.pomo_cycle = _clamp_int(data.get("cycle", 0), 0, 0, 1000)
        self.focus_total_secs = self.POMODORO_MIN * 60
        session = data.get("session")
        if not isinstance(session, dict):
            self._update_pomodoro_bar()
            return
        todo = next((t for t in self.todos if t.id == session.get("task_id")), None)
        if todo is None:
            self._save_pomodoro()
            return
        phase = session.get("phase") if session.get("phase") in POMO_PHASES else "focus"
        try:
            total = int(session.get("total_secs") or self._phase_total_secs(phase))
        except (ValueError, TypeError):
            total = self._phase_total_secs(phase)
        self.focus_task_id = todo.id
        self.focus_phase = phase
        self.focus_total_secs = total
        if session.get("paused_secs") is not None:
            try:
                self.focus_paused_secs = int(session["paused_secs"])
            except (ValueError, TypeError):
                self.focus_paused_secs = total
            self.focus_end = None
            self._populate_table()
            what = (
                T("pomo_what_break")
                if phase in ("short", "long")
                else T("pomo_what_focus")
            )
            self.notify(T("n_rest_paused", w=what, t=todo.title))
            return
        try:
            end = datetime.fromisoformat(str(session.get("end")))
        except (ValueError, TypeError):
            self._clear_pomodoro_state()
            self._save_pomodoro()
            self._populate_table()
            return
        # Consuma le fasi scadute ad app chiusa (focus -> pausa -> ...).
        credited = 0
        break_done: str | None = None
        for _ in range(6):
            if datetime.now() < end:
                break
            if phase == "focus":
                todo.pomodoros += 1
                todo.pomodoro_log.append(end.strftime("%Y-%m-%d %H:%M"))
                self._save_data()
                credited += 1
                self.pomo_cycle += 1
                phase = (
                    "long" if self.pomo_cycle % self.POMO_LONG_EVERY == 0 else "short"
                )
                total = self._phase_total_secs(phase)
                end = end + timedelta(seconds=total)
                continue
            break_done = phase
            if phase == "long":
                self.pomo_cycle = 0
            phase = ""
            break
        if not phase:
            self._clear_pomodoro_state()
            self._save_pomodoro()
            self._populate_table()
            bits = []
            if credited:
                bits.append(T("n_rest_cred", n=credited))
            if break_done:
                bits.append(T("n_rest_breakdone"))
            head = ". ".join(bits) + ". " if bits else T("n_rest_expired") + ". "
            self.notify(head + T("n_rest_total", t=todo.title, n=todo.pomodoros))
            return
        self.focus_phase = phase
        self.focus_total_secs = total
        self.focus_end = end
        self.focus_paused_secs = None
        self._save_pomodoro()
        self._populate_table()
        what = (
            T("pomo_what_break") if phase in ("short", "long") else T("pomo_what_timer")
        )
        extra = T("n_rest_extra", n=credited) if credited else ""
        self.notify(
            T(
                "n_rest_active",
                icon="☕" if phase in ("short", "long") else "🍅",
                w=what,
                t=todo.title,
                extra=extra,
            )
        )

    def _pomodoro_pause_resume(self) -> None:
        if self.focus_task_id is None:
            return
        if self.focus_paused_secs is not None:
            self.focus_end = datetime.now() + timedelta(seconds=self.focus_paused_secs)
            self.focus_paused_secs = None
            self.notify(T("n_resumed"))
        else:
            self.focus_paused_secs = self._pomodoro_remaining_secs()
            self.focus_end = None
            self.notify(T("n_paused"))
        self._save_pomodoro()
        self._populate_table()

    def _pomodoro_stop(self) -> None:
        self._clear_pomodoro_state()
        self._save_pomodoro()
        self._populate_table()
        self.notify(T("n_stopped"))

    def _complete_focus(self) -> None:
        todo = next((t for t in self.todos if t.id == self.focus_task_id), None)
        if todo:
            todo.pomodoros += 1
            todo.pomodoro_log.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
            self._save_data()
        self.pomo_cycle += 1
        kind = "long" if self.pomo_cycle % self.POMO_LONG_EVERY == 0 else "short"
        task_id = self.focus_task_id
        self._start_phase(kind, task_id)
        dots = self._cycle_dots()
        mins = self.POMO_LONG_MIN if kind == "long" else self.POMO_SHORT_MIN
        name = f"su '{todo.title}'" if todo else ""
        self.notify(
            T(
                "n_focus_done",
                name=name,
                dots=dots,
                kind=T("pomo_long_w") if kind == "long" else T("pomo_short_w"),
                mins=mins,
            )
        )

    def _finish_break(self, skipped: bool) -> None:
        was_long = self.focus_phase == "long"
        if was_long:
            self.pomo_cycle = 0
        self._clear_pomodoro_state()
        self._save_pomodoro()
        self._populate_table()
        if skipped:
            self.notify(T("n_skipped"))
        elif was_long:
            self.notify(T("n_long_done"))
        else:
            self.notify(T("n_short_done"))

    def _pomodoro_done(self) -> None:
        if self.focus_task_id is None:
            return
        if (self.focus_phase or "focus") == "focus":
            self._complete_focus()
        else:
            self._finish_break(skipped=True)

    def action_view_kanban(self) -> None:
        self.push_screen(KanbanScreen(self.todos))

    def action_toggle_kanban(self) -> None:
        bar = self.query_one("#kanban-bar", Static)
        bar.set_class(not bar.has_class("hidden"), "hidden")
        self.config["kanban_visible"] = not bar.has_class("hidden")
        self._save_config()
        if not bar.has_class("hidden"):
            self._update_kanban()
            self.notify(T("n_kb_show"))
        else:
            self.notify(T("n_kb_hide"))

    def _focus_label(self) -> str:
        if self.focus_task_id is None:
            return ""
        todo = next((t for t in self.todos if t.id == self.focus_task_id), None)
        name = todo.title[:20] if todo else f"#{self.focus_task_id}"
        secs = self._pomodoro_remaining_secs()
        if self.focus_paused_secs is not None:
            tag = "⏸"
        else:
            tag = "☕" if self._is_break() else "🍅"
        return f"{tag} {name} {secs // 60:02d}:{secs % 60:02d}"

    def _tick_focus(self) -> None:
        if self.focus_task_id is None:
            return
        if self.focus_paused_secs is not None or not self.focus_end:
            return
        if datetime.now() >= self.focus_end:
            self._pomodoro_done()
            return
        try:
            self.query_one("#stats-bar", Static).update(self._stats_text())
            self._update_pomodoro_bar()
        except Exception:
            pass

    def action_undo_delete(self) -> None:
        if not self._undo_stack:
            self.notify(T("n_nothing"), severity="warning")
            return
        restored = self._undo_stack.pop()
        for t in restored:
            if t.id is not None and any(x.id == t.id for x in self.todos):
                t.id = self.next_id
                self.next_id += 1
        self.todos.extend(restored)
        self._trash = [t for t in self._trash if t not in restored]
        self._purge_archive({t.id for t in restored if t.id is not None})
        self._save_data()
        self._populate_table()
        self.notify(T("n_restored", n=len(restored)))

    def _purge_archive(self, ids: set) -> None:
        if not ids:
            return
        try:
            archive = load_archive()
            kept = [
                d for d in archive if not (isinstance(d, dict) and d.get("id") in ids)
            ]
            if len(kept) != len(archive):
                save_archive(kept)
        except Exception:
            pass

    def action_archive_done(self) -> None:
        roots = [t for t in self._get_parents() if t.state == "completato"]
        if not roots:
            self.notify(T("n_arc_none"), severity="warning")
            return
        all_ids = {t.id for t in roots}
        for t in roots:
            all_ids |= {d.id for d in self._get_all_descendants(t.id)}
        removed = [t for t in self.todos if t.id in all_ids]

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                return
            try:
                archive = load_archive()
                archive.extend([t.to_dict() for t in removed])
                save_archive(archive)
            except Exception as exc:
                self.notify(T("n_arc_err", e=exc), severity="error")
                return
            self._undo_stack.append(removed)
            self._trash.extend(removed)
            self.todos = [t for t in self.todos if t.id not in all_ids]
            self._save_data()
            self._populate_table()
            self.notify(T("n_archived", n=len(removed)))

        self.push_screen(
            ConfirmScreen(T("n_arc_confirm", n=len(removed))),
            on_confirm,
        )

    def action_view_archive(self) -> None:
        items: list[TodoItem] = []
        for d in load_archive():
            if not isinstance(d, dict):
                continue
            try:
                items.append(TodoItem.from_dict(d))
            except Exception:
                continue
        items.sort(key=lambda t: (t.completed_at or "", t.title.lower()), reverse=True)
        self.push_screen(ArchiveScreen(items), self._on_archive_action)

    def _on_archive_action(self, result: tuple | None) -> None:
        if not result:
            return
        action, payload = result
        archive = load_archive()
        if action == "all":
            if not archive:
                return
            restored = 0
            for d in archive:
                if not isinstance(d, dict):
                    continue
                try:
                    t = TodoItem.from_dict(d)
                except Exception:
                    continue
                if t.id is None or any(x.id == t.id for x in self.todos):
                    t.id = self.next_id
                    self.next_id += 1
                self.todos.append(t)
                restored += 1
            save_archive([])
            self._save_data()
            self._populate_table()
            self.notify(T("n_arc_emptied", n=restored))
            return
        if action == "one":
            try:
                idx = int(payload)
                raw = archive[idx]
            except (ValueError, TypeError, IndexError):
                return
            if not isinstance(raw, dict):
                return
            try:
                t = TodoItem.from_dict(raw)
            except Exception:
                return
            if t.id is None or any(x.id == t.id for x in self.todos):
                t.id = self.next_id
                self.next_id += 1
            del archive[idx]
            save_archive(archive)
            self.todos.append(t)
            self._save_data()
            self._populate_table()
            self.notify(T("n_arc_one", t=t.title))
            self.action_view_archive()

    def action_new_from_template(self) -> None:
        self._open_template_picker()

    def _open_template_picker(self) -> None:
        self.push_screen(TemplateScreen(self.templates), self._on_template_action)

    def _persist_templates(self) -> None:
        global TEMPLATES
        TEMPLATES = self.templates
        save_templates(self.templates)

    def _on_template_action(self, result: tuple | None) -> None:
        if not result:
            return
        action, payload = result
        if action == "use":
            self._instantiate_template(payload)
        elif action == "delete":
            self._confirm_delete_template(payload)
        elif action == "new":
            self.push_screen(TemplateCreateScreen(), self._on_template_created)
        elif action == "edit":
            self._open_template_editor(payload)
        elif action == "from_project":
            self._open_template_from_project()

    def _instantiate_template(self, name: str) -> None:
        if not name or name not in self.templates:
            return
        created = []
        for item in self.templates[name]:
            todo = TodoItem(
                title=item["title"],
                priority=item.get("priority", Priority.MEDIUM),
                project=name.lower(),
                todo_id=self.next_id,
            )
            self.next_id += 1
            self.todos.append(todo)
            created.append(todo)
        self._save_data()
        self._populate_table()
        self.notify(T("n_tpl_made", n=name, c=len(created)))

    def _confirm_delete_template(self, name: str) -> None:
        if name not in self.templates:
            return

        def on_confirm(confirmed: bool) -> None:
            if not confirmed:
                self._open_template_picker()
                return
            del self.templates[name]
            self._persist_templates()
            self.notify(T("n_tpl_del", n=name))
            self._open_template_picker()

        self.push_screen(ConfirmScreen(T("n_tpl_confirm", n=name)), on_confirm)

    def _on_template_created(self, result: dict | None) -> None:
        if not result:
            self._open_template_picker()
            return
        name = str(result.get("name", "") or "").strip()
        if not name:
            self.notify(T("n_tpl_badname"), severity="error")
            self._open_template_picker()
            return
        if name in self.templates:
            self.notify(T("n_tpl_dup", n=name), severity="error")
            self._open_template_picker()
            return
        items = result.get("items", [])
        if not items:
            self.notify(T("n_tpl_empty"), severity="error")
            self._open_template_picker()
            return
        self.templates[name] = items
        self._persist_templates()
        self.notify(T("n_tpl_created", n=name, c=len(items)))
        self._open_template_picker()

    def _open_template_editor(self, name: str) -> None:
        if not name or name not in self.templates:
            self._open_template_picker()
            return

        def on_edited(result: dict | None) -> None:
            if not result:
                self._open_template_picker()
                return
            new_name = str(result.get("name", "") or "").strip()
            items = result.get("items", [])
            if not new_name or not items:
                self.notify(T("n_tpl_need"), severity="error")
                self._open_template_picker()
                return
            if new_name != name and new_name in self.templates:
                self.notify(T("n_tpl_dup", n=new_name), severity="error")
                self._open_template_picker()
                return
            if new_name != name:
                del self.templates[name]
            self.templates[new_name] = items
            self._persist_templates()
            self.notify(T("n_tpl_updated", n=new_name, c=len(items)))
            self._open_template_picker()

        self.push_screen(
            TemplateCreateScreen({"name": name, "items": self.templates[name]}),
            on_edited,
        )

    def _open_template_from_project(self) -> None:
        counts: dict[str, int] = {}
        for t in self.todos:
            if t.project:
                counts[t.project] = counts.get(t.project, 0) + 1
        if not counts:
            self.notify(T("n_tpl_noproj"), severity="warning")
            self._open_template_picker()
            return
        projects = sorted(counts.items(), key=lambda kv: kv[0])

        def on_pick(project: str | None) -> None:
            if not project:
                self._open_template_picker()
                return
            self._create_template_from_project(project)

        self.push_screen(TemplateProjectScreen(projects), on_pick)

    def _create_template_from_project(self, project: str) -> None:
        source = sorted(
            [t for t in self.todos if t.project == project],
            key=self._sort_key,
        )
        if not source:
            self.notify(T("n_tpl_emptyproj", p=project), severity="warning")
            self._open_template_picker()
            return
        base = project.strip().capitalize() or project
        name = base
        suffix = 2
        while name in self.templates:
            name = f"{base} ({suffix})"
            suffix += 1
        self.templates[name] = [
            {"title": t.title, "priority": t.priority} for t in source
        ]
        self._persist_templates()
        self.notify(T("n_tpl_fromproj", n=name, p=project, c=len(source)))
        self._open_template_picker()

    def action_export_data(self) -> None:
        try:
            out_dir = Path.home() / "Tasko_screenshots"
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            md = out_dir / f"tasko_export_{ts}.md"
            lines = ["# Tasko export", ""]
            for t in sorted(self.todos, key=self._sort_key):
                box = "x" if t.done else " "
                proj = f" @{t.project}" if t.project else ""
                lines.append(
                    f"- [{box}] {t.title}{proj} (scad: {t.due or '-'}, prio: {t.priority.value})"
                )
            md.write_text("\n".join(lines), encoding="utf-8")
            self.notify(T("n_exp_saved", p=md))
        except Exception as exc:
            self.notify(T("n_exp_err", e=exc), severity="error")

    def action_export_stats_csv(self) -> None:
        """Export aggregati giornalieri (CSV): data, completati, pomodori."""
        import csv

        try:
            by_date: dict[str, int] = {}
            for t in self.todos:
                if t.completed_at:
                    k = t.completed_at[:10]
                    by_date[k] = by_date.get(k, 0) + 1
            pomo_by_date: dict[str, int] = {}
            for t in self.todos:
                for ts in getattr(t, "pomodoro_log", []) or []:
                    k = str(ts)[:10]
                    pomo_by_date[k] = pomo_by_date.get(k, 0) + 1
            days = sorted(set(by_date) | set(pomo_by_date))
            out_dir = Path.home() / "Tasko_screenshots"
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path = out_dir / f"tasko_stats_{ts}.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["data", "completati", "pomodori"])
                for d in days:
                    writer.writerow([d, by_date.get(d, 0), pomo_by_date.get(d, 0)])
            self.notify(T("n_stat_saved", p=csv_path, d=len(days)))
        except Exception as exc:
            self.notify(T("n_stat_err", e=exc), severity="error")

    def action_export_csv(self) -> None:
        """Export foglio di calcolo (CSV) in ~/Tasko_screenshots."""
        import csv

        try:
            out_dir = Path.home() / "Tasko_screenshots"
            out_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_path = out_dir / f"tasko_export_{ts}.csv"
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(
                    [
                        "id",
                        "titolo",
                        "stato",
                        "priorita",
                        "scadenza",
                        "progetto",
                        "tags",
                        "creazione",
                        "completato_il",
                        "pomodori",
                        "stima_pomo",
                        "padre",
                        "note",
                    ]
                )
                for t in sorted(self.todos, key=self._sort_key):
                    writer.writerow(
                        [
                            t.id,
                            t.title,
                            t.state,
                            t.priority.value,
                            t.due or "",
                            t.project or "",
                            ";".join(t.tags),
                            t.created or "",
                            t.completed_at or "",
                            t.pomodoros,
                            t.stima_pomo,
                            t.parent_id if t.parent_id is not None else "",
                            (t.notes or "").replace("\r", " "),
                        ]
                    )
            self.notify(T("n_csv_saved", p=csv_path, n=len(self.todos)))
        except Exception as exc:
            self.notify(T("n_csv_err", e=exc), severity="error")

    def action_import_csv(self) -> None:
        try:
            out_dir = Path.home() / "Tasko_screenshots"
            files = (
                sorted(
                    out_dir.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True
                )
                if out_dir.exists()
                else []
            )
        except OSError:
            files = []

        def on_pick(path: str | None) -> None:
            if not path:
                return
            try:
                imported, skipped = self._import_csv_file(path)
            except Exception as exc:
                self.notify(T("n_imp_err", e=exc), severity="error")
                return
            if imported:
                self._save_data()
                self._populate_table()
            msg = T("n_imp_ok", n=imported, f=Path(path).name)
            if skipped:
                msg += T("n_imp_skip", s=skipped)
            self.notify(msg, severity="info" if imported else "warning")

        self.push_screen(ImportCsvScreen(files[:20]), on_pick)

    def _import_csv_file(self, path: str) -> tuple[int, int]:
        """Importa task da CSV (formato export o compatibile). Ritorna (importati, scartati)."""
        import csv

        p = Path(str(path).strip()).expanduser()
        pr_map = {
            "alta": Priority.HIGH,
            "high": Priority.HIGH,
            "media": Priority.MEDIUM,
            "medium": Priority.MEDIUM,
            "bassa": Priority.LOW,
            "low": Priority.LOW,
        }
        with open(p, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return 0, 0
            cols = {c.strip().lower(): c for c in reader.fieldnames if c and c.strip()}

            def col(*names: str) -> str:
                for n in names:
                    if n in cols:
                        v = row.get(cols[n])
                        return str(v or "").strip()
                return ""

            raw_rows: list[dict | None] = []
            for row in reader:
                if not isinstance(row, dict):
                    continue
                title = col("titolo", "title", "name", "task")
                if not title:
                    raw_rows.append(None)
                    continue
                state = col("stato", "state", "status").lower()
                priority = pr_map.get(
                    col("priorita", "priority").lower(), Priority.MEDIUM
                )
                tags_raw = col("tags", "tag", "etichette")
                tags = [
                    t.strip().lower()
                    for t in tags_raw.replace(";", ",").split(",")
                    if t.strip()
                ]
                try:
                    pomodoros = int(col("pomodori", "pomodoros") or 0)
                except (ValueError, TypeError):
                    pomodoros = 0
                try:
                    stima = max(0, int(col("stima_pomo", "stima", "estimate") or 0))
                except (ValueError, TypeError):
                    stima = 0
                try:
                    old_parent = int(col("padre", "parent_id", "parent") or 0) or None
                except (ValueError, TypeError):
                    old_parent = None
                try:
                    old_id = int(col("id") or 0) or None
                except (ValueError, TypeError):
                    old_id = None
                raw_rows.append(
                    {
                        "old_id": old_id,
                        "title": title,
                        "priority": priority,
                        "done": state
                        in ("completato", "completed", "done", "x", "true", "1"),
                        "paused": state
                        in ("in_sospeso", "sospeso", "paused", "suspended"),
                        "due": _normalize_date(col("scadenza", "due", "deadline")),
                        "notes": col("note", "notes", "descrizione"),
                        "project": col("progetto", "project"),
                        "tags": tags,
                        "created": col("creazione", "created"),
                        "completed_at": col("completato_il", "completed_at")[:16],
                        "pomodoros": pomodoros,
                        "stima_pomo": stima,
                        "old_parent": old_parent,
                    }
                )
        # Rimappa gli id (padri compresi) sui nuovi.
        id_map: dict[int, int] = {}
        created: list[TodoItem] = []
        pending_parents: list = []
        skipped = 0
        for raw in raw_rows:
            if raw is None:
                skipped += 1
                continue
            assert raw is not None
            todo = TodoItem(
                title=raw["title"],
                priority=raw["priority"],
                done=raw["done"],
                paused=raw["paused"] and not raw["done"],
                created=raw["created"] or datetime.now().strftime("%Y-%m-%d %H:%M"),
                due=raw["due"],
                notes=raw["notes"],
                project=raw["project"],
                tags=raw["tags"],
                completed_at=raw["completed_at"] if raw["done"] else "",
                pomodoros=raw["pomodoros"],
                stima_pomo=raw.get("stima_pomo", 0),
                todo_id=self.next_id,
            )
            if raw["old_id"] is not None:
                id_map[raw["old_id"]] = self.next_id
            self.next_id += 1
            pending_parents.append(raw["old_parent"])
            created.append(todo)
        for todo, old_parent in zip(created, pending_parents):
            if old_parent is not None and old_parent in id_map:
                todo.parent_id = id_map[old_parent]
        self.todos.extend(created)
        return len(created), skipped

    def action_edit_goals(self) -> None:
        def on_submit(result: dict | None) -> None:
            if not result:
                return
            self.config["daily_goal"] = result["daily"]
            self.config["weekly_goal"] = result["weekly"]
            self.config["pomo_daily_goal"] = result["pomo_daily"]
            self._save_config()
            self._populate_table()
            self.notify(
                T(
                    "n_goals_saved",
                    d=result["daily"],
                    w=result["weekly"],
                    p=result["pomo_daily"],
                )
            )

        self.push_screen(
            GoalsScreen(
                self.config.get("daily_goal", 5),
                self.config.get("weekly_goal", 25),
                self.config.get("pomo_daily_goal", 8),
            ),
            on_submit,
        )

    def action_open_settings(self) -> None:
        def on_submit(result: dict | None) -> None:
            if not result:
                return
            try:
                self.theme = result["theme"]
            except Exception as exc:
                self.notify(T("n_theme_bad", e=exc), severity="error")
                return
            self.config["theme"] = result["theme"]
            self.config["kanban_visible"] = result["kanban_visible"]
            self.config["filter_state"] = result["filter_state"]
            self.config["daily_goal"] = result["daily_goal"]
            self.config["weekly_goal"] = result["weekly_goal"]
            self.config["pomo_daily_goal"] = result["pomo_daily_goal"]
            old_lang = self.config.get("lang", "auto")
            self.config["lang"] = result.get("lang", old_lang)
            self._save_config()
            self.POMODORO_MIN = result["focus_min"]
            self.POMO_SHORT_MIN = result["short_min"]
            self.POMO_LONG_MIN = result["long_min"]
            self.POMO_LONG_EVERY = result["long_every"]
            self._save_pomodoro()
            try:
                bar = self.query_one("#kanban-bar", Static)
                bar.set_class(not result["kanban_visible"], "hidden")
                if result["kanban_visible"]:
                    self._update_kanban()
            except Exception:
                pass
            self._populate_table()
            if result.get("lang", old_lang) != old_lang:
                self.notify(T("n_lang_restart"))
            else:
                self.notify(T("n_settings_saved"))

        current = dict(self.config)
        current.update(
            {
                "focus_min": self.POMODORO_MIN,
                "short_min": self.POMO_SHORT_MIN,
                "long_min": self.POMO_LONG_MIN,
                "long_every": self.POMO_LONG_EVERY,
            }
        )
        self.push_screen(
            SettingsScreen(sorted(self.available_themes.keys()), current), on_submit
        )

    def action_backup_now(self) -> None:
        try:
            path = create_backup()
        except Exception as exc:
            self.notify(T("n_bak_fail", e=exc), severity="error")
            return
        self.notify(T("n_bak_ok", n=path.name))

    def action_restore_backup(self) -> None:
        snaps = list_snapshots()
        if not snaps:
            self.notify(T("n_no_snap"), severity="warning")
            return

        def on_pick(path: str | None) -> None:
            if not path:
                return
            info = snapshot_info(Path(path))

            def on_confirm(confirmed: bool) -> None:
                if not confirmed:
                    return
                try:
                    create_backup()
                except Exception:
                    pass
                try:
                    restore_snapshot(Path(path))
                except Exception as exc:
                    self.notify(T("n_restore_fail", e=exc), severity="error")
                    return
                try:
                    _read_state_file(DATA_FILE)
                except ValueError:
                    self.notify(T("n_restore_badkey"), severity="error")
                    return
                except OSError:
                    pass
                self._reload_all()
                self.notify(T("n_restored_snap", d=info.get("created", "?")))

            self.push_screen(
                ConfirmScreen(T("n_restore_confirm", d=info.get("created", "?"))),
                on_confirm,
            )

        self.push_screen(RestoreScreen(snaps[:20]), on_pick)

    def _reload_all(self) -> None:
        self.todos = self._load_data()
        self.next_id = max((t.id or 0 for t in self.todos), default=0) + 1
        self.templates = load_templates()
        global TEMPLATES
        TEMPLATES = self.templates
        self.config = load_config()
        try:
            if self.config.get("theme") in self.available_themes:
                self.theme = self.config["theme"]
        except Exception:
            pass
        if self.config.get("filter_state") in FILTER_STATES:
            self.filter_state = self.config["filter_state"]
        try:
            bar = self.query_one("#kanban-bar", Static)
            bar.set_class(not self.config.get("kanban_visible", True), "hidden")
        except Exception:
            pass
        if self.focus_task_id is None:
            self._pending_pomo = load_pomodoro()
            self._restore_pomodoro()
        else:
            self._update_pomodoro_bar()
        self._populate_table()
        self._auto_backup()

    def _auto_backup(self) -> None:
        try:
            snaps = list_snapshots()
            if snaps:
                latest = max(p.stat().st_mtime for p in snaps)
                if (
                    datetime.now() - datetime.fromtimestamp(latest)
                ).total_seconds() < 24 * 3600:
                    return
            path = create_backup()
            self.notify(T("n_auto_bak", n=path.name))
        except Exception:
            pass

    def action_open_security(self) -> None:
        self.push_screen(SecurityScreen(_needs_unlock()), self._on_security_action)

    def _on_security_action(self, action: str | None) -> None:
        if action == "enable":
            self.push_screen(
                PasswordScreen(
                    "sec_pw_title_enable",
                    ["sec_pw_new", "sec_pw_repeat"],
                    self._pw_valid_new,
                ),
                self._sec_enable,
            )
        elif action == "change":
            self.push_screen(
                PasswordScreen(
                    "sec_pw_title_change",
                    ["sec_pw_current", "sec_pw_new", "sec_pw_repeat"],
                    self._pw_valid_change,
                ),
                self._sec_change,
            )
        elif action == "disable":
            self.push_screen(
                PasswordScreen(
                    "sec_pw_title_disable", ["sec_pw_current"], self._pw_valid_disable
                ),
                self._sec_disable,
            )

    def _pw_valid_new(self, values: list[str]) -> str | None:
        if any(not v for v in values):
            return T("n_sec_fill")
        new, repeat = values[-2], values[-1]
        if len(new) < 8:
            return T("n_sec_need8")
        if new != repeat:
            return T("n_sec_mismatch")
        return None

    def _pw_valid_change(self, values: list[str]) -> str | None:
        if any(not v for v in values):
            return T("n_sec_fill")
        if not self._sec_current_ok(values[0]):
            return T("n_sec_badcurrent")
        return self._pw_valid_new(values[1:])

    def _pw_valid_disable(self, values: list[str]) -> str | None:
        if any(not v for v in values):
            return T("n_sec_fill")
        if not self._sec_current_ok(values[0]):
            return T("n_sec_badcurrent")
        return None

    def _rewrite_all_state(self) -> None:
        self._save_data()
        save_templates(self.templates)
        self._save_pomodoro()
        try:
            save_archive(load_archive())
        except Exception:
            pass

    def _sec_enable(self, values: list[str] | None) -> None:
        if not values:
            return
        new, repeat = values[0], values[1]
        if len(new) < 8:
            self.notify(T("n_sec_need8"), severity="error")
            return
        if new != repeat:
            self.notify(T("n_sec_mismatch"), severity="error")
            return
        try:
            create_backup()
        except Exception as exc:
            self.notify(T("n_bak_fail", e=exc), severity="error")
            return
        _crypto.set_key(_crypto.password_to_key(new))
        try:
            self._rewrite_all_state()
        except Exception as exc:
            _crypto.set_key(None)
            self.notify(T("n_bak_fail", e=exc), severity="error")
            return
        self._populate_table()
        self.notify(T("n_sec_enabled"))

    def _sec_current_ok(self, password: str) -> bool:
        for name, path in _backup_sources():
            if name == "config":
                continue
            try:
                if path.exists() and not _crypto.try_password(password, path):
                    return False
            except OSError:
                pass
        return True

    def _sec_change(self, values: list[str] | None) -> None:
        if not values:
            return
        old, new, repeat = values[0], values[1], values[2]
        if not self._sec_current_ok(old):
            self.notify(T("n_sec_badcurrent"), severity="error")
            return
        if len(new) < 8:
            self.notify(T("n_sec_need8"), severity="error")
            return
        if new != repeat:
            self.notify(T("n_sec_mismatch"), severity="error")
            return
        _crypto.set_key(_crypto.password_to_key(new))
        try:
            self._rewrite_all_state()
        except Exception as exc:
            self.notify(T("n_bak_fail", e=exc), severity="error")
            return
        self._populate_table()
        self.notify(T("n_sec_changed"))

    def _sec_disable(self, values: list[str] | None) -> None:
        if not values:
            return
        if not self._sec_current_ok(values[0]):
            self.notify(T("n_sec_badcurrent"), severity="error")
            return
        _crypto.set_key(None)
        try:
            self._rewrite_all_state()
        except Exception as exc:
            self.notify(T("n_bak_fail", e=exc), severity="error")
            return
        self._populate_table()
        self.notify(T("n_sec_disabled"))

    def action_refresh(self) -> None:
        self._reload_all()
        self.notify(T("n_reloaded"))

    def action_toggle_help(self) -> None:
        help_panel = self.query_one("#help-panel")
        help_panel.set_class(not help_panel.has_class("hidden"), "hidden")

    def action_show_keys(self) -> None:
        """Apre il popup con tutte le combinazioni di tasti (voce Tasti del menu)."""
        self.push_screen(KeysScreen())

    def action_choose_theme(self) -> None:
        themes = sorted(self.available_themes.keys())

        def on_pick(choice: str | None) -> None:
            if choice is None:
                return
            try:
                self.theme = choice
            except Exception as exc:
                self.notify(T("n_theme_bad", e=exc), severity="error")
                return
            self.config["theme"] = choice
            self._save_config()
            self.notify(T("n_theme", c=choice))

        self.push_screen(ThemeListScreen(themes, self.theme), on_pick)

    def action_toggle_theme(self) -> None:
        # Retro-compatibilità: ciclo semplice tra i due temi storici.
        self.theme = "textual-dark" if self.theme == "matrix" else "matrix"
        self.config["theme"] = self.theme
        self._save_config()
        self.notify(T("n_theme", c=self.theme))

    def action_save_screenshot(self) -> None:
        try:
            path = self._save_screenshot_safe()
            self.notify(T("n_shot_saved", p=path))
        except Exception as exc:
            self.notify(T("n_shot_err", e=exc), severity="error")

    def _save_screenshot_safe(self) -> str:
        out_dir = Path.home() / "Tasko_screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = out_dir / f"tasko_{timestamp}.svg"
        screenshot = self.export_screenshot(title="Tasko")
        output.write_text(screenshot, encoding="utf-8")
        return str(output)

    def deliver_screenshot(
        self,
        filename: str | None = None,
        path: str | None = None,
        time_format: str | None = None,
    ) -> str | None:
        """Override the built-in palette 'Screenshot' command: save to disk locally
        instead of attempting a browser download (which fails outside a browser)."""
        try:
            path = (
                self._save_screenshot_safe()
                if path is None and filename is None
                else None
            )
            if path is not None:
                self.notify(T("n_shot_saved", p=path))
                return None
            out_dir = Path(path) if path else (Path.home() / "Tasko_screenshots")
            out_dir.mkdir(parents=True, exist_ok=True)
            name = filename or f"tasko_{datetime.now().strftime('%Y%m%d_%H%M%S')}.svg"
            output = out_dir / name
            output.write_text(self.export_screenshot(title="Tasko"), encoding="utf-8")
        except Exception as exc:
            self.notify(T("n_shot_err", e=exc), severity="error")
            return None
        self.notify(T("n_shot_saved", p=output))
        return None


def main() -> None:
    TodoApp().run()


if __name__ == "__main__":
    main()
