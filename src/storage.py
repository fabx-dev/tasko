"""Persistenza: paths, load/save todos/template/config/archive/pomodoro/backup."""

import json
from datetime import datetime
from pathlib import Path

from src import crypto as _crypto
from src.lang import T
from src.models import Priority, TodoItem


def _read_state_file(path: Path):
    """Legge JSON con envelope cifrato opzionale.

    Solleva ValueError se il file e' cifrato e la password manca/errata,
    o se il contenuto non e' JSON valido.
    """
    text = path.read_text(encoding="utf-8")  # OSError se manca
    obj, _ = _crypto.unprotect_text(text)
    return obj


def _dump_state_text(obj) -> str:
    """Serializza JSON applicando la cifratura se il lock e' attivo."""
    return _crypto.protect_text(json.dumps(obj, indent=2, ensure_ascii=False))


def state_readable() -> bool:
    """True se il file todos esiste ed e' leggibile (chiave corretta se cifrato)."""
    if not DATA_FILE.exists():
        return True
    try:
        _read_state_file(DATA_FILE)
    except (OSError, ValueError):
        return False
    return True


def _home() -> Path:
    """Base dati: TASKO_HOME se impostata (test/automazioni), altrimenti home reale."""
    import os

    override = os.environ.get("TASKO_HOME", "").strip()
    if override:
        base = Path(override).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        return base
    return Path.home()


DATA_FILE = _home() / ".todo_app.json"


def load_todos() -> list[TodoItem]:
    if not DATA_FILE.exists():
        return []
    try:
        data = _read_state_file(DATA_FILE)
    except (json.JSONDecodeError, OSError, ValueError):
        backup = DATA_FILE.with_suffix(".corrotto.json")
        try:
            backup.write_bytes(DATA_FILE.read_bytes())
        except OSError:
            pass
        return []
    if not isinstance(data, list):
        return []
    todos: list[TodoItem] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            todos.append(TodoItem.from_dict(item))
        except Exception:
            continue
    return todos


def save_todos(todos: list[TodoItem]) -> None:
    import os
    import shutil

    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_dump_state_text([t.to_dict() for t in todos]))
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    # Backup dell'ultima versione valida prima di sovrascrivere.
    if DATA_FILE.exists():
        try:
            shutil.copy2(DATA_FILE, DATA_FILE.with_suffix(".bak.json"))
        except OSError:
            pass
    tmp.replace(DATA_FILE)


TEMPLATE_FILE = _home() / ".todo_templates.json"

DEFAULT_TEMPLATES: dict[str, list[dict]] = {
    T("tpldef_client"): [
        {"title": T("tpldef_kickoff"), "priority": Priority.HIGH},
        {"title": T("tpldef_req"), "priority": Priority.MEDIUM},
        {"title": T("tpldef_quote"), "priority": Priority.HIGH},
        {"title": T("tpldef_contract"), "priority": Priority.MEDIUM},
        {"title": T("tpldef_setup"), "priority": Priority.LOW},
    ],
    T("tpldef_trip"): [
        {"title": T("tpldef_flights"), "priority": Priority.HIGH},
        {"title": T("tpldef_hotel"), "priority": Priority.HIGH},
        {"title": T("tpldef_checkin"), "priority": Priority.MEDIUM},
        {"title": T("tpldef_luggage"), "priority": Priority.LOW},
        {"title": T("tpldef_docs"), "priority": Priority.MEDIUM},
    ],
    T("tpldef_site"): [
        {"title": T("tpldef_wireframe"), "priority": Priority.MEDIUM},
        {"title": T("tpldef_design"), "priority": Priority.MEDIUM},
        {"title": T("tpldef_dev"), "priority": Priority.HIGH},
        {"title": T("tpldef_test"), "priority": Priority.HIGH},
        {"title": T("tpldef_deploy"), "priority": Priority.HIGH},
    ],
}


def _coerce_template_item(raw: dict) -> dict | None:
    title = str(raw.get("title", "") or "").strip()
    if not title:
        return None
    try:
        priority = Priority(str(raw.get("priority", "media")))
    except ValueError:
        # Accetta anche "Priority.HIGH" o "alta" maiuscola
        try:
            priority = Priority(
                str(raw.get("priority", "media")).split(".")[-1].lower()
            )
        except ValueError:
            priority = Priority.MEDIUM
    return {"title": title, "priority": priority}


def load_templates() -> dict[str, list[dict]]:
    if not TEMPLATE_FILE.exists():
        return {
            k: [{"title": i["title"], "priority": i["priority"]} for i in v]
            for k, v in DEFAULT_TEMPLATES.items()
        }
    try:
        data = _read_state_file(TEMPLATE_FILE)
    except (json.JSONDecodeError, OSError, ValueError):
        return {
            k: [{"title": i["title"], "priority": i["priority"]} for i in v]
            for k, v in DEFAULT_TEMPLATES.items()
        }
    if not isinstance(data, dict):
        return {
            k: [{"title": i["title"], "priority": i["priority"]} for i in v]
            for k, v in DEFAULT_TEMPLATES.items()
        }
    out: dict[str, list[dict]] = {}
    for name, items in data.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(items, list):
            continue
        clean = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            item = _coerce_template_item(raw)
            if item:
                clean.append(item)
        if clean:
            out[name.strip()] = clean
    return out or {
        k: [{"title": i["title"], "priority": i["priority"]} for i in v]
        for k, v in DEFAULT_TEMPLATES.items()
    }


