import datetime as dt

from softwatch import render

TODAY = dt.date(2026, 11, 23)


def test_none_renders_as_unavailable():
    assert render.fmt(None) == "unavailable"
    assert render.fmt(3, "{:.1f}") == "3.0"


def test_unmeasured_surge_is_stated_not_invented():
    r = {"full_name": "a/b", "class": "emerging", "score": 70, "reason": "",
         "metrics": {"stars": 10, "observed_at": "2026-11-23T06:00:00Z",
                     "surge_status": "unmeasurable_truncated", "artifacts_new_120d": None,
                     "domains_90d": None}}
    text = render.alert_block(r, TODAY)
    assert "surge test: unmeasurable_truncated" in text
    assert "switching: unavailable" in text
    assert "confirmation: unavailable" in text
    assert "falsifier:" in text


def test_resurgent_gets_why_now():
    r = {"full_name": "a/b", "class": "resurgent", "score": 60, "reason": "",
         "metrics": {"stars": 1000, "observed_at": "x", "surge_status": "measured",
                     "stars_last90": 900, "share90": 0.9, "ratio90": 2.0,
                     "artifacts_new_120d": 3, "domains_90d": ["x.dev"],
                     "top_recent_story": None}}
    assert "why now: cause unexplained" in render.alert_block(r, TODAY)


def test_falsifier_has_a_date():
    assert "2027-02-21" in render.falsifier("inflection", TODAY)


def test_notify_empty_when_nothing_to_say():
    assert render.notify_text([], [], False, TODAY, []) == ""


def test_dry_run_is_labelled():
    text = render.notify_text([], ["Health: x"], True, TODAY, [])
    assert text.startswith("[DRY RUN")
