"""Test navigazione tastiera nel menu Temi (v): frecce, Tab, allineamento."""

import asyncio

from tests.conftest import make_app, make_todo


def run(coro):
    return asyncio.run(coro)


def test_temi_frecce_tab_e_allineamento(tmp_files):
    async def t():
        app = make_app([make_todo("A")])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_choose_theme()
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "ThemeListScreen"
            buttons = list(app.screen.query("#theme-list Button"))
            assert len(buttons) >= 2
            # voci allineate a sinistra
            for b in buttons:
                assert str(b.styles.text_align) == "left", b.styles.text_align
            start = getattr(app.screen.focused, "id", None)
            # giu/su si muovono davvero tra i temi (ordine DOM)
            await pilot.press("down")
            await pilot.pause()
            ids = [b.id for b in app.screen.query("#theme-list Button")]
            assert (
                getattr(app.screen.focused, "id", None)
                == ids[(ids.index(start) + 1) % len(ids)]
            )
            await pilot.press("up")
            await pilot.pause()
            assert getattr(app.screen.focused, "id", None) == start
            # Tab scende fino a Chiudi
            for _ in range(len(buttons) + 2):
                if getattr(app.screen.focused, "id", None) == "theme-close":
                    break
                await pilot.press("tab")
                await pilot.pause()
            assert getattr(app.screen.focused, "id", None) == "theme-close"
            # Enter su Chiudi chiude senza cambiare tema
            before = app.theme
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ != "ThemeListScreen"
            assert app.theme == before

    run(t())
