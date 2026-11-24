import datetime as dt

from softwatch.config import load
from softwatch.measure import surge_from_times, velocities

CFG = load()["surge"]
NOW = dt.datetime(2026, 11, 23, 12, tzinfo=dt.timezone.utc)


def days_ago(d):
    return NOW - dt.timedelta(days=d)


def test_measured_surge_passes_guard():
    times = [days_ago(10)] * 300 + [days_ago(120)] * 100
    r = surge_from_times(times, NOW, days_ago(900), 400, days_ago(400), CFG)
    assert r["surge_status"] == "measured"
    assert r["stars_last90"] == 300 and r["stars_prior90"] == 100
    assert r["ratio90"] == 3.0
    assert r["share90"] == 0.75


def test_truncated_walk_is_unmeasurable():
    # Walk hit the page cap before reaching 180 days back: the prior window is unobserved.
    r = surge_from_times([days_ago(1)] * 50, NOW, days_ago(3000), 150000, None, CFG)
    assert r["surge_status"] == "unmeasurable_truncated"
    assert r["ratio90"] is None and r["share90"] is None


def test_zero_prior_window_is_unmeasurable_not_infinite():
    r = surge_from_times([days_ago(5)] * 20, NOW, days_ago(900), 20, days_ago(900), CFG)
    assert r["surge_status"] == "unmeasurable_no_prior"
    assert r["ratio90"] is None


def test_young_repo_is_too_young():
    r = surge_from_times([days_ago(1)], NOW, days_ago(60), 1, days_ago(60), CFG)
    assert r["surge_status"] == "too_young"


def test_velocities_from_daily_histogram():
    daily = {(NOW - dt.timedelta(days=i)).date().isoformat(): 10 for i in range(7)}
    v7, v28 = velocities(daily, NOW)
    assert v7 == 10.0
    assert v28 == 70 / 28
