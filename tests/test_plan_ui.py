"""Integrazione planner Sprint 4: tasto P, proposta, conferma, settings (isolati)."""

import asyncio
import json
from datetime import datetime, timedelta

from textual.widgets import Input, SelectionList

import src.main as m
from src.models import Priority
from tests.conftest import commands_module, make_app, make_todo


def _day(offset: int) -> str:
    return (datetime.now().date() + timedelta(days=offset)).strftime("%Y-%m-%d")


def _todos():
    return [
        make_todo("A-ritardo", todo_id=1, due=_day(-1), priority=Priority.HIGH),
        make_todo("B-oggi", todo_id=2, due=_day(0)),
        make_todo("C-libero", todo_id=3, priority=Priority.LOW),
        make_todo("D-fatto", todo_id=4, due=_day(-5), done=True),
    ]


def test_tasto_p_e_conferma(tmp_files):
    async def t():
        app = make_app(_todos())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("P")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "PlanProposalScreen"
            opts = app.screen.query_one("#planp-list", SelectionList)
            assert len(opts._options) == 3
            assert set(opts.selected) == {1, 2, 3}
            await pilot.press("ctrl+enter")
            await pilot.pause()
            await pilot.pause()
            today = _day(0)
            by_id = {t.id: t for t in app.todos}
            assert by_id[1].planned_for == today
            assert by_id[2].planned_for == today
            assert by_id[3].planned_for == today
            assert by_id[4].planned_for == ""

    asyncio.run(t())


def test_tagliati_non_preselezionati(tmp_files):
    async def t():
        app = make_app(_todos())
        app.config["day_hours"] = 0.5  # capacita' 1 pomo: solo A+B (mandatory)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_plan_day()
            await pilot.pause()
            await pilot.pause()
            opts = app.screen.query_one("#planp-list", SelectionList)
            assert set(opts.selected) == {1, 2}
            from src.lang import T as _T

            labels = " ".join(str(o.prompt) for o in opts._options)
            assert _T("plan_cut") in labels
            await pilot.press("ctrl+enter")
            await pilot.pause()
            await pilot.pause()
            by_id = {t.id: t for t in app.todos}
            assert by_id[1].planned_for == _day(0)
            assert by_id[3].planned_for == ""

    asyncio.run(t())


def test_menu_palette_e_settings_ore(tmp_files):
    names = [action for _t, _h, action in commands_module.TaskoMenuProvider.MENU_IT]
    assert "action_plan_day" in names

    async def t():
        app = make_app([make_todo("A")])
        async with app.run_test(size=(130, 55)) as pilot:
            await pilot.pause()
            app.action_open_settings()
            await pilot.pause()
            await pilot.pause()
            app.screen.query_one("#set-hours", Input).value = "4"
            await pilot.press("ctrl+enter")
            await pilot.pause()
            await pilot.pause()
            assert app.config["day_hours"] == 4
            saved = json.loads(m.CONFIG_FILE.read_text(encoding="utf-8"))
            assert saved["day_hours"] == 4

    asyncio.run(t())
