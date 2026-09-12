"""Logica di dominio: transizioni di stato, pomodori, pianificazione.

Contratto:
- niente I/O (mai store/storage), niente UI (mai T()/notify), niente orologi
  impliciti (i timestamp arrivano come parametri espliciti);
- le funzioni mutano SOLO gli oggetti TodoItem passati e ritornano riepiloghi
  (conteggi, nuovi item); deterministiche e testabili senza app/pilot;
- l'app e le screen chiamano queste e persistono via store.commit().
"""

from src.models import Recurrence, TodoItem

STATES = ("attivo", "in_sospeso", "completato")


def apply_state(todo: TodoItem, choice: str, now_str: str) -> TodoItem | None:
    """Transizione di stato. Ritorna l'eventuale nuovo item da ricorrenza
    (senza id: il chiamante lo aggiunge via store.add che lo assegna)."""
    if choice not in STATES:
        raise ValueError(f"stato non valido: {choice!r}")
    if choice == "attivo":
        todo.done = False
        todo.paused = False
        todo.completed_at = ""
    elif choice == "in_sospeso":
        todo.done = False
        todo.paused = True
        todo.completed_at = ""
    else:  # completato
        todo.paused = False
        todo.done = True
        todo.planned_for = ""
        todo.completed_at = now_str
        if todo.recurrence != Recurrence.NONE and todo.due:
            return TodoItem(
                title=todo.title,
                priority=todo.priority,
                due=todo.recurrence.next_date(todo.due),
                notes=todo.notes,
                parent_id=todo.parent_id,
                recurrence=todo.recurrence,
                tags=list(todo.tags),
                project=todo.project,
            )
    return None


def credit_pomodoro(todo: TodoItem, stamp_str: str) -> None:
    """Accredita un pomodoro (contatore + log)."""
    todo.pomodoros += 1
    todo.pomodoro_log.append(stamp_str)


def apply_form(todo: TodoItem, result: dict) -> None:
    """Applica il dict risultato del TodoFormScreen (8 campi)."""
    todo.title = result["title"]
    todo.priority = result["priority"]
    todo.due = result["due"]
    todo.notes = result["notes"]
    todo.recurrence = result["recurrence"]
    todo.tags = result["tags"]
    todo.project = result.get("project", "")
    todo.stima_pomo = result.get("stima_pomo", 0)


def review_plan(
    todos: list[TodoItem], selected_ids: set, tomorrow: str
) -> tuple[int, int]:
    """Piano di domani (Review): aggiunge i selezionati, toglie i deselezionati.
    Solo item attivi. Ritorna (aggiunti, rimossi)."""
    n = k = 0
    for t in todos:
        if t.state != "attivo":
            continue
        if t.id in selected_ids:
            t.planned_for = tomorrow
            n += 1
        elif t.planned_for == tomorrow:
            t.planned_for = ""
            k += 1
    return n, k


def proposal_plan(
    todos: list[TodoItem], selected_ids: set, today: str
) -> tuple[int, int]:
    """Piano smart additivo (Buongiorno): aggiunge i selezionati, marca gli
    scartati in plan_skip. Solo item attivi. Ritorna (aggiunti, rimandati)."""
    n = r = 0
    for t in todos:
        if t.state != "attivo":
            continue
        if t.id in selected_ids:
            t.planned_for = today
            t.plan_skip = ""
            n += 1
        elif t.planned_for != today:
            if t.plan_skip != today:
                r += 1
            t.plan_skip = today
    return n, r


def plan_add(todo: TodoItem, today: str) -> None:
    """Pianifica un item per oggi (piano giorno)."""
    todo.planned_for = today


def plan_remove(todo: TodoItem) -> None:
    """Toglie un item dal piano di oggi (piano giorno)."""
    todo.planned_for = ""


def plan_suspend(todo: TodoItem) -> None:
    """Sospende un item pianificato (piano giorno)."""
    todo.paused = True