def save_templates(templates: dict[str, list[dict]]) -> None:
    import os

    serializable = {
        name: [
            {
                "title": i["title"],
                "priority": i["priority"].value
                if isinstance(i["priority"], Priority)
                else str(i["priority"]),
            }
            for i in items
        ]
        for name, items in templates.items()
    }
    tmp = TEMPLATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_dump_state_text(serializable))
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    tmp.replace(TEMPLATE_FILE)


TEMPLATES: dict[str, list[dict]] = load_templates()


CONFIG_FILE = _home() / ".todo_config.json"
DEFAULT_CONFIG: dict = {
    "theme": "matrix",
    "kanban_visible": True,
    "filter_state": "attivo",
    "daily_goal": 5,
    "weekly_goal": 25,
    "pomo_daily_goal": 8,
    "lang": "auto",
    "onboarded": False,
    "reminder_min": 10,
    "sounds": True,
}


FILTER_STATES = ("attivo", "in_sospeso", "completati", None)


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if not CONFIG_FILE.exists():
        return cfg
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    if isinstance(data.get("theme"), str) and data["theme"].strip():
        cfg["theme"] = data["theme"].strip()
    if isinstance(data.get("kanban_visible"), bool):
        cfg["kanban_visible"] = data["kanban_visible"]
    if "filter_state" in data and data["filter_state"] in FILTER_STATES:
        cfg["filter_state"] = data["filter_state"]
    try:
        daily = int(data.get("daily_goal", 5))
        cfg["daily_goal"] = daily if 0 <= daily <= 100 else 5
    except (ValueError, TypeError):
        cfg["daily_goal"] = 5
    try:
        weekly = int(data.get("weekly_goal", 25))
        cfg["weekly_goal"] = weekly if 0 <= weekly <= 500 else 25
    except (ValueError, TypeError):
        cfg["weekly_goal"] = 25
    try:
        pomo = int(data.get("pomo_daily_goal", 8))
        cfg["pomo_daily_goal"] = pomo if 0 <= pomo <= 100 else 8
    except (ValueError, TypeError):
        cfg["pomo_daily_goal"] = 8
    lang = str(data.get("lang", "auto")).lower()
    cfg["lang"] = lang if lang in ("auto", "it", "en") else "auto"
    cfg["onboarded"] = bool(data.get("onboarded", False))
    try:
        rem = int(data.get("reminder_min", 10))
        cfg["reminder_min"] = rem if 0 <= rem <= 120 else 10
    except (ValueError, TypeError):
        cfg["reminder_min"] = 10
    cfg["sounds"] = bool(data.get("sounds", True))
    return cfg


def save_config(cfg: dict) -> None:
    import os

    payload = {
        "theme": str(cfg.get("theme", DEFAULT_CONFIG["theme"])),
        "kanban_visible": bool(cfg.get("kanban_visible", True)),
        "filter_state": cfg.get("filter_state")
        if cfg.get("filter_state") in FILTER_STATES
        else None,
        "daily_goal": _clamp_int(cfg.get("daily_goal", 5), 5, 0, 100),
        "weekly_goal": _clamp_int(cfg.get("weekly_goal", 25), 25, 0, 500),
        "pomo_daily_goal": _clamp_int(cfg.get("pomo_daily_goal", 8), 8, 0, 100),
        "onboarded": bool(cfg.get("onboarded", False)),
        "reminder_min": _clamp_int(cfg.get("reminder_min", 10), 10, 0, 120),
        "sounds": bool(cfg.get("sounds", True)),
        "lang": str(cfg.get("lang", "auto")).lower()
        if str(cfg.get("lang", "auto")).lower() in ("auto", "it", "en")
        else "auto",
    }
    tmp = CONFIG_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    tmp.replace(CONFIG_FILE)


ARCHIVE_FILE = _home() / ".todo_archive.json"


def load_archive() -> list[dict]:
    if not ARCHIVE_FILE.exists():
        return []
    try:
        data = _read_state_file(ARCHIVE_FILE)
    except (json.JSONDecodeError, OSError, ValueError):
        return []
    return [d for d in data] if isinstance(data, list) else []


def save_archive(items: list[dict]) -> None:
    import os

    tmp = ARCHIVE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_dump_state_text(items))
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    tmp.replace(ARCHIVE_FILE)


BACKUP_DIR = _home() / "Tasko_backups"


BACKUP_KEEP = 14


def _backup_sources() -> tuple[tuple[str, Path], ...]:
    return (
        ("todos", DATA_FILE),
        ("templates", TEMPLATE_FILE),
        ("pomodoro", POMODORO_FILE),
        ("config", CONFIG_FILE),
        ("archive", ARCHIVE_FILE),
    )


