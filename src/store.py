"""Store centrale dei todo: lookup per id, mutazioni, contatore id, commit unico.

Tutta la logica di lettura/scrittura della lista vive qui; `TodoApp` e CLI
usano lo store invece di manipolare `list[TodoItem]` a mano. Lo store NON
decide quando salvare: `commit()` e' l'unico punto che scrive su disco
(chiamato da `TodoApp._save_data`), così in futuro si può aggiungere
lock/merge in un solo posto (vedi Sprint 2).
"""

from src.models import TodoItem
from src.storage import load_todos, save_todos_synced


class TodoStore:
    """Contenitore mutabile di TodoItem con indice per id.

    Invarianti mantenute dai metodi di scrittura:
    - ogni item presente ha un id intero univoco (assegnato se mancante
      o in collisione);
    - `_next_id` e' sempre > max(id presenti).
    - `_base` e' l'ultimo stato sincronizzato col disco (three-way merge).
    """

    def __init__(self, todos: list[TodoItem] | None = None) -> None:
        self._todos: list[TodoItem] = list(todos) if todos else []
        self._base: list[dict] = [t.to_dict() for t in self._todos]
        self._reindex()

    @classmethod
    def load(cls) -> "TodoStore":
        """Carica da disco (stessa semantica di `load_todos`)."""
        return cls(load_todos())

    # -- lettura ------------------------------------------------------

    def all(self) -> list[TodoItem]:
        """La lista live (stesso oggetto): lettura e passaggio alle screen."""
        return self._todos

    def by_id(self, todo_id: int | None) -> TodoItem | None:
        if todo_id is None:
            return None
        return self._by_id.get(todo_id)

    def has_id(self, todo_id: int | None) -> bool:
        return todo_id is not None and todo_id in self._by_id

    def children(self, parent_id: int | None) -> list[TodoItem]:
        return [t for t in self._todos if t.parent_id == parent_id]

    def descendants(self, todo_id: int | None) -> list[TodoItem]:
        result: list[TodoItem] = []
        for t in self._todos:
            if t.parent_id == todo_id:
                result.append(t)
                result.extend(self.descendants(t.id))
        return result

    def depth(self, todo: TodoItem) -> int:
        depth = 0
        current = todo
        while current.parent_id is not None:
            parent = self.by_id(current.parent_id)
            if parent is None:
                break
            depth += 1
            current = parent
        return depth

    @property
    def next_id(self) -> int:
        """Prossimo id senza consumarlo (peek per `_demo_todos` e simili)."""
        return self._next_id

    @next_id.setter
    def next_id(self, value: int) -> None:
        self._next_id = max(int(value), self._recompute_next())

    # -- scrittura (solo memoria, nessun I/O) --------------------------

    def allocate_id(self) -> int:
        nid = self._next_id
        self._next_id += 1
        return nid

    def add(self, todo: TodoItem) -> TodoItem:
        """Aggiunge un item assegnando l'id se manca o collide. Ritorna todo."""
        if todo.id is None or todo.id in self._by_id:
            todo.id = self.allocate_id()
        else:
            self._next_id = max(self._next_id, todo.id + 1)
        self._todos.append(todo)
        self._by_id[todo.id] = todo
        return todo

    def add_many(self, todos: list[TodoItem]) -> list[TodoItem]:
        for t in todos:
            self.add(t)
        return todos

    def remove_ids(self, ids: set[int | None]) -> list[TodoItem]:
        """Rimuove gli item con id in `ids`, ritorna i rimossi (ordine originale)."""
        wanted = {i for i in ids if i is not None}
        removed = [t for t in self._todos if t.id in wanted]
        if len(removed) == len(self._todos):
            self._todos.clear()
        else:
            self._todos[:] = [t for t in self._todos if t.id not in wanted]
        for t in removed:
            self._by_id.pop(t.id, None)
        return removed

    def replace_all(self, todos: list[TodoItem]) -> None:
        """Sostituisce l'intero contenuto (demo, reload, restore)."""
        self._todos[:] = list(todos)
        self._base = [t.to_dict() for t in self._todos]
        self._reindex()

    def reload(self) -> None:
        """Ricarica da disco, scartando le modifiche non committate."""
        self.replace_all(load_todos())

    # -- persistenza (unico punto di scrittura) -------------------------

    def commit(self) -> None:
        """Merge three-way col disco sotto lock e scrittura atomica.

        Dopo il commit la memoria rispecchia il merged (eventuali item
        aggiunti da altri processi compaiono; i conflitti sullo stesso id
        si risolvono a nostro favore, vedi `merge_todo_dicts`).
        """
        current = [t.to_dict() for t in self._todos]
        merged = save_todos_synced(current, self._base)
        live = {t.id: t for t in self._todos if t.id is not None}
        seen: set[int | None] = set()
        reconciled: list[TodoItem] = []
        for d in merged:
            obj = live.get(d.get("id")) if isinstance(d, dict) else None
            if obj is None or obj.id in seen:
                try:
                    obj = TodoItem.from_dict(d)
                except Exception:
                    continue
            seen.add(obj.id)
            reconciled.append(obj)
        self._todos[:] = reconciled
        self._reindex()
        self._base = [t.to_dict() for t in self._todos]

    # -- interni ---------------------------------------------------------

    def _recompute_next(self) -> int:
        return max((t.id or 0 for t in self._todos), default=0) + 1

    def _reindex(self) -> None:
        self._by_id = {}
        for t in self._todos:
            if t.id is not None:
                self._by_id[t.id] = t  # last-wins su duplicati legacy
        self._next_id = self._recompute_next()
