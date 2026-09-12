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
kanban (mini in home + full), agenda cronologica, calendario, settimana, piano giornaliero,
pomodoro persistente a cicli, template (creabili, anche da progetto), statistiche, goals,
salute progetti, archivio, backup/snapshot zip, import/export CSV + export Markdown +
export iCal, cifratura Fernet opzionale, onboarding demo, **chiusura giornata**
(review serale, tasto `R`), inserimento in linguaggio naturale (form `ctrl+l`, CLI add),
buongiorno unificato (tasto `P`: contesto di oggi + proposta con motivi da confermare),
resoconto sera (solo palette, zero rete).

## 2. Mappa del codice

```
src/main.py      entry point + re-export compatibilità + init lingua PRIMA degli import
src/app.py       TodoApp(App): orchestratore (~2570 righe, 166 funzioni) — è la god-class nota
src/screens.py   33 modali (solo models/storage/lang/nlparse, mai app) — via push_screen+callback;
                 MenuScreen a 2 colonne (voci a sx -> sottomenu a dx,
src/nlparse.py   parser deterministico NL it/en → dict uguale al result di TodoFormScreen;
                 sigilli #tag *progetto !prio ~stima //note, parse_with_found() per merge
src/plan.py      plan_day() pura: score, capacita' ore/0.5 🍅, motivi (chiave, params)
src/models.py    TodoItem, Priority, Recurrence, validazioni date, MAX_DEPTH=6;
                 campi extra: stima_pomo, planned_for, plan_skip (scarto piano smart, data)
src/store.py     TodoStore: lookup id, mutazioni, next_id, commit() = UNICO punto di scrittura todos
src/storage.py   paths, load/save (todos/template/config/archive/pomodoro), lock, merge, backup;
                 config include day_hours (default 6, clamp 1-16)
src/crypto.py    Fernet + PBKDF2 (600k iter), chiave solo in RAM, envelope {"v","salt","data"}
src/cli.py       add/list/done/show (add/done via TodoStore: lock+merge gratis); add senza flag = NL
src/commands.py  MENU_STRUCTURE (4 categorie: giornata/viste/dati/sistema, chiavi i18n +
                 action + shortcut) + TaskoMenuProvider (palette `ctrl+p`, titoli
                 "Categoria › Voce"); MENU_IT piatta tenuta per compatibilita'
src/lang.py      catalogo STRINGS it/en + key_sections (help) — vedi §4
tests/           ~146 test; conftest.py con fixture di isolamento (vedi §5)
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
- **Bottoni**: tutti `variant="default"`; coppie azione = `form_save` ("Salva [s]") +
  `form_cancel` ("Annulla [esc]"); solo visione = `ui_close_esc` ("Chiudi [escape]").
  `ctrl+enter` resta come binding secondario ma NON affidarti solo a lui: molti terminali
  (Windows Terminal/WSL) non lo consegnano all'app — `s` funziona ovunque (i campi di
  testo consumano i caratteri, quindi non scatta mentre digiti).
- **Tasti globali**: superficie già ampia (~30 binding). Nuovi tasti solo su richiesta esplicita;
  preferire palette/menu. `m` = menu per funzioni (categorie -> voci),
  `ctrl+p` = palette di ricerca. Convenzione maiuscole = variante (`b/B`, `o/O`, `r` ricarica / `R` review;
  eccezione approvata: `P` = piano smart, coppia di `p` = piano giorno).
- **Nuove screen con lista scrollabile**: box ad altezza definita (`height: 90%`) + figlio
  flessibile (`height: 1fr`) — MAI box auto + `max-height` con figli auto (lezione stats:
  il contenuto sborda o avanza cornice vuota). Vale anche per future revisioni di
  plan-box/rev-box/arc-box (ancora al pattern vecchio).
- **SelectionList**: le label interpretano il markup Rich — niente `[...]` nelle option
  (vengono mangiate come tag di stile); usare parentesi tonde. Precedente: motivo
  di taglio sparito dal piano smart.
- **Edit**: blocchi BINDINGS/CSS duplicati tra classi diverse (es. form vs import-CSV):
  usare sempre contesto ampio in oldString e verificare con grep dove è finito l'edit.
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
- Testo screen nei test: helper `screen_texts()` di conftest (gestisce `.content`/`.renderable`);
  attese via `T(chiave)` non stringhe hardcodate (la lingua effettiva dipende dall'env).
  Mai `.content` diretto: non esiste in tutte le versioni di Textual (la CI installa
  la più recente <4, diversa dalla venv) — ha rotto la CI una volta.
- Script ad-hoc (`python -c`, screenshot): senza `TASKO_LANG=it` l'app parte in inglese
  (auto→locale container). Per output italiani: `TASKO_LANG=it` davanti al comando.
- Screenshot SVG per cambi visivi: script con `TASKO_HOME` **fresca per run** (il restore del
  pomodoro altera i run successivi!), estrazione testo via regex `<text>` + `html.unescape`
  (gli spazi sono `&#160;`: normalizzare prima di cercare), verifica sopra+SOTTO il fold
  (`scroll_end` per i bottoni). Byte-compare = falso.
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
- **AI-1**: `src/nlparse.py` (`parse(text, lang)` → dict del form; `#tag *progetto !prio ~stima`,
  date it/en, regole ambiguità nel docstring) + `tests/test_nlparse.py` (57 it + 49 en).
