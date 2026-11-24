"""Daily pipeline: measure -> ecosystem -> confirm -> score -> alert.

Stage order follows the irreplaceability rule (handover D6.10): surge measurement runs first,
so a later stage cannot starve it. Each source failure is recorded, and the affected value is
stored as NULL, never as zero."""
import datetime as dt
import json
import tomllib
from pathlib import Path
from urllib.parse import urlparse

from . import render
from .budget import Budget
from .collision import anchor_for, name_collision_rate
from .db import iso, log_source, upsert_repo
from .http import Http, SourceError
from .measure import surge_from_anchors
from .score import CLASS_RANK, classify, components
from .sources.github import GitHub
from .sources import star_history
from .sources.hn import HN

ROOT = Path(__file__).resolve().parent.parent
ALERT_CLASSES = {"inflection", "resurgent", "climber"}


def load_seeds(path=ROOT / "seeds" / "test_set.toml"):
    with open(path, "rb") as f:
        return [r["full_name"] for r in tomllib.load(f)["repo"]]


def _own_domain(homepage):
    if not homepage:
        return None
    host = urlparse(homepage if "://" in homepage else f"https://{homepage}").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _ledger_allows(con, full_name, cls, score, now, cfg):
    row = con.execute("SELECT * FROM alerts WHERE full_name=?", (full_name,)).fetchone()
    if row is None:
        return True
    last = dt.datetime.fromisoformat(row["last_alerted"].replace("Z", "+00:00"))
    days = (now - last).days
    if days < cfg["alerts"]["per_repo_min_days"]:
        return False
    if CLASS_RANK.get(cls, 0) > CLASS_RANK.get(row["last_class"], 0):
        return True
    return (days >= cfg["alerts"]["realert_days"] and score - (row["last_score"] or 0) >=
            cfg["alerts"]["realert_score_delta"] and cls in ("climber", "resurgent", "inflection"))


