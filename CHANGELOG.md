# Changelog

Format inspired by [Keep a Changelog](https://keepachangelog.com/).
Entries in English from now on.

## [Unreleased]

## [0.3.0] - 2026-09-10

### Added
- Project health view (OK / At risk / Critical) with key and menu entry
- CLI (`add`, `list`, `done`, `show`) with `TASKO_HOME` isolation
- Complete Italian/English coverage: all screens, notifications, dates, defaults
- Due-time reminders polish and fully isolated test fixture

### Fixed
- Removed useless Maximize entry from menu

## [0.2.0] - 2026-09-10

### Added
- Optional file encryption (Fernet) with startup lock screen and Security menu
- Due-time reminders (10 min lead) with bell, pomodoro end sounds, sound settings
- Onboarding with demo data, app settings screen, template editing
- Archive for done tasks with viewer and restore, CSV import
- Goals with streaks, per-project breakdown, peak hours, punctuality, heatmap, stats CSV export
- Full Italian/English UI with system detection

### Fixed
- Isolated test fixture (tests can no longer touch real home files)
- Double detail popup on repeated clicks, pomodoro bar countdown, calendar alignment

## [0.1.0] - 2026-09-09

First public release.

### Added
- Tasks with subtasks, states, priorities, due dates, tags, projects, recurrences, 🍅 estimates
- Home kanban + full board, calendar, week view, daily plan, detail view
- Full pomodoro cycles (focus/short/long breaks) with persistence and live bar
- Stats: goals and streaks, per-project breakdown, time slots, punctuality, heatmap
- Creatable/editable templates, CSV import/export, archive, zip backup + restore
- Optional file encryption (Fernet) with startup lock screen
- Italian/English UI with auto-detection
- pytest suite + CI on Python 3.12/3.13
