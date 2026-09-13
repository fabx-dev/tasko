"""Test persistenza: todos, template, config, pomodoro, archivio, backup."""

import json

import src.main as m


def test_todos_roundtrip(tmp_files):
    todos = [
        m.TodoItem(title="A", todo_id=1, tags=["x"], project="lav"),
        m.TodoItem(title="B", parent_id=1, todo_id=2, pomodoros=2, stima_pomo=4),
    ]
    m._save_todos_plain(todos)
    back = m.load_todos()
    assert [t.title for t in back] == ["A", "B"]
    assert back[1].parent_id == 1 and back[1].stima_pomo == 4


def test_todos_file_corrotto(tmp_files):
    m.DATA_FILE.write_text("{{{rotto")
    assert m.load_todos() == []
    assert m.DATA_FILE.with_suffix(".corrotto.json").exists()


def test_templates_roundtrip_e_default(tmp_files):
    t = m.load_templates()
    assert "Viaggio" in t  # default italiani con lang it
    t["Mio"] = [{"title": "X", "priority": m.Priority.HIGH}]
    m.save_templates(t)
    back = m.load_templates()
    assert back["Mio"][0]["priority"] == m.Priority.HIGH


def test_config_roundtrip_e_fallback(tmp_files):
    m.save_config(
        {
            "theme": "textual-dark",
            "kanban_visible": False,
            "filter_state": "completati",
            "daily_goal": 7,
            "weekly_goal": 20,
            "pomo_daily_goal": 6,
            "lang": "en",
        }
    )
    cfg = m.load_config()
    assert cfg["theme"] == "textual-dark" and cfg["daily_goal"] == 7
    assert cfg["lang"] == "en"
    m.CONFIG_FILE.write_text("rotto{{{")
    assert m.load_config()["theme"] == "matrix"


def test_pomodoro_roundtrip_e_migrazione(tmp_files):
    m.save_pomodoro(
        {
            "default_minutes": 30,
            "short_minutes": 5,
            "long_minutes": 15,
            "long_every": 4,
            "cycle": 2,
            "session": {
                "task_id": 1,
                "phase": "short",
                "total_secs": 300,
                "end": None,
                "paused_secs": 120,
            },
        }
    )
    d = m.load_pomodoro()
    assert d["cycle"] == 2 and d["session"]["phase"] == "short"
    # file vecchio senza fase/ciclo
    m.POMODORO_FILE.write_text(
        json.dumps({"default_minutes": 30, "session": {"task_id": 1}})
    )
    d2 = m.load_pomodoro()
    assert d2["session"]["phase"] == "focus" and d2["cycle"] == 0


def test_archive_roundtrip(tmp_files):
    assert m.load_archive() == []
    m.save_archive([{"id": 1, "title": "A"}])
    assert m.load_archive() == [{"id": 1, "title": "A"}]


def test_backup_giro_completo(tmp_files):
    m.DATA_FILE.write_text(json.dumps([{"id": 1, "title": "A", "priority": "media"}]))
    p = m.create_backup()
    assert p.exists()
    info = m.snapshot_info(p)
    assert info["files"].get("todos") == 1
    m.DATA_FILE.write_text(json.dumps([{"id": 9, "title": "NUOVO"}]))
    m.restore_snapshot(p)
    assert json.loads(m.DATA_FILE.read_text())[0]["title"] == "A"


def test_backup_corrotto_rifiutato(tmp_files):
    bad = m.BACKUP_DIR / "tasko_20990101_000000.zip"
    m.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"not a zip")
    try:
        m.restore_snapshot(bad)
    except OSError:
        pass
    else:
        raise AssertionError("doveva fallire")


def test_backup_retention(tmp_files, monkeypatch):
    from datetime import datetime as _dt

    import src.storage as s

    m.DATA_FILE.write_text("[]")

    class _FakeDT(_dt):
        _calls = 0

        @classmethod
        def now(cls, tz=None):
            cls._calls += 1
            return _dt(2099, 1, 1, 0, 0, cls._calls)

    monkeypatch.setattr(s, "datetime", _FakeDT)
    for _ in range(3):
        m.create_backup()
    m.prune_snapshots(keep=2)
    assert len(m.list_snapshots()) == 2
