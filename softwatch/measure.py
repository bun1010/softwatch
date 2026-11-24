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
