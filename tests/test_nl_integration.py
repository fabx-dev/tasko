"""Integrazione NL Sprint 2: form (ctrl+l) + CLI add (file isolati)."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path as _P

from textual.widgets import Input, Label, Select

from src.models import Priority, Recurrence
from tests.conftest import make_app

PHRASE = "Report *lavoro #ufficio !1 ~2 2026-12-01 09:30"


def test_form_ctrl_l_compila_e_anteprima(tmp_files):
    async def t():
        app = make_app([])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_new_todo()
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "TodoFormScreen"
            app.screen.query_one("#title-input", Input).value = PHRASE
            await pilot.press("ctrl+l")
            await pilot.pause()
            scr = app.screen
            assert scr.query_one("#title-input", Input).value == "Report"
            assert scr.query_one("#due-input", Input).value == "2026-12-01 09:30"
            assert scr.query_one("#project-input", Input).value == "lavoro"
            assert scr.query_one("#tags-input", Input).value == "ufficio"
            assert scr.query_one("#stima-input", Input).value == "2"
            assert scr.query_one("#priority-select", Select).value == Priority.HIGH
            assert scr.query_one("#recurrence-select", Select).value == Recurrence.NONE
            preview = str(scr.query_one("#nl-preview", Label).render())
            assert "2026-12-01 09:30" in preview
            assert "*lavoro" in preview and "#ufficio" in preview
            await pilot.press("ctrl+enter")
            await pilot.pause()
            await pilot.pause()
            assert len(app.todos) == 1
            todo = app.todos[0]
            assert todo.title == "Report"
            assert todo.due == "2026-12-01 09:30"
            assert todo.project == "lavoro"
            assert todo.tags == ["ufficio"]
            assert todo.priority == Priority.HIGH
            assert todo.stima_pomo == 2

    asyncio.run(t())


def test_form_ctrl_l_titolo_vuoto(tmp_files):
    async def t():
        app = make_app([])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_new_todo()
            await pilot.pause()
            await pilot.pause()
            await pilot.press("ctrl+l")
            await pilot.pause()
            assert type(app.screen).__name__ == "TodoFormScreen"

    asyncio.run(t())


def test_form_ctrl_l_nessun_campo(tmp_files):
    async def t():
        app = make_app([])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_new_todo()
            await pilot.pause()
            await pilot.pause()
            app.screen.query_one("#title-input", Input).value = "Solo titolo"
            await pilot.press("ctrl+l")
            await pilot.pause()
            scr = app.screen
            assert scr.query_one("#title-input", Input).value == "Solo titolo"
            assert scr.query_one("#due-input", Input).value == ""

    asyncio.run(t())


def _cli(args, home):
    env = dict(os.environ, TASKO_HOME=str(home))
    return subprocess.run(
        [sys.executable, "-m", "src.main", *args],
        cwd=str(_P(__file__).resolve().parent.parent),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_add_nl(tmp_path):
    home = tmp_path / "home"
    r = _cli(["add", PHRASE], home=home)
    assert r.returncode == 0, r.stderr
    tid = int(r.stdout.strip())
    r = _cli(["list", "--porcelain"], home=home)
    assert r.returncode == 0
    assert f"{tid}|attivo|alta|2026-12-01 09:30|Report" in r.stdout, r.stdout
    r = _cli(["show", str(tid)], home=home)
    assert "lavoro" in r.stdout and "ufficio" in r.stdout


def test_cli_add_classico_invariato(tmp_path):
    home = tmp_path / "home"
    # flag espliciti = titolo alla lettera, zero parsing NL
    r = _cli(["add", "Report domani", "--project", "x"], home=home)
    assert r.returncode == 0, r.stderr
    tid = int(r.stdout.strip())
    r = _cli(["list", "--porcelain"], home=home)
    assert f"{tid}|attivo|media|-|Report domani" in r.stdout, r.stdout


def test_cli_add_titolo_vuoto(tmp_path):
    home = tmp_path / "home"
    r = _cli(["add", ""], home=home)
    assert r.returncode == 2
    r = _cli(["add", "   "], home=home)
    assert r.returncode == 2
    r = _cli(["list", "--porcelain"], home=home)
    assert r.stdout.strip() == ""