def list_snapshots() -> list[Path]:
    try:
        files = sorted(BACKUP_DIR.glob("tasko_*.zip"), reverse=True)
    except OSError:
        return []
    return [p for p in files if p.is_file()]


def _snapshot_manifest(files: dict[str, int]) -> dict:
    return {
        "app": "tasko",
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "files": files,
    }


def create_backup() -> Path:
    """Crea uno snapshot zip di tutti i file di stato + manifest. Ritorna il path."""
    import zipfile

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = BACKUP_DIR / f"tasko_{ts}.zip"
    counts: dict[str, int] = {}
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, path in _backup_sources():
            if path.exists():
                data = path.read_bytes()
                zf.writestr(f"{name}.json", data)
                try:
                    counts[name] = (
                        len(json.loads(data)) if name in ("todos", "archive") else 1
                    )
                except (json.JSONDecodeError, OSError):
                    counts[name] = -1
        zf.writestr("manifest.json", json.dumps(_snapshot_manifest(counts), indent=2))
    # Verifica integrita' subito.
    with zipfile.ZipFile(out) as zf:
        bad = zf.testzip()
    if bad is not None:
        try:
            out.unlink()
        except OSError:
            pass
        raise OSError(f"Snapshot corrotto, scartato: {bad}")
    prune_snapshots()
    return out


def prune_snapshots(keep: int = BACKUP_KEEP) -> None:
    for old in list_snapshots()[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def snapshot_info(path: Path) -> dict:
    """Legge il manifest di uno snapshot (mai eccezioni)."""
    import zipfile

    info: dict = {"name": path.name, "size": 0, "created": "?", "files": {}}
    try:
        info["size"] = path.stat().st_size
        with zipfile.ZipFile(path) as zf:
            raw = zf.read("manifest.json")
        manifest = json.loads(raw)
        info["created"] = str(manifest.get("created", "?"))
        info["files"] = dict(manifest.get("files", {}))
    except Exception:
        pass
    return info


def restore_snapshot(path: Path) -> None:
    """Sostituisce i file di stato con quelli dello snapshot (solo file presenti)."""
    import shutil
    import zipfile

    try:
        zf = zipfile.ZipFile(path)
    except Exception as exc:
        raise OSError(f"Snapshot illeggibile: {exc}")
    with zf:
        bad = zf.testzip()
        if bad is not None:
            raise OSError(f"Snapshot danneggiato: {bad}")
        names = set(zf.namelist())
        for name, dest in _backup_sources():
            if f"{name}.json" not in names:
                continue
            tmp = dest.with_suffix(".restore_tmp")
            with open(tmp, "wb") as f:
                f.write(zf.read(f"{name}.json"))
            shutil.move(str(tmp), str(dest))


POMODORO_FILE = _home() / ".todo_pomodoro.json"


POMO_PHASES = ("focus", "short", "long")
POMO_PHASE_PRESETS: dict[str, tuple[int, ...]] = {
    "focus": (15, 25, 50),
    "short": (3, 5, 10),
    "long": (10, 15, 30),
}

POMO_DEFAULTS: dict = {
    "default_minutes": 25,
    "short_minutes": 5,
    "long_minutes": 15,
    "long_every": 4,
    "cycle": 0,
    "session": None,
}


def _clamp_int(value, default: int, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (ValueError, TypeError):
        return default
    return v if lo <= v <= hi else default


def load_pomodoro() -> dict:
    """Ritorna config ciclo + sessione. Retrocompatibile coi file vecchi."""
    cfg = dict(POMO_DEFAULTS)
    if not POMODORO_FILE.exists():
        return cfg
    try:
        data = _read_state_file(POMODORO_FILE)
    except (json.JSONDecodeError, OSError, ValueError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    cfg["default_minutes"] = _clamp_int(data.get("default_minutes", 25), 25, 1, 180)
    cfg["short_minutes"] = _clamp_int(data.get("short_minutes", 5), 5, 1, 60)
    cfg["long_minutes"] = _clamp_int(data.get("long_minutes", 15), 15, 1, 60)
    cfg["long_every"] = _clamp_int(data.get("long_every", 4), 4, 2, 12)
    cfg["cycle"] = _clamp_int(data.get("cycle", 0), 0, 0, 1000)
    session = data.get("session")
    if isinstance(session, dict):
        if session.get("phase") not in POMO_PHASES:
            session["phase"] = "focus"
        cfg["session"] = session
    return cfg


def save_pomodoro(state: dict) -> None:
    import os

    payload = {
        "default_minutes": _clamp_int(state.get("default_minutes", 25), 25, 1, 180),
        "short_minutes": _clamp_int(state.get("short_minutes", 5), 5, 1, 60),
        "long_minutes": _clamp_int(state.get("long_minutes", 15), 15, 1, 60),
        "long_every": _clamp_int(state.get("long_every", 4), 4, 2, 12),
        "cycle": _clamp_int(state.get("cycle", 0), 0, 0, 1000),
        "session": state.get("session")
        if isinstance(state.get("session"), dict)
        else None,
    }
    tmp = POMODORO_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(_dump_state_text(payload))
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass
    tmp.replace(POMODORO_FILE)
