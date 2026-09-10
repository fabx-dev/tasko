# Tasko — contesto per le sessioni agent

> Leggere questo file all'inizio di ogni sessione di lavoro sul repo.
> Se il tuo commit cambia fatti documentati qui (architettura, convenzioni,
> workflow, lezioni apprese), aggiorna questo file nello stesso commit.
> In caso di dubbio, aggiorna.
> Lingua dell'utente: italiano. Risposte concise, niente emoji.

## 1. Cos'è

**Tasko** (`tasko` su PyPI concettuale, entry-point `tasko = src.main:main`) è una
TUI todo-list in italiano/inglese costruita con **Textual** (>=0.86,<4; in venv: 8.2.8).
Python >= 3.12. Repo: `git@github.com:fabx-dev/tasko.git`, branch `main`.

Avvio: `tasko` (TUI) oppure `python -m src.main ...` / `.venv/bin/python -m src.main ...`.
CLI non interattiva: `tasko add|list|done|show` (+ `--porcelain`).

Feature principali: task con 3 stati, sotto-task annidati, ricorrenze, progetti/tag/priorità,
kanban (mini in home + full), calendario, settimana, piano giornaliero, pomodoro persistente
a cicli, template (creabili, anche da progetto), statistiche, goals, salute progetti,
archivio, backup/snapshot zip, import/export CSV + export Markdown, cifratura Fernet opzionale,
onboarding demo, **chiusura giornata** (review serale, tasto `R`).

## 2. Mappa del codice

```
src/main.py      entry point + re-export compatibilità + init lingua PRIMA degli import
src/app.py       TodoApp(App): orchestratore (~2400 righe, 125 metodi) — è la god-class nota
src/screens.py   27 modali (solo models/storage/lang, mai app) — comunicano via push_screen+callback
src/models.py    TodoItem, Priority, Recurrence, validazioni date, MAX_DEPTH=6
src/store.py     TodoStore: lookup id, mutazioni, next_id, commit() = UNICO punto di scrittura todos
src/storage.py   paths, load/save (todos/template/config/archive/pomodoro), lock, merge, backup
src/crypto.py    Fernet + PBKDF2 (600k iter), chiave solo in RAM, envelope {"v","salt","data"}
src/cli.py       add/list/done/show (add/done via TodoStore: lock+merge gratis)
src/commands.py  TaskoMenuProvider (palette `m` / ctrl+p): solo voci senza tasto globale
src/lang.py      catalogo STRINGS it/en + key_sections (help) — vedi §4
tests/           ~76 test; conftest.py con fixture di isolamento (vedi §5)
```

Flusso dati standard nelle action: muta oggetti → `store` → `_save_data()` (= `store.commit()`)
→ `_populate_table()`. Le screen non salvano mai su disco (solo lettura via `_backup_sources`).

## 3. Dati e persistenza

File in home (o `TASKO_HOME` se impostata — usata dai test): `.todo_app.json`,
`.todo_templates.json`, `.todo_config.json`, `.todo_pomodoro.json`, `.todo_archive.json`,
più `.bak.json` / `.corrotto.json` / `.lock` collaterali e `Tasko_backups/*.zip`.

Regole dure:
- Scritture sempre atomiche tmp+fsync+replace, sotto lock fcntl (`_locked`, timeout 10s,
  `StorageLocked` oltre). Niente lock stali (il kernel li rilascia).
- `store.commit()` = lettura+merge+scrittura sotto **un solo lock** (`save_todos_synced`).
  Merge three-way per id (`merge_todo_dicts`): nuovi da entrambi i lati in unione, vince chi
  ha modificato, entrambi modificati vince chi salva, cancellato-vs-modificato vince la
  modifica, stesso id creato da entrambi → disco tiene l'id, nostro riassegnato.
- File cifrato senza chiave in RAM → `[]` **senza** backup `.corrotto` (non è corrotto, è
  blindato). Chiave errata → `[]` + backup. Dopo l'unlock l'app fa `_reload_all()`.

## 4. Convenzioni (rispettarle sempre)

- **i18n**: ogni stringa UI via `T("chiave", ...)`; `test_parita_chiavi` impone stesse chiavi
  it/en — chiavi nuove sempre in entrambe le lingue. `T()` valutato all'import (BINDINGS,
  MENU_IT) segue la lingua fissata da `_apply_startup_lang()` in main: non spostare gli import.
- **CSS**: shell modali condivisa in `TodoApp.CSS` (sezione "Shell modali condivisa": root
  `ModalScreen`, gruppo 24 box, gruppo 12 titoli, gruppi bottoni chiudi). Nuove screen:
  aggiungere i propri `#x-box`/`#x-title` a quei gruppi, dichiarare in screen solo lo specifico.
