import datetime as dt
from pathlib import Path

import pytest

from softwatch.config import load
from softwatch.measure import surge_from_anchors
from softwatch.sources.star_history import ChartError, consistent_with, parse

FIX = Path(__file__).parent / "fixtures" / "star_history"
CFG = load()["surge"]


def _svg(name):
    return (FIX / name).read_text()


def test_omarchy_first_anchor_is_creation_date_and_last_matches_api_scale():
    r = parse(_svg("omarchy.svg"))
    assert r["anchors"][0][0] == dt.date(2025, 6, 1)  # repo created 2025-06-01
    assert r["anchors"][-1][0] == dt.date(2026, 11, 24)
    assert abs(r["anchors"][-1][1] - 47493) / 47493 < 0.02  # REST count seen in the run
    assert r["x_residual_days"] < 1 and r["y_residual"] < 1


def test_ollama_parses_with_k_scale():
    r = parse(_svg("ollama.svg"))
    assert r["anchors"][-1][1] > 100000


def test_chromium_year_labels_only_parses():
    r = parse(_svg("chromium.svg"))
    assert r["anchors"][0][0].year == 2018
    assert 20000 < r["anchors"][-1][1] < 30000


def test_non_svg_is_rejected():
    with pytest.raises(ChartError):
        parse("<html>nope</html>")


def test_chart_with_no_date_anchor_is_rejected():
    svg = _svg("omarchy.svg").replace("2026</text>", "x</text>").replace(">2026<", ">x<")
    with pytest.raises(ChartError):
        parse(svg)


NOW = dt.datetime(2026, 11, 24, 12, tzinfo=dt.timezone.utc)


def _anchors(points):
    return [(NOW.date() - dt.timedelta(days=d), s) for d, s in points]


def test_surge_measured_from_anchors_with_no_interpolation():
    # oldest first: 180+ days back, then anchors in the prior and last windows
    a = _anchors([(200, 100), (150, 300), (120, 500), (60, 900), (30, 1200), (1, 1500)])
    r = surge_from_anchors(a, NOW, NOW - dt.timedelta(days=900), 1500, CFG)
    assert r["surge_status"] == "measured"
    assert r["stars_last90"] == 1500 - 500  # base at latest anchor <= 90 days ago is 500
    assert r["stars_prior90"] == 500 - 100
    assert r["anchors_last90"] >= 3


def test_inconsistent_chart_is_not_used():
    a = _anchors([(200, 100), (100, 500), (1, 1500)])
    r = surge_from_anchors(a, NOW, NOW - dt.timedelta(days=900), 9000, CFG)
    assert r["surge_status"] == "inconsistent"


def test_sparse_chart_is_unmeasurable_not_surge():
    a = _anchors([(200, 100), (120, 500), (1, 900)])
    r = surge_from_anchors(a, NOW, NOW - dt.timedelta(days=900), 900, CFG)
    assert r["surge_status"] == "unmeasurable_sparse"
    assert r["ratio90"] is None


def test_chart_not_reaching_180_days_is_truncated():
    a = _anchors([(100, 500), (1, 900)])
    r = surge_from_anchors(a, NOW, NOW - dt.timedelta(days=900), 900, CFG)
    assert r["surge_status"] == "unmeasurable_truncated"


def test_small_prior_base_is_not_a_ratio():
    # 96 stars in the prior window: measurable in principle, but the ratio is not trustworthy
    a = _anchors([(200, 100), (150, 300), (120, 196), (60, 380), (30, 420), (1, 4500)])
    r = surge_from_anchors(a, NOW, NOW - dt.timedelta(days=900), 4500, CFG)
    assert r["stars_prior90"] == 96
    assert r["surge_status"] == "unmeasurable_small_base"
    assert r["ratio90"] is None
