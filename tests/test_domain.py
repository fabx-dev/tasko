"""Test logica di dominio pura (senza app/pilot)."""

import pytest

from src import domain
from src.models import Priority, Recurrence
from tests.conftest import make_todo


def test_apply_state_attivo_e_sospeso():
    t = make_todo("X", done=True, completed_at="2026-09-10 10:00")
    assert domain.apply_state(t, "attivo", "2026-09-12 10:00") is None
    assert (t.done, t.paused, t.completed_at) == (False, False, "")
    assert domain.apply_state(t, "in_sospeso", "2026-09-12 10:00") is None
    assert (t.done, t.paused, t.completed_at) == (False, True, "")


def test_apply_state_completato_senza_ricorrenza():
    t = make_todo("X", todo_id=1, planned_for="2026-09-12")
    assert domain.apply_state(t, "completato", "2026-09-12 10:00") is None
    assert t.done and not t.paused
    assert t.planned_for == "" and t.completed_at == "2026-09-12 10:00"


def test_apply_state_completato_con_ricorrenza():
    t = make_todo(
        "X",
        todo_id=1,
        due="2026-09-12 09:00",
        recurrence=Recurrence.DAILY,
        project="casa",
        tags=["a"],
        notes="n",
        priority=Priority.HIGH,
        parent_id=7,
    )
    new = domain.apply_state(t, "completato", "2026-09-12 10:00")
    assert t.done and t.completed_at == "2026-09-12 10:00"
    assert new is not None and new.id is None  # id lo assegna lo store
    assert new.due == "2026-09-13 09:00"  # next daily, orario preservato
    assert (new.title, new.project, new.tags, new.notes) == ("X", "casa", ["a"], "n")
    assert new.priority == Priority.HIGH and new.parent_id == 7
    assert new.recurrence == Recurrence.DAILY


def test_apply_state_scelta_invalida():
    with pytest.raises(ValueError):
        domain.apply_state(make_todo("X"), "boh", "2026-09-12 10:00")


def test_credit_pomodoro():
    t = make_todo("X", todo_id=1)
    domain.credit_pomodoro(t, "2026-09-12 10:25")
    domain.credit_pomodoro(t, "2026-09-12 10:55")
    assert t.pomodoros == 2
    assert t.pomodoro_log == ["2026-09-12 10:25", "2026-09-12 10:55"]


def test_apply_form():
    t = make_todo("Vecchio", todo_id=1)
    domain.apply_form(
        t,
        {
            "title": "Nuovo",
            "priority": Priority.HIGH,
            "due": "2026-09-13",
            "notes": "n",
            "recurrence": Recurrence.WEEKLY,
            "tags": ["x"],
            "project": "casa",
            "stima_pomo": 3,
        },
    )
    assert t.title == "Nuovo" and t.priority == Priority.HIGH
    assert t.due == "2026-09-13" and t.recurrence == Recurrence.WEEKLY
    assert t.tags == ["x"] and t.project == "casa" and t.stima_pomo == 3


def test_review_plan_aggiunge_e_toglie():
    a = make_todo("A", todo_id=1)
    b = make_todo("B", todo_id=2, planned_for="2026-09-13")
    c = make_todo("C", todo_id=3, done=True, completed_at="2026-09-12 10:00")
    n, k = domain.review_plan([a, b, c], {1}, "2026-09-13")
    assert (n, k) == (1, 1)
    assert a.planned_for == "2026-09-13" and b.planned_for == ""
    assert c.planned_for == ""  # completati mai toccati


def test_proposal_plan_additivo():
    a = make_todo("A", todo_id=1)
    b = make_todo("B", todo_id=2, planned_for="2026-09-12")
    c = make_todo("C", todo_id=3, done=True, completed_at="2026-09-12 10:00")
    d = make_todo("D", todo_id=4)
    n, r = domain.proposal_plan([a, b, c, d], {1}, "2026-09-12")
    assert (n, r) == (1, 1)  # a aggiunto, d scartato; b gia' pianificato resta
    assert a.planned_for == "2026-09-12" and a.plan_skip == ""
    assert d.plan_skip == "2026-09-12" and d.planned_for == ""
    assert b.planned_for == "2026-09-12" and b.plan_skip == ""
    assert c.planned_for == ""


def test_plan_add_remove_suspend():
    t = make_todo("X", todo_id=1)
    domain.plan_add(t, "2026-09-12")
    assert t.planned_for == "2026-09-12"
    domain.plan_remove(t)
    assert t.planned_for == ""
    domain.plan_add(t, "2026-09-12")
    domain.plan_suspend(t)
    assert t.paused and t.planned_for == "2026-09-12"