def measure_repo(full_name, gh, hn, con, run_id, now, cfg, canary_ok, errors):
    """Returns the metrics dict for one repo, or None if it should be skipped."""
    owner, name = full_name.split("/", 1)
    m = {"full_name": full_name, "name": name, "owner": owner}

    rest = gh.repo(full_name)
    if rest is None:
        errors.append(f"{full_name}: not found")
        return None
    if rest["archived"] or rest["fork"]:
        errors.append(f"{full_name}: archived or fork, skipped")
        return None
    upsert_repo(con, full_name, None, created_at=iso(rest["created_at"]),
                description=rest["description"], topics=rest["topics"],
                homepage=rest["homepage"], language=rest["language"], now=now)
    observed = iso(now)
    con.execute("INSERT OR REPLACE INTO snapshots VALUES(?,?,?,?,?,?,?)",
                (full_name, observed, rest["stars"], rest["forks"], rest["open_issues"],
                 rest["pushed_at"], 0))
    m.update(stars=rest["stars"], forks=rest["forks"], open_issues=rest["open_issues"],
             topics=rest["topics"], description=rest["description"], observed_at=observed,
             age_days=(now - rest["created_at"]).days, created_at=rest["created_at"],
             fork_ratio=rest["forks"] / rest["stars"] if rest["stars"] else None,
             issue_ratio=rest["open_issues"] / rest["stars"] if rest["stars"] else None)

    # 1. Surge measurement from star-history chart anchors (no GitHub stargazer API needed).
    # The chart's own anchors are the data; the guard in measure.surge_from_anchors decides.
    try:
        svg = gh.star_history_svg(full_name)
        chart = star_history.parse(svg)
        surge = surge_from_anchors(chart["anchors"], now, rest["created_at"], rest["stars"],
                                   cfg["surge"], cfg["surge"]["consistency_tolerance"])
        con.execute("INSERT OR REPLACE INTO surge VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (full_name, observed, surge["surge_status"], surge["stars_last90"],
                     surge["stars_prior90"], surge["share90"], surge["ratio90"],
                     chart["anchors"][0][0].isoformat() if chart["anchors"] else None,
                     len(chart["anchors"]), None, None, surge["anchors_last90"]))
        m.update(surge_status=surge["surge_status"], stars_last90=surge["stars_last90"],
                 stars_prior90=surge["stars_prior90"], share90=surge["share90"],
                 ratio90=surge["ratio90"], history_source="star_history_svg",
                 anchors_last90=surge["anchors_last90"],
                 # No velocity from sparse anchors: acceleration is reported unavailable.
                 vel7=None, vel28=None, suspicious_stars=False)
    except (SourceError, star_history.ChartError) as e:
        errors.append(f"{full_name}: surge measurement failed ({e})")
        m.update(surge_status="unavailable", vel7=None, vel28=None, suspicious_stars=False,
                 history_source="star_history_svg")

    # 2. Ecosystem: artifacts created in the last 120 days, anchored (collision filter).
    since = (now - dt.timedelta(days=120)).date().isoformat()
    matched = {}
    try:
        _, readme_items = gh.search_repos(f'"{owner}/{name}" in:readme created:>{since}')
        for it in readme_items:
            if it["full_name"].lower() != full_name.lower():
                matched[it["full_name"]] = ("readme", it)
        if len(name) > 4:
            name_total, name_items = gh.search_repos(f"{name} in:name created:>{since}")
            hits = matched_name = 0
            for it in name_items:
                if it["full_name"].lower() == full_name.lower():
                    continue
                hits += 1
                art = {"full_name": it["full_name"], "description": it.get("description"),
                       "topics": it.get("topics")}
                a = anchor_for(owner, name, rest["topics"], art)
                if a:
                    matched_name += 1
                    matched.setdefault(it["full_name"], (a, it))
            m["name_collision_rate"] = name_collision_rate(hits, matched_name)
        m["artifacts_new_120d"] = len(matched)
        m["artifact_examples"] = sorted(matched)[:2]
        for fn, (anchor, it) in matched.items():
            con.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)",
                        (full_name, fn, it.get("created_at"), anchor, observed))
    except SourceError as e:
        errors.append(f"{full_name}: ecosystem search failed ({e})")
        m["artifacts_new_120d"] = None

    # 3. Confirmation: HN, URL-anchored, distinct independent domains in 90 days.
    m["domains_90d"], m["confirm_fresh"], m["top_recent_story"] = None, False, None
    if canary_ok:
        try:
            since_epoch = int((now - dt.timedelta(days=90)).timestamp())
            res = hn.stories_for_repo(owner, name, since_epoch, own_domain=_own_domain(rest["homepage"]))
            m["domains_90d"] = sorted(res["domains"])
            m["confirm_fresh"] = True
            for s in res["stories"]:
                con.execute("INSERT OR REPLACE INTO mentions VALUES(?,?,?,?,?,?,?,?,?,?)",
                            ("hn", s["item_id"], full_name, s["title"], s["url"],
                             s["domain"], s["author"], s["points"], s["created_at"], run_id))
            recent = [s for s in res["stories"] if s["created_at"] and
                      dt.datetime.fromisoformat(s["created_at"].replace("Z", "+00:00")) >=
                      now - dt.timedelta(days=14)]
            if recent:
                m["top_recent_story"] = max(recent, key=lambda s: s["points"])
        except SourceError as e:
            errors.append(f"{full_name}: HN search failed ({e})")
    else:
        errors.append(f"{full_name}: HN collector canary failed, confirmation stale")
    return m


