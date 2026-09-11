"""Briefing mattina/sera Sprint 5: composizione dati esistenti (isolati)."""

import asyncio
from datetime import datetime, timedelta

from src.lang import T
from tests.conftest import commands_module, make_app, make_todo, screen_texts


def _day(offset: int) -> str:
    return (datetime.now().date() + timedelta(days=offset)).strftime("%Y-%m-%d")


def _todos():
    return [
        make_todo("P-piano", todo_id=1, planned_for=_day(0), stima_pomo=2),
        make_todo("D-oggi", todo_id=2, due=_day(0)),
        make_todo("O-ieri", todo_id=3, due=_day(-1)),
        make_todo(
            "Y-fatto",
            todo_id=4,
            done=True,
            completed_at=_day(-1) + " 10:00",
            pomodoro_log=[_day(-1) + " 10:30"],
        ),
    ]


def test_mattina(tmp_files):
    async def t():
        app = make_app(_todos())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_briefing_morning()
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "BriefingScreen"
            txt = screen_texts(app.screen)
            from src.screens import BriefingScreen as _B

            assert T("brief_m_sec_today") in txt
            assert _B._hero(T("brief_k_plan"), "1") in txt
            assert _B._hero(T("brief_k_due"), "1") in txt
            assert _B._hero(T("brief_k_over"), "1") in txt
            assert T("brief_m_load", s=2, c=12, h=6) in txt
            assert T("brief_m_yest", d=1, p=1) in txt
            assert "O-ieri" in txt  # top proposta
            assert T("plan_overdue") in txt  # motivo su riga propria
            assert "()" not in txt  # niente parentesi vuote
            assert T("stats_serie", n=1) in txt
            from textual.widgets import Button, Static

            statics = [
                str(getattr(w, "content", "") or "") for w in app.screen.query(Static)
            ]
            streak = [s for s in statics if "Serie" in s or "Streak" in s]
            assert streak and all(
                s.startswith("  ") and not s.startswith("   ") for s in streak
            )
            box = app.screen.query_one("#brief-box").region
            btn = app.screen.query_one("#brief-close", Button).region
            assert btn.width >= box.width - 8  # bottone a tutta larghezza
            assert btn.y >= box.y and btn.y + btn.height <= box.y + box.height

    asyncio.run(t())


def test_sera(tmp_files):
    async def t():
        todos = _todos() + [
            make_todo("F-oggi", todo_id=5, done=True, completed_at=_day(0) + " 09:00"),
            make_todo(
                "G-oggi",
                todo_id=6,
                done=True,
                completed_at=_day(0) + " 11:00",
                pomodoro_log=[_day(0) + " 11:30"],
            ),
        ]
        app = make_app(todos)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_briefing_evening()
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "BriefingScreen"
            txt = screen_texts(app.screen)
            assert T("brief_e_sec_done") in txt
            assert "2/5 · 1 🍅  ████░░░░░░" in txt  # barra obiettivo
            assert T("brief_e_sec_left") in txt
            assert "P-piano" in txt  # rimasto in piano
            assert "#1" not in txt  # niente id interni
            assert T("brief_e_hint") in txt

    asyncio.run(t())


def test_vuoto_e_menu(tmp_files):
    names = [action for _t, _h, action in commands_module.TaskoMenuProvider.MENU_IT]
    assert "action_briefing_morning" in names
    assert "action_briefing_evening" in names

    async def t():
        app = make_app([])
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            app.action_briefing_morning()
            await pilot.pause()
            await pilot.pause()
            assert T("brief_m_empty") in screen_texts(app.screen)
            await pilot.press("escape")
            await pilot.pause()
            app.action_briefing_evening()
            await pilot.pause()
            await pilot.pause()
            assert T("brief_e_left_empty") in screen_texts(app.screen)

    asyncio.run(t())
