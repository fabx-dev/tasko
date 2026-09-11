"""Test menu per funzioni (m): categorie, navigazione a 2 livelli, palette."""

import asyncio

import src.commands as commands_module
import src.lang as lang_module
from src.lang import T
from tests.conftest import make_app, make_todo


def run(coro):
    return asyncio.run(coro)


def test_struttura_quattro_categorie_e_action_esistenti(tmp_files):
    cats = commands_module.menu_categories()
    assert len(cats) == 4
    titoli = [c[0] for c in cats]
    assert T("menu_cat_day_t") in titoli
    assert T("menu_cat_sys_t") in titoli
    app = make_app([make_todo("A")])
    totale = 0
    for _ct, _ch, items in cats:
        assert len(items) >= 5
        for _t, _h, action, shortcut in items:
            assert callable(getattr(app, action, None)), action
            assert "[" not in (_t + (_h or "")), (_t, _h)
            if shortcut:
                assert "[" not in shortcut and "]" not in shortcut
            totale += 1
    assert totale >= 29


def test_menu_it_legacy_contiene_chiavi_storiche(tmp_files):
    names = [t for t, _, _ in commands_module.TaskoMenuProvider.MENU_IT]
    actions = [a for _, _, a in commands_module.TaskoMenuProvider.MENU_IT]
    assert "Impostazioni" in names and "Backup: crea ora" in names
    assert "Chiusura giornata" in names and "Salute progetti" in names
    assert "action_plan_day" in actions


def test_provider_palette_prefissa_categoria(tmp_files):
    async def t():
        app = make_app([make_todo("A")])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            prov = commands_module.TaskoMenuProvider(app.screen)
            seen = [t for t, _, _ in prov._iter()]
            assert any("›" in s for s in seen), seen
            assert len(seen) == sum(
                len(c[2]) for c in commands_module.menu_categories()
            )

    run(t())


def test_m_apre_menu_e_ctrl_p_resta_palette(tmp_files):
    actions = {b.key: b.action for b in type(make_app([make_todo("A")])).BINDINGS}
    assert actions.get("m") == "open_menu"
    assert actions.get("ctrl+p") == "command_palette"
    assert type(make_app([make_todo("A")])).COMMAND_PALETTE_BINDING == "ctrl+p"


def _bar_cats(screen):
    return {
        b.id
        for b in screen.query("#menu-bar Button")
        if (b.id or "").startswith("menu-cat-")
    }


def _drop_items(screen):
    if getattr(screen, "_open_idx", None) is None:
        return []
    try:
        if screen.query_one("#menu-drop-row").has_class("hidden"):
            return []
    except Exception:
        return []
    return [b.id for b in screen.query(f"#menu-drop-{screen._open_idx} Button")]


def _drop_labels(screen):
    if getattr(screen, "_open_idx", None) is None:
        return ""
    return " ".join(
        b.label.plain if hasattr(b.label, "plain") else str(b.label)
        for b in screen.query(f"#menu-drop-{screen._open_idx} Button")
    )


def test_navigazione_categorie_voci_e_chiusura(tmp_files):
    async def t():
        app = make_app([make_todo("A")])
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("m")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "MenuScreen"
            # ramo principale: solo le 4 categorie, nessun dropdown aperto
            assert len(_bar_cats(app.screen)) == 4
            assert _drop_items(app.screen) == []
            # click apre il dropdown sotto la voce
            await pilot.click("#menu-cat-0")
            await pilot.pause()
            await pilot.pause()
            assert len(_drop_items(app.screen)) >= 5
            assert T("menu_review_t") in _drop_labels(app.screen)
            # nuovo click sulla stessa voce lo chiude (toggle)
            await pilot.click("#menu-cat-0")
            await pilot.pause()
            await pilot.pause()
            assert _drop_items(app.screen) == []
            assert len(_bar_cats(app.screen)) == 4
            # altra voce: dropdown con le sue voci
            await pilot.click("#menu-cat-1")
            await pilot.pause()
            await pilot.pause()
            assert T("menu_cal_t") in _drop_labels(app.screen)
            # esc chiude il dropdown, resto nel menu
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "MenuScreen"
            assert _drop_items(app.screen) == []
            assert len(_bar_cats(app.screen)) == 4
            # esc chiude il menu
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ != "MenuScreen"

    run(t())


def test_scelta_voce_esegue_action(tmp_files):
    async def t():
        app = make_app([make_todo("A")])
        app.filter_search = "qualcosa"
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.action_open_menu()
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ == "MenuScreen"
            n_cat = len(commands_module.menu_categories())
            await pilot.click(f"#menu-cat-{n_cat - 1}")
            await pilot.pause()
            await pilot.pause()
            target = None
            for b in app.screen.query("#menu-drop Button"):
                label = b.label.plain if hasattr(b.label, "plain") else str(b.label)
                if T("menu_clearf_t") in label:
                    target = "#" + (b.id or "")
                    break
            assert target, "voce Pulisci filtri non trovata"
            await pilot.click(target)
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ != "MenuScreen"
            assert app.filter_search == "" and app.filter_tag is None

    run(t())


def test_frecce_ed_enter_da_tastiera(tmp_files):
    async def t():
        app = make_app([make_todo("A")])
        app.filter_search = "qualcosa"
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("m")
            await pilot.pause()
            await pilot.pause()
            assert getattr(app.screen.focused, "id", None) == "menu-cat-0"
            # destra/sinistra tra le voci principali
            await pilot.press("right")
            await pilot.pause()
            assert getattr(app.screen.focused, "id", None) == "menu-cat-1"
            await pilot.press("left")
            await pilot.pause()
            assert getattr(app.screen.focused, "id", None) == "menu-cat-0"
            # giu apre il dropdown e va alla prima voce
            await pilot.press("down")
            await pilot.pause()
            await pilot.pause()
            assert len(_drop_items(app.screen)) >= 5
            assert getattr(app.screen.focused, "id", None) == "menu-item-0-0"
            # su torna alla voce principale senza chiudere
            await pilot.press("up")
            await pilot.pause()
            assert getattr(app.screen.focused, "id", None) == "menu-cat-0"
            assert len(_drop_items(app.screen)) >= 5
            # giu+giu+enter sulla terza voce di Sistema = Pulisci filtri
            # (destra con dropdown aperto cambia categoria e va in testa)
            await pilot.press("right")
            await pilot.press("right")
            await pilot.press("right")
            await pilot.pause()
            await pilot.pause()
            assert getattr(app.screen.focused, "id", None) == "menu-item-3-0"
            assert T("menu_settings_t") in _drop_labels(app.screen)
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            assert getattr(app.screen.focused, "id", None) == "menu-item-3-2"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            assert type(app.screen).__name__ != "MenuScreen"
            assert app.filter_search == "" and app.filter_tag is None

    run(t())


def test_nuove_chiavi_parita_it_en(tmp_files):
    for key in (
        "menu_cat_day_t",
        "menu_cat_views_t",
        "menu_cat_data_t",
        "menu_cat_sys_t",
        "menu_title",
        "menu_hint",
        "menu_dayplan_t",
        "menu_cal_t",
        "menu_week_t",
        "menu_kbmini_t",
        "menu_kbfull_t",
        "menu_stats_t",
        "menu_tpl_t",
        "menu_theme_t",
        "menu_keys_t",
        "menu_snap_t",
        "menu_refresh_t",
        "menu_quit_t",
    ):
        assert key in lang_module.STRINGS["it"], key
        assert key in lang_module.STRINGS["en"], key