- **AI-2**: `ctrl+l` nel form (pre-compila + anteprima persistente) + `tasko add "<frase>"` NL
  (con flag = modalità classica, titolo alla lettera); chiavi `nl_*`, `cli_empty_title`;
  `tests/test_nl_integration.py`. Lezione: binding finito per sbaglio su ImportCsvScreen
  (blocchi BINDINGS duplicati) — vedi §4.
- **AI-3**: `src/plan.py` (`plan_day`: pesi espliciti, capacità ore/0.5, `plan_cut`, motivi
  `(chiave, params)`) + chiavi `plan_*` + `tests/test_plan.py` (9 scenari).
- **AI-4**: `PlanProposalScreen` (tasto `P` + palette; conferma SOLO additiva: i già
  pianificati non si ripropongono, per togliere c'è il piano `p` con `x`; scarti del
  giorno in `plan_skip`) + settings `day_hours`; `tests/test_plan_ui.py`. Lezione: `[]`
  mangiati dal markup nelle option — vedi §4.
- **AI-5**: `BriefingScreen` mattina/sera (solo composizione dati esistenti, zero rete) da
  palette; `tests/test_briefing.py`. Stop-criterion manuale: lettura reale 5 giorni.
- **Menu**: `m` = `MenuScreen` a 2 colonne (voci a sx -> sottomenu a dx,
  tutto allineato a sinistra, righe compatte titolo+aiuto; click/Enter apre,
  Enter entra sempre, nuovo click = toggle; frecce + 1-4 + type-to-filter,
  esc a stadi filtro/sottomenu/menu),
  categoria `Giornata` raggruppa le viste temporali (Agenda, piano giorno, piano smart,
  settimana, calendario, briefing/resoconto/review); `ctrl+p` resta palette
  (`TaskoMenuProvider`, titoli "Categoria › Voce") ma è nascosto dal footer
  (`Footer(show_command_palette=False)`); nel footer si mostra solo `m` come `☰ Menu`;
  menu completo anche delle azioni con tasto; `tests/test_menu.py`.
  Lezioni: righe come `MenuRow` (Label focusable), non Button — il Click del
  mouse (on_click sulla riga) e l'Enter (binding activate) restano
  distinguibili (Button.Pressed li confonde) e niente debounce -active;
  alle coordinate dell'evento in bolla non affidarsi (offset consumati);
  il filtro cattura i caratteri in on_key + stop() (i binding globali
  scattano prima); gruppi dropdown pre-costruiti e commutati via classi
  (remove+mount rapidi in sequenza danno `DuplicateIds`); focus via
  `call_after_refresh` con guardia su `_open_idx`.