def run_daily(cfg, con, run_id, dry_run, out_dir, token, now, clients=None):
    budget = Budget(cfg["budget"])
    if clients is None:
        http = Http(con, run_id)
        gh = GitHub(http, token, budget, cfg["budget"]["github_search_gap_seconds"])
        hn = HN(http, budget, cfg["budget"]["hn_gap_seconds"])
    else:  # injected clients (tests)
        gh, hn = clients
    errors, health = [], []

    for full in load_seeds():
        upsert_repo(con, full, "seed", now=now)
    repos = [r["full_name"] for r in con.execute(
        "SELECT full_name FROM repos WHERE status='watch' ORDER BY full_name")]

    # Canary: a normal day has >= 20 HN stories mentioning github.com.
    canary_ok, canary_value = False, None
    try:
        canary_value = hn.canary(now)
        canary_ok = canary_value >= 20
        log_source(con, run_id, "hn", canary_ok, n_requests=1, n_items=canary_value,
                   canary=canary_value)
        if not canary_ok:
            health.append(f"Health: Hacker News collector looks broken ({canary_value} stories "
                          "in 24h, expected 20+). Confirmation is stale, so nothing new is "
                          "called an inflection today.")
    except SourceError as e:
        errors.append(f"hn canary: {e}")
        log_source(con, run_id, "hn", False, error=str(e))
        health.append("Health: Hacker News collector failed. Confirmation is stale.")

    results = []
    for full in repos:
        try:
            m = measure_repo(full, gh, hn, con, run_id, now, cfg, canary_ok, errors)
        except SourceError as e:
            errors.append(f"{full}: {e}")
            continue
        if m is None:
            continue
        score, accel_ratio, comps, flags = components(m, cfg)
        cls, reason = classify(m, score, accel_ratio, cfg)
        if m.get("surge_status") and str(m["surge_status"]).startswith("unmeasurable"):
            flags.append(m["surge_status"])
        m["flags"] = flags
        m["class"] = cls
        results.append({"full_name": full, "class": cls, "score": score, "reason": reason,
                        "components": comps, "metrics": m, "accel_ratio": accel_ratio})
        con.execute("INSERT OR REPLACE INTO scores VALUES(?,?,?,?,?,?,?,?)",
                    (full, iso(now), run_id, score, cls, json.dumps(comps),
                     json.dumps(m, default=_default), json.dumps(flags)))
        if cls in CLASS_RANK:
            falsifier = render.falsifier(cls, now.date())
            con.execute("INSERT OR IGNORE INTO predictions(full_name, made_at, class, score, "
                        "metrics_json, falsifier) VALUES(?,?,?,?,?,?)",
                        (full, iso(now), cls, score, json.dumps(m, default=_default), falsifier))
    con.commit()

    # Alerts: one stage, one ledger keyed by repo, daily cap.
    cands = sorted((r for r in results if r["class"] in ALERT_CLASSES and
                    _ledger_allows(con, r["full_name"], r["class"], r["score"], now, cfg)),
                   key=lambda r: -r["score"])
    cap = cfg["alerts"]["daily_cap"]
    alerts, also = cands[:cap], cands[cap:]
    if not dry_run:
        for r in alerts:
            con.execute("""INSERT INTO alerts VALUES(?,?,?,?,?,1,?)
                ON CONFLICT(full_name) DO UPDATE SET last_alerted=excluded.last_alerted,
                  last_class=excluded.last_class, last_score=excluded.last_score,
                  times_alerted=alerts.times_alerted+1, last_run_id=excluded.last_run_id""",
                        (r["full_name"], iso(now), iso(now), r["class"], r["score"], run_id))
        con.commit()

    # Health only on a change of state, so one incident sends one message.
    prev = out_dir / "last_run.json"
    prev_canary = json.loads(prev.read_text()).get("canary_ok") if prev.exists() else None
    new_incident = (not canary_ok) and prev_canary is not False
    health_out = health if new_incident else []

    text = render.notify_text(alerts, health_out, dry_run, now.date(), also)
    (out_dir / "notify.txt").write_text(text)
    shortlist = sorted((_summary(r) for r in results if CLASS_RANK.get(r["class"], 0) >= 1),
                       key=lambda r: -r["score"])
    (out_dir / "shortlist.json").write_text(json.dumps(shortlist, indent=2))
    (out_dir / "last_run.json").write_text(json.dumps({
        "run_id": run_id, "finished_at": iso(now), "ok": True, "canary_ok": canary_ok,
        "canary_value": canary_value, "repos_measured": len(results),
        "alerts": [r["full_name"] for r in alerts], "budget_used": budget.used,
        "errors": errors,
    }, indent=2))
    return {"alerts": alerts, "results": results, "errors": errors}


def _summary(r):
    m = r["metrics"]
    return {"full_name": r["full_name"], "class": r["class"], "score": r["score"],
            "reason": r["reason"], "components": r["components"], "flags": m.get("flags", []),
            "surge_status": m.get("surge_status"), "stars": m.get("stars"),
            "ratio90": m.get("ratio90"), "share90": m.get("share90"),
            "artifacts_new_120d": m.get("artifacts_new_120d"),
            "domains_90d": m.get("domains_90d")}


def _default(o):
    if isinstance(o, dt.datetime):
        return iso(o)
    if isinstance(o, dt.date):
        return o.isoformat()
    raise TypeError(type(o))
