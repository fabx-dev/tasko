"""Test viste calendario/giorno/kanban e filtri tag/progetto."""

from datetime import datetime, timedelta

from tests.conftest import make_app, make_todo, run, screen_texts


def _ds(offset: int) -> str:
    return (datetime.now().date() + timedelta(days=offset)).strftime("%Y-%m-%d")


def test_calendar_mostra_mese_e_task(tmp_files):
    async def t():
        app = make_app([make_todo("A", due=_ds(0)), make_todo("B", due=_ds(5))])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_view_calendar()
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "CalendarScreen"
            txt = screen_texts(app.screen)
            assert "A" in txt or "B" in txt
            await pilot.press("escape")
            await pilot.pause()

    run(t())


def test_day_mostra_task_della_data(tmp_files):
    async def t():
        app = make_app(
            [
                make_todo("Oggi", due=_ds(0)),
                make_todo("Domani", due=_ds(1)),
                make_todo(
                    "Fatto", due=_ds(0), done=True, completed_at=_ds(0) + " 10:00"
                ),
            ]
        )
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            today = datetime.now().date()
            app.action_open_day(today.year, today.month, today.day)
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "DayScreen"
            txt = screen_texts(app.screen)
            assert "Oggi" in txt and "Domani" not in txt
            await pilot.press("escape")
            await pilot.pause()

    run(t())


def test_kanban_full_mostra_colonne(tmp_files):
    async def t():
        app = make_app(
            [
                make_todo("A"),
                make_todo("B", todo_id=2, paused=True),
                make_todo("C", todo_id=3, done=True, completed_at=_ds(0) + " 10:00"),
            ]
        )
        async with app.run_test(size=(130, 40)) as pilot:
            await pilot.pause()
            app.action_view_kanban()
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "KanbanScreen"
            txt = screen_texts(app.screen)
            assert "A" in txt and "B" in txt and "C" in txt
            await pilot.press("escape")
            await pilot.pause()

    run(t())


def test_filtri_tag_e_progetto_ciclano(tmp_files):
    async def t():
        app = make_app(
            [
                make_todo("A", tags=["x"], project="casa"),
                make_todo("B", todo_id=2, tags=["y"], project="lavoro"),
                make_todo("C", todo_id=3),
            ]
        )
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert len(app._row_map) == 3
            app.action_filter_by_tag()
            assert app.filter_tag == "x" and len(app._row_map) == 1
            app.action_filter_by_tag()
            assert app.filter_tag == "y" and len(app._row_map) == 1
            app.action_filter_by_tag()
            assert app.filter_tag is None and len(app._row_map) == 3
            app.action_filter_by_project()
            assert app.filter_project == "casa" and len(app._row_map) == 1
            app.action_filter_by_project()
            assert app.filter_project == "lavoro" and len(app._row_map) == 1
            app.action_filter_by_project()
            assert app.filter_project is None and len(app._row_map) == 3

    run(t())


def test_filtri_senza_tag_o_progetti_avvisano(tmp_files):
    async def t():
        app = make_app([make_todo("A")])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_filter_by_tag()
            assert app.filter_tag is None
            app.action_filter_by_project()
            assert app.filter_project is None

    run(t())
