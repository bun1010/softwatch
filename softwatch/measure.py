"""Surge measurement from exact star timestamps, with the measurement guard.

The guard (handover pack, Pi D6.8 / measurement guard): a 90-day share or ratio is only
reported when the windows were actually observed. Otherwise the status says why, and the
surge classes may not be awarded.
"""
import datetime as dt
from collections import Counter


def _days_ago(now, days):
    return now - dt.timedelta(days=days)


def surge_from_times(starred_at, now, created_at, total_stars, covered_back_to, cfg):
    """
    starred_at: list of aware datetimes for stars collected (newest-first walk, so the
                newest stars are always present).
    covered_back_to: the datetime back to which every star was collected, or None when
                     the walk stopped before reaching the cutoff (truncated).
    Returns a dict; surge_status is 'measured' only when the guard passes.
    """
    out = {
        "surge_status": None, "stars_last90": None, "stars_prior90": None,
        "share90": None, "ratio90": None, "daily": Counter(),
    }
    starred_at = list(starred_at)
    out["daily"] = Counter(t.date().isoformat() for t in starred_at)
    if (now - created_at).days < cfg["min_age_days"]:
        out["surge_status"] = "too_young"
        return out
    if covered_back_to is None or covered_back_to > _days_ago(now, 2 * 90):
        out["surge_status"] = "unmeasurable_truncated"
        return out

    cut90 = _days_ago(now, 90)
    cut180 = _days_ago(now, 180)
    last90 = sum(1 for t in starred_at if t >= cut90)
    prior90 = sum(1 for t in starred_at if cut180 <= t < cut90)
    out["stars_last90"] = last90
    out["stars_prior90"] = prior90
    if prior90 == 0:
        # A zero prior window means no observed data, so the ratio would be meaningless.
        out["surge_status"] = "unmeasurable_no_prior"
        return out
    out["surge_status"] = "measured"
    out["share90"] = last90 / total_stars if total_stars else None
    out["ratio90"] = last90 / prior90
    return out


def velocities(daily, now):
    """Average stars/day over the last 7 and 28 days, from the daily histogram."""
    def window(days):
        total = 0
        for i in range(days):
            day = (now - dt.timedelta(days=i)).date().isoformat()
            total += daily.get(day, 0)
        return total / days
    return window(7), window(28)


def surge_from_anchors(anchors, now, created_at, live_stars, cfg, tolerance=0.02):
    """Surge test from star-history chart anchors (dated cumulative stars).

    Window boundaries snap to chart anchor dates, so no value is interpolated: the
    numbers are differences between recorded anchors. The chart's latest anchor must agree
    with the live star count from the API, or the result is 'inconsistent'.
    """
    out = {"surge_status": None, "stars_last90": None, "stars_prior90": None,
           "share90": None, "ratio90": None, "anchors_last90": 0, "anchors_prior90": 0,
           "history_source": "star_history_svg"}
    if (now - created_at).days < cfg["min_age_days"]:
        out["surge_status"] = "too_young"
        return out
    if not anchors or live_stars is None:
        out["surge_status"] = "unmeasurable_truncated"
        return out
    last_day, last_stars = anchors[-1]
    if (now.date() - last_day).days > 3 or abs(last_stars - live_stars) / live_stars > tolerance:
        out["surge_status"] = "inconsistent"
        return out
    cut90, cut180 = (now - dt.timedelta(days=90)).date(), (now - dt.timedelta(days=180)).date()
    if anchors[0][0] > cut180:
        out["surge_status"] = "unmeasurable_truncated"  # chart does not reach 180 days back
        return out
    a90 = [a for a in anchors if a[0] <= cut90]
    a180 = [a for a in anchors if a[0] <= cut180]
    out["anchors_last90"] = sum(1 for a in anchors if a[0] > cut90)
    out["anchors_prior90"] = sum(1 for a in anchors if cut180 < a[0] <= cut90)
    if not a90 or not a180:
        out["surge_status"] = "unmeasurable_truncated"
        return out
    base90, base180 = a90[-1][1], a180[-1][1]
    last90 = last_stars - base90
    prior90 = base90 - base180
    out["stars_last90"], out["stars_prior90"] = round(last90), round(prior90)
    if prior90 <= 0:
        out["surge_status"] = "unmeasurable_no_prior"
        return out
    if out["anchors_last90"] < 3 or out["anchors_prior90"] < 1:
        out["surge_status"] = "unmeasurable_sparse"
        return out
    out["surge_status"] = "measured"
    out["share90"] = last90 / last_stars
    out["ratio90"] = last90 / prior90
    return out
