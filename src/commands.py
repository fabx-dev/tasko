"""Provider comandi per menu/palette."""

from textual.command import DiscoveryHit, Hit, Provider

from src.lang import T


class TaskoMenuProvider(Provider):
    """Voci del menu principale (m): solo configurazione, import/export e utility senza tasto."""

    # (titolo, aiuto, nome action di TodoApp)
    MENU_IT: tuple[tuple[str, str, str], ...] = (
        (T("menu_settings_t"), T("menu_settings_h"), "action_open_settings"),
        (T("menu_health_t"), T("menu_health_h"), "action_view_health"),
        (T("menu_security_t"), T("menu_security_h"), "action_open_security"),
        (T("menu_goals_t"), T("menu_goals_h"), "action_edit_goals"),
        (T("menu_clearf_t"), T("menu_clearf_h"), "action_clear_filters"),
        (T("menu_backup_now_t"), T("menu_backup_now_h"), "action_backup_now"),
        (
            T("menu_backup_restore_t"),
            T("menu_backup_restore_h"),
            "action_restore_backup",
        ),
        (T("menu_exp_md_t"), T("menu_exp_md_h"), "action_export_data"),
        (T("menu_exp_csv_t"), T("menu_exp_csv_h"), "action_export_csv"),
        (T("menu_exp_stats_t"), T("menu_exp_stats_h"), "action_export_stats_csv"),
        (T("menu_imp_csv_t"), T("menu_imp_csv_h"), "action_import_csv"),
        (T("menu_archive_do_t"), T("menu_archive_do_h"), "action_archive_done"),
        (T("menu_archive_view_t"), T("menu_archive_view_h"), "action_view_archive"),
        (T("menu_review_t"), T("menu_review_h"), "action_open_review"),
        (T("menu_plan_t"), T("menu_plan_h"), "action_plan_day"),
    )

    def _iter(self):
        for title, help_text, action_name in self.MENU_IT:
            callback = getattr(self.app, action_name, None)
            if callable(callback):
                yield title, help_text, callback

    async def discover(self):
        for title, help_text, callback in self._iter():
            yield DiscoveryHit(title, callback, help=help_text)

    async def search(self, query: str):
        matcher = self.matcher(query)
        for title, help_text, callback in self._iter():
            if (match := matcher.match(title)) > 0:
                yield Hit(match, matcher.highlight(title), callback, help=help_text)
