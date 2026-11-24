"""End-to-end wiring test with synthetic clients. No network: every number is fixture data."""
import datetime as dt
import json

from softwatch.config import load
from softwatch.db import connect
from softwatch.pipeline import run_daily

NOW = dt.datetime(2026, 11, 23, 12, tzinfo=dt.timezone.utc)


def ago(d):
    return NOW - dt.timedelta(days=d)


class FakeGH:
    def __init__(self, repos):
        self.repos = repos

    def repo(self, full):
        return self.repos.get(full)

    def stargazers(self, owner, name, cutoff, cap):
        r = self.repos[f"{owner}/{name}"]
        return {"total": r["stars"], "created_at": r["created_at"],
                "starred": r["starred"], "covered_back_to": r["covered"], "pages": 3}

    def search_repos(self, q, per_page=100):
        if "in:readme" in q:
            items = [{"full_name": f"dev{i}/omarchy-port{i}", "description": "port of omacom/omarchy",
                      "topics": []} for i in range(3)]
            return 3, items
        return 0, []


class FakeHN:
    def canary(self, now):
        return 57

    def stories_for_repo(self, owner, name, since, own_domain=None):
        if name != "omarchy":
            return {"stories": [], "domains": set(), "repost_campaign": False}
        st = [{"item_id": "1", "title": "Omarchy on NixOS", "url": "https://lwn.net/x",
               "domain": "lwn.net", "author": "a", "points": 120,
               "created_at": ago(5).strftime("%Y-%m-%dT%H:%M:%SZ")},
              {"item_id": "2", "title": "Omarchy review", "url": "https://theregister.com/y",
               "domain": "theregister.com", "author": "b", "points": 40,
               "created_at": ago(9).strftime("%Y-%m-%dT%H:%M:%SZ")}]
        return {"stories": st, "domains": {"lwn.net", "theregister.com"}, "repost_campaign": False}


def repo_fixture():
    # 'omarchy': 300 stars in last 90d, 100 in prior 90d, full coverage back to 180d.
    # 1,200 stars: 50 in the last 7 days, 750 in days 8-90, 300 in days 91-180, 100 older.
    starred = ([(ago(1), ago(900), 5, 3)] * 50 + [(ago(60), ago(900), 5, 3)] * 750
               + [(ago(120), ago(900), 5, 3)] * 300 + [(ago(400), ago(900), 5, 3)] * 100)
    return {
        "omacom/omarchy": {"stars": 1200, "forks": 40, "open_issues": 20, "created_at": ago(500),
                           "pushed_at": None, "topics": ["linux", "nix", "dotfiles"],
                           "description": "Opinionated Arch setup", "homepage": "https://omarchy.org",
                           "language": "Shell", "archived": False, "fork": False, "name": "omarchy",
                           "owner": "omacom", "starred": starred, "covered": ago(400)},
        "chromium/chromium": {"stars": 150000, "forks": 1, "open_issues": 1, "created_at": ago(3200),
                              "pushed_at": None, "topics": [], "description": "browser",
                              "homepage": None, "language": "C++", "archived": False, "fork": False,
                              "name": "chromium", "owner": "chromium", "starred": [(ago(1), None, None, None)],
                              "covered": None},
    }


def test_daily_pipeline_wiring(tmp_path, monkeypatch):
    import softwatch.pipeline as pl
    monkeypatch.setattr(pl, "load_seeds", lambda: ["omacom/omarchy", "chromium/chromium"])
    # Rewrite fixture starred tuples to the 4-tuple shape the real client returns.
    repos = repo_fixture()
    for r in repos.values():
        r["starred"] = [(t, uc, f, rp) for t, uc, f, rp in r["starred"]]
    con = connect(tmp_path / "t.db")
    out = tmp_path / "out"
    out.mkdir()
    cfg = load()
    res = run_daily(cfg, con, "test-run", True, out, "", NOW,
                    clients=(FakeGH(repos), FakeHN()))
    by = {r["full_name"]: r for r in res["results"]}

    omarchy = by["omacom/omarchy"]
    assert omarchy["metrics"]["surge_status"] == "measured"
    assert omarchy["metrics"]["ratio90"] == __import__("pytest").approx(800 / 300)
    assert omarchy["metrics"]["domains_90d"] == ["lwn.net", "theregister.com"]
    assert omarchy["metrics"]["artifacts_new_120d"] == 3
    assert omarchy["class"] == "resurgent", omarchy["reason"]

    chromium = by["chromium/chromium"]
    assert chromium["metrics"]["surge_status"] == "unmeasurable_truncated"
    assert chromium["class"] == "rejected"  # 3,200 days old, no measured surge

    # dry run: the alert is previewed, labelled, and not written to the ledger
    notify = (out / "notify.txt").read_text()
    assert notify.startswith("[DRY RUN")
    assert "omacom/omarchy (resurgent" in notify
    assert "falsifier:" in notify and "<https://github.com/omacom/omarchy>" in notify
    assert con.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0
    last = json.loads((out / "last_run.json").read_text())
    assert last["canary_ok"] is True and last["ok"] is True
