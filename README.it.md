# Tasko

Todo manager da terminale (TUI Textual) con kanban, cicli pomodoro completi, statistiche, template, backup e interfaccia italiano/inglese.

[Read in English](README.md)

![Tasko home](docs/screenshots/home.svg)
![Tasko stats](docs/screenshots/stats.svg)

## Installazione

```bash
pipx install .
# oppure
pip install .
```

Avvio:

```bash
tasko
```

Serve Python 3.12+. Alternativa Docker: `docker compose up` (dev) o build dal `Dockerfile`.

## Tasti

| Tasto | Azione |
|---|---|
| `n` / `s` | Nuovo todo / sotto-task del selezionato |
| `Space` poi `1/2/3` | Attivo / Sospeso / Fatto |
| `Enter` / `e` | Dettagli (con modifica) / Modifica |
| `d` / `u` | Elimina (conferma) / Annulla eliminazione |
| `o` / `O` / `X` | Avvia-apri pomodoro / pausa-riprendi / completa-salta |
| `b` / `B` | Mini-kanban / board completa |
| `c` / `w` / `p` / `k` | Calendario / settimana / piano / statistiche |
| `f` / `t` / `g` / `/` | Filtri stato, tag, progetto, ricerca |
| `T` / `v` / `m` / `h` | Template / tema / menu / aiuto |
| `q` | Esci |

Il menu `m` raccoglie impostazioni, obiettivi, backup, import/export e archivio. La voce `Tasti` elenca tutto.

## Dati

Tutto in JSON locali vicino alla home (offline-first):

| File | Contenuto |
|---|---|
| `~/.todo_app.json` | Task (+ copia `.bak.json` precedente) |
| `~/.todo_templates.json` | Template |
| `~/.todo_pomodoro.json` | Sessione timer + ciclo |
| `~/.todo_config.json` | Tema, filtri, obiettivi, lingua |
| `~/.todo_archive.json` | Completati archiviati |
| `~/Tasko_backups/` | Snapshot zip automatici (14 tenuti) |
| `~/Tasko_screenshots/` | Screenshot SVG, export CSV/Markdown |

Ripristino dal menu (`Backup: ripristina`). Lingua automatica dal sistema, forzabile con `TASKO_LANG=it|en` o dalle Impostazioni.

## Sviluppo

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
python -m ruff check src/ tests/
```

Vedi [CONTRIBUTING.md](CONTRIBUTING.md). Progetto hobbistico, italiano-first: issue in italiano o inglese benvenute.

## Licenza

MIT — vedi [LICENSE](LICENSE) e [CHANGELOG.md](CHANGELOG.md).
