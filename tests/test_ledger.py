import datetime as dt

from softwatch.db import connect, iso
from softwatch.pipeline import _ledger_allows
from softwatch.config import load

CFG = load()
NOW = dt.datetime(2026, 11, 23, 12, tzinfo=dt.timezone.utc)


def con_with_alert(tmp_path, last_days_ago, cls, score):
    (tmp_path / "x").mkdir(parents=True, exist_ok=True)
    con = connect(tmp_path / "x" / "t.db")
    last = NOW - dt.timedelta(days=last_days_ago)
    con.execute("INSERT INTO alerts VALUES(?,?,?,?,?,1,?)",
                ("a/b", iso(last), iso(last), cls, score, "r0"))
    return con


def test_never_alerted_is_allowed(tmp_path):
    (tmp_path / "x").mkdir(parents=True, exist_ok=True)
    con = connect(tmp_path / "x" / "t.db")
    assert _ledger_allows(con, "a/b", "inflection", 80, NOW, CFG)


def test_no_duplicate_within_min_days(tmp_path):
    # Surge path and score path both produce the repo: one alert per 7 days.
    con = con_with_alert(tmp_path, 2, "inflection", 80)
    assert not _ledger_allows(con, "a/b", "resurgent", 90, NOW, CFG)


def test_class_upgrade_allowed_after_min_days(tmp_path):
    con = con_with_alert(tmp_path, 10, "climber", 70)
    assert _ledger_allows(con, "a/b", "inflection", 80, NOW, CFG)


def test_same_class_needs_60_days_and_score_rise(tmp_path):
    con = con_with_alert(tmp_path, 30, "climber", 70)
    assert not _ledger_allows(con, "a/b", "climber", 85, NOW, CFG)
    con2 = con_with_alert(tmp_path / "second", 70, "climber", 70)
    assert _ledger_allows(con2, "a/b", "climber", 85, NOW, CFG)