- **Bottoni**: tutti `variant="default"`; coppie azione = `form_save` ("Salva [ctrl+enter]") +
  `form_cancel` ("Annulla [esc]"); solo visione = `ui_close_esc` ("Chiudi [escape]").
- **Tasti globali**: superficie già ampia (~30 binding). Nuovi tasti solo su richiesta esplicita;
  preferire palette/menu. Convenzione maiuscole = variante (`b/B`, `o/O`, `r` ricarica / `R` review).
- **Mai crash da UI**: except ampi intenzionali (ruff esclude BLE/S110/S112 di proposito).
- Date wall-time `"YYYY-MM-DD [HH:MM]"` (niente aware — romperebbe i dati, ruff esclude DTZ).
- `ruff check` **E** `ruff format --check` (la CI li corre entrambi + pytest su 3.12 e 3.13).

## 5. Verifica (obbligatoria prima di dire "fatto")

- Test: `.venv/bin/python -m pytest tests/ -q`. Mai toccare i file reali di `~`:
  usare `TASKO_HOME` temporanea o la fixture `tmp_files` di conftest (autouse, redireziona
  tutti i path). Precedente grave: un test scrisse su `~/.todo_app.json` cancellando dati veri.
- `conftest` fa `reload()` dei moduli a inizio sessione: nei test usare import di modulo
  (`import src.storage as s`) e non `from ... import nomi` (restano stali).
- Pilot Textual: `async with app.run_test(size=(120, 40))`, `await pilot.pause()` doppia dopo
  le action modali. `SelectionList`: option `(label, value, selected_init)`, metodi
  `select/deselect/toggle(value)`, prop `selected`.
- Screenshot SVG per cambi visivi: script con `TASKO_HOME` **fresca per run** (il restore del
  pomodoro altera i run successivi!), normalizzare le cifre, confrontare per righe di testo
  con coordinate y arrotondate a int (le coordinate sub-pixel fluttuano). Byte-compare = falso.
- LockScreen nei test ad-hoc = file reali cifrati sotto `~`: usare sempre `TASKO_HOME` isolata.

## 6. Git e CI

- Commit piccoli e descrittivi in inglese (stile log esistente). Mai `--force`/push da sandbox.
- **La sandbox NON può pushare** (SSH senza passphrase): commit in locale, l'utente pusha dal
  suo terminale con `git push origin main`, poi si ricontrolla la CI con `gh run list`.
- CI (`.github/workflows/ci.yml`): `ruff check` + `ruff format --check` + pytest su 3.12/3.13.
  Lezione: un push è fallito solo per `ruff format` mai lanciato in locale — correrlo sempre.
- Split di commit misti: classificare hunk per marker (occhio alle righe di contesto vuote nei
  diff, che non hanno prefisso e sballano i conteggi) e validare con round-trip
  stash → apply → commit → md5 dei file. `git apply --check` su un diff del working tree
  fallisce sempre per costruzione: non è un segnale utile.

## 7. Sprint log (fatto)

- **S1**: `TodoStore` + `commit()` centralizzato; `todos`/`next_id` restano property compatibili.
- **S2**: lock fcntl + merge three-way + CLI via store; `test_concurrency.py`, `test_failure_paths.py`.
- **S3**: rimossi `_trash`, `action_toggle_theme`, `_apply_startup_lang` duplicato; CSS condiviso
  (−298 righe); `build/` untracked + gitignore esteso; pyproject 0.3.0 + CHANGELOG Unreleased.
- **S5**: `ReviewScreen` (riepilogo oggi vs goal + pomodori, `SelectionList` candidati con top-3
  preselezionati, conferma = piano di domani esatto); ingresso da palette/menu + tasto `R`;
  `test_review.py`. Fix successivi: bottoni uniformati, box 100 col, label help "chiusura giornata".

## 8. Decisioni aperte (non implementare senza discuterle)

- **Sync**: file-sync (Syncthing/Nextcloud, economico ma cieco) vs server Tasko vs SQLite+replica
  vs CRDT vs BaaS — vedi thread in chat. Dubbi utente sul file-sync ancora aperti.
- **Web app sullo stesso backend** (proposta utente): opzioni A read-only → B server locale CRUD
  (TUI/CLI client, telefono via LAN) → C hosting pubblico. Serve risposta a: basta la LAN?
  autostart invisibile? stack Python+template o altro? Slice A come validazione con stop se inutile.
- Prossimi quick-win mai partiti: stima durata + "smart oggi", export iCal.
- Pomodoro cross-device dichiarato fuori scope v1 (timer resta locale).
