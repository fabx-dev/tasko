"""Cambia stato (Space): scelta 1/2/3, click, esc, focus sullo stato corrente."""

import asyncio

from textual.widgets import Button

from src.lang import T
from tests.conftest import make_app, make_todo, screen_texts


def run(coro):
    return asyncio.run(coro)


def _open_via_space(pilot, app):
    return pilot.press("space")


def test_space_apre_con_stato_corrente_e_focus(tmp_files):
    async def t():
        app = make_app([make_todo("Da sospendere", todo_id=1, paused=True)])
        app.filter_state = "in_sospeso"
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app._populate_table()
            await pilot.pause()
            await _open_via_space(pilot, app)
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "StateChoiceScreen"
            txt = screen_texts(app.screen)
            assert "Da sospendere" in txt
            assert T("state_sospeso") in txt  # stato attuale nel titolo
            assert T("state_legend") in txt
            # marker sul corrente, focus sul suo bottone
            sospeso_label = str(app.screen.query_one("#sospeso-btn", Button).label)
            assert sospeso_label.startswith("● ")
            assert getattr(app.screen.focused, "id", None) == "sospeso-btn"
            # niente tasti bugiardi: solo [1]/[2]/[3] veri
            assert "O Attivo" not in txt and "P Sospeso" not in txt
            assert "X Fatto" not in txt

    run(t())


def test_tasti_123_cambiano_stato(tmp_files):
    async def t():
        app = make_app([make_todo("A", todo_id=1)])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _open_via_space(pilot, app)
            await pilot.pause()
            await pilot.pause()
            await pilot.press("3")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ != "StateChoiceScreen"
            by_id = {t.id: t for t in app.todos}
            assert by_id[1].done is True

    run(t())


def test_click_sospeso_e_esc_non_scrive(tmp_files):
    async def t():
        app = make_app(
            [make_todo("A", todo_id=1), make_todo("B", todo_id=2, paused=True)]
        )
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # click su Sospeso per il primo task (attivo)
            await _open_via_space(pilot, app)
            await pilot.pause()
            await pilot.pause()
            app.screen.query_one("#sospeso-btn", Button).active_effect_duration = 0
            await pilot.click("#sospeso-btn")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ != "StateChoiceScreen"
            by_id = {t.id: t for t in app.todos}
            assert by_id[1].paused is True
            # esc sul secondo (sospeso): nessun cambiamento
            app.filter_state = "in_sospeso"
            app._populate_table()
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            await _open_via_space(pilot, app)
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "StateChoiceScreen"
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ != "StateChoiceScreen"
            assert by_id[2].paused is True and by_id[2].done is False

    run(t())


def test_enter_sullo_stato_corrente_e_noop(tmp_files):
    async def t():
        app = make_app([make_todo("A", todo_id=1)])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await _open_via_space(pilot, app)
            await pilot.pause()
            await pilot.pause()
            # focus su Attivo (corrente): Enter chiude senza errori
            assert getattr(app.screen.focused, "id", None) == "attivo-btn"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ != "StateChoiceScreen"
            assert app.todos[0].state == "attivo"

    run(t())
