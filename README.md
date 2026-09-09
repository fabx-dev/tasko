# Tasko

Terminal todo manager (Textual TUI) with kanban, full pomodoro cycles, statistics, templates, backups and Italian/English UI.

[Leggimi in italiano](README.it.md)

![Tasko home](docs/screenshots/home.svg)
![Tasko stats](docs/screenshots/stats.svg)

## Install

```bash
pipx install .
# or
pip install .
```

Run with:

```bash
tasko
```

Requires Python 3.12+. Docker alternative: `docker compose up` (dev) or build from `Dockerfile`.

## Keys

| Key | Action |
|---|---|
| `n` / `s` | New todo / subtask of selected |
| `Space` then `1/2/3` | Active / Paused / Done |
| `Enter` / `e` | Details (with inline edit) / Edit |
| `d` / `u` | Delete (confirm) / Undo |
| `o` / `O` / `X` | Start-open pomodoro / pause-resume / complete-skip |
| `b` / `B` | Mini-kanban / full board |
| `c` / `w` / `p` / `k` | Calendar / week / daily plan / stats |
| `f` / `t` / `g` / `/` | State, tag, project, search filters |
| `T` / `v` / `m` / `h` | Templates / theme / menu / help |
| `q` | Quit |

Press `m` for the menu (settings, goals, backup, import/export, archive). Press `Tasti` there for the full key list.

## Data

Everything lives in local JSON next to your home (offline-first):

| File | Content |
|---|---|
| `~/.todo_app.json` | Tasks (+ `.bak.json` previous copy) |
| `~/.todo_templates.json` | Templates |
| `~/.todo_pomodoro.json` | Timer session + cycle |
| `~/.todo_config.json` | Theme, filters, goals, language |
| `~/.todo_archive.json` | Archived done tasks |
| `~/Tasko_backups/` | Automatic zip snapshots (14 kept) |
| `~/Tasko_screenshots/` | SVG screenshots, CSV/Markdown exports |

Restore a backup any time from the menu (`Backup: ripristina`). Language follows the system (Italian or English), override with `TASKO_LANG=it|en` or in Settings.

## Dev

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
python -m ruff check src/ tests/
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Hobby project, Italian-first: issues in Italian or English welcome.

## License

MIT — see [LICENSE](LICENSE) and [CHANGELOG.md](CHANGELOG.md).