- **Agenda/iCal/Menu giornata**: `AgendaScreen` cronologica (scaduti, oggi, domani,
  prossimi 7 giorni, alta priorità senza data) solo da menu/palette; export iCal `.ics`
  manuale dei task non completati con `due`; menu ripulito spostando calendario/settimana
  nella categoria `Giornata`; `tests/test_agenda_ical.py`.
- **Health layout**: `HealthScreen` passata al pattern cornice fissa
  (`#hea-box height 90%` + `#hea-list height 1fr`): a terminale piccolo la
  lista sforava e il Chiudi usciva dalla cornice; regression test
  `test_health_layout_terminale_piccolo` (120x40, 80x24, 70x20).
- **Test Pilot**: `pilot.click` ravvicinati sullo stesso `Button` sono inghiottiti
  dal debounce visivo (`-active` 0.2s in `Button._on_click`) — nei test con
  toggle azzerare `active_effect_duration`; dopo i click usare attesa a
  condizione (`_wait_for`) invece di pause fisse (runner CI lenti).
- **Workflow**: `WorkflowScreen` statica (guida operativa checklist in 5 blocchi:
  cattura/mattina/giorno/sera/settimana), prima voce di `Giornata`
  (`action_view_workflow`, nessuno shortcut); chiavi `menu_workflow_*` +
  `workflow_*` it/en; sezione settimana con rimando esplicito a
  `Viste e analisi → Obiettivi`; `tests/test_workflow.py`.
- **Release 0.4.0**: bump `pyproject` 0.3.0 → 0.4.0, CHANGELOG datato 2026-09-12,
  descrizione `pyproject`/README riscritte in tono pratico + installazione in 4 passi
  (pipx consigliato, venv per dev, verifica con `tasko --help`/`list`).
- **Buongiorno unificato**: briefing mattina + piano smart fusi in un'unica
  `PlanProposalScreen` (voce `Buongiorno`, tasto `P`): contesto ex briefing
  (conteggi/carico/ieri/serie) + proposta con motivi inline + stampa `p`;
  `BriefingScreen` resta solo sera (hint morto `R...` → riga guida onesta
  `chiudi + R`); `ReviewScreen` al pattern cornice fissa (`#rev-box 90%` +
  `#rev-list 1fr`) con regression test a 3 taglie; `#brief-*`/`#planp-*`
  nei gruppi CSS condivisi; chiavi `menu_morning_*`, rimosse `menu_plan_*`,
  `menu_brief_*`, `brief_m_title/empty/sec_top/hint`;
  `tests/test_plan_ui.py` (+2), `test_briefing.py` riscritto sera-only,
  `test_review.py` (+layout piccolo).

## 8. Decisioni aperte (non implementare senza discuterle)

- **Sync**: accantonato (idee non chiare) — file-sync vs server vs SQLite+replica vs CRDT
  vs BaaS, vedi thread in chat. Non riaprire di iniziativa.
- **AI provider / Sprint AI-6** (condizionato): parte SOLO se il briefing (AI-5) viene letto
  5 giorni di fila. Design fissato: interfaccia `AIProvider` (Null/Cloud BYOK/locale-stub),
  chiave SOLO da `TASKO_AI_KEY` o file 0600 (mai nel config in chiaro), endpoint
  OpenAI-compatible configurabile, chiamate solo via `run_worker` con fallback a template,
  preview-consenso prima di ogni invio cloud, zero rete nei test (fake provider).
- **Web app sullo stesso backend** (proposta utente): opzioni A read-only → B server locale CRUD
  (TUI/CLI client, telefono via LAN) → C hosting pubblico. Serve risposta a: basta la LAN?
  autostart invisibile? stack Python+template o altro? Slice A come validazione con stop se inutile.
- Quick-win rimasti: da rivalutare dopo agenda/export iCal. ("Smart oggi" fatto dal planner; stime esistevano già.)
- Pomodoro cross-device dichiarato fuori scope v1 (timer resta locale).
