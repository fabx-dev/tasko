"""Integrazione planner Sprint 4: tasto P, proposta, conferma, settings (isolati)."""

import asyncio
import json
from datetime import datetime, timedelta

from textual.widgets import Input, SelectionList

import src.main as m
from src.models import Priority
from tests.conftest import commands_module, make_app, make_todo, screen_texts


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


def test_rientro_ricorda_scarti(tmp_files):
    """Deseleziona -> conferma -> rientra: pianificati nascosti, scarto in fondo
    deselezionato con motivo; riseleziona -> skip azzerato e ripianificato."""
    from src.lang import T as _T

    async def t():
        app = make_app(_todos())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_plan_day()
            await pilot.pause()
            await pilot.pause()
            opts = app.screen.query_one("#planp-list", SelectionList)
            assert set(opts.selected) == {1, 2, 3}
            opts.deselect(3)
            await pilot.press("ctrl+enter")
            await pilot.pause()
            await pilot.pause()
            by_id = {t.id: t for t in app.todos}
            assert by_id[3].planned_for == ""
            assert by_id[3].plan_skip == _day(0)
            # rientro: 1,2 nascosti (gia' pianificati), solo C deselezionato
            app.action_plan_day()
            await pilot.pause()
            await pilot.pause()
            opts = app.screen.query_one("#planp-list", SelectionList)
            assert [o.value for o in opts._options] == [3]
            assert set(opts.selected) == set()
            labels = " ".join(str(o.prompt) for o in opts._options)
            assert _T("plan_skipped") in labels
            # riseleziona C: skip azzerato, 1,2 intoccati (additivo)
            opts.select(3)
            await pilot.press("ctrl+enter")
            await pilot.pause()
            await pilot.pause()
            by_id = {t.id: t for t in app.todos}
            assert by_id[3].planned_for == _day(0)
            assert by_id[3].plan_skip == ""
            assert by_id[1].planned_for == _day(0)
            assert by_id[2].planned_for == _day(0)

    asyncio.run(t())


def test_piano_completo_e_additivo(tmp_files):
    """Piano gia' fatto -> messaggio dedicato; conferma non toglie i pianificati."""

    async def t():
        todos = _todos()
        for t in todos[:2]:
            t.planned_for = _day(0)
        app = make_app(todos)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_plan_day()
            await pilot.pause()
            await pilot.pause()
            opts = app.screen.query_one("#planp-list", SelectionList)
            assert {o.value for o in opts._options} == {3}
            await pilot.press("ctrl+enter")
            await pilot.pause()
            await pilot.pause()
            by_id = {t.id: t for t in app.todos}
            assert by_id[1].planned_for == _day(0)
            assert by_id[2].planned_for == _day(0)
            assert by_id[3].planned_for == _day(0)
            # ora tutto pianificato -> messaggio piano completo
            app.action_plan_day()
            await pilot.pause()
            await pilot.pause()
            from src.lang import T as _T

            assert _T("planp_done") in screen_texts(app.screen)

    asyncio.run(t())


def test_conferma_con_s(tmp_files):
    """Tasto s (terminal-safe) conferma come ctrl+enter."""

    async def t():
        app = make_app(_todos())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_plan_day()
            await pilot.pause()
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            await pilot.pause()
            today = _day(0)
            by_id = {t.id: t for t in app.todos}
            assert by_id[1].planned_for == today
            assert by_id[2].planned_for == today

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
