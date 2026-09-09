"""Fixture comuni: isolano TUTTI i file reali (mai ~/.todo_* nei test)."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import src.lang as lang  # noqa: E402  (serve sys.path sopra)
import src.main as main  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _italian_module():
    """Riesegue src.main con lingua italiana: BINDINGS deterministici su ogni macchina."""
    import importlib

    lang.set_lang("it")
    importlib.reload(main)
    lang.set_lang("it")
    yield
    lang.set_lang("it")


@pytest.fixture()
def tmp_files(tmp_path, monkeypatch):
    """Redireziona ogni path su file temporanei e ricarica i default."""
    monkeypatch.setattr(main, "DATA_FILE", tmp_path / "todo.json")
    monkeypatch.setattr(main, "TEMPLATE_FILE", tmp_path / "templates.json")
    monkeypatch.setattr(main, "POMODORO_FILE", tmp_path / "pomo.json")
    monkeypatch.setattr(main, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(main, "ARCHIVE_FILE", tmp_path / "archive.json")
    monkeypatch.setattr(main, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(main, "TEMPLATES", main.load_templates())
    return tmp_path


@pytest.fixture()
def italian_lang():
    """Ripristina la lingua italiana dopo il test."""
    lang.set_lang("it")
    yield
    lang.set_lang("it")


def make_todo(title="T", todo_id=1, **kwargs):
    return main.TodoItem(title=title, todo_id=todo_id, **kwargs)


def make_app(todos):
    app = main.TodoApp()
    app.todos = list(todos)
    app.next_id = max((t.id or 0 for t in todos), default=0) + 1
    return app
