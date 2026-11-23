"""SQLite state. Only deterministic code writes here; the LLM never does."""
import datetime as dt
import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos(
  full_name TEXT PRIMARY KEY, owner TEXT, name TEXT, role TEXT,
  created_at TEXT, description TEXT, topics_json TEXT, homepage TEXT,
  language TEXT, status TEXT DEFAULT 'watch', first_seen TEXT);
CREATE TABLE IF NOT EXISTS snapshots(
  full_name TEXT, ts TEXT, stars INTEGER, forks INTEGER, open_issues INTEGER,
  pushed_at TEXT, archived INTEGER, PRIMARY KEY(full_name, ts));
CREATE TABLE IF NOT EXISTS star_daily(
  full_name TEXT, day TEXT, stars_added INTEGER, PRIMARY KEY(full_name, day));
CREATE TABLE IF NOT EXISTS surge(
  full_name TEXT, ts TEXT, surge_status TEXT, stars_last90 INTEGER, stars_prior90 INTEGER,
  share90 REAL, ratio90 REAL, covered_back_to TEXT, pages_walked INTEGER,
  pct_new_accounts REAL, pct_empty_accounts REAL, sample_size INTEGER,
  PRIMARY KEY(full_name, ts));
CREATE TABLE IF NOT EXISTS mentions(
  source TEXT, item_id TEXT, full_name TEXT, title TEXT, url TEXT, domain TEXT,
  author TEXT, points INTEGER, created_at TEXT, run_id TEXT,
  PRIMARY KEY(source, item_id, full_name));
CREATE TABLE IF NOT EXISTS artifacts(
  full_name TEXT, artifact TEXT, created_at TEXT, anchor TEXT, first_seen TEXT,
  PRIMARY KEY(full_name, artifact));
CREATE TABLE IF NOT EXISTS scores(
  full_name TEXT, ts TEXT, run_id TEXT, score REAL, class TEXT,
  components_json TEXT, metrics_json TEXT, flags_json TEXT,
  PRIMARY KEY(full_name, ts));
CREATE TABLE IF NOT EXISTS alerts(
  full_name TEXT PRIMARY KEY, first_alerted TEXT, last_alerted TEXT, last_class TEXT,
  last_score REAL, times_alerted INTEGER, last_run_id TEXT);
CREATE TABLE IF NOT EXISTS predictions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, full_name TEXT, made_at TEXT, class TEXT,
  score REAL, metrics_json TEXT, falsifier TEXT, horizon_days INTEGER DEFAULT 90,
  UNIQUE(full_name));
CREATE TABLE IF NOT EXISTS source_runs(
  run_id TEXT, source TEXT, finished TEXT, ok INTEGER, n_requests INTEGER,
  n_items INTEGER, canary_value INTEGER, error TEXT);
CREATE TABLE IF NOT EXISTS raw_fetches(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, url TEXT, status INTEGER,
  fetched_at TEXT, sha256 TEXT);
"""


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert_repo(con, full_name, role, created_at=None, description=None, topics=None,
                homepage=None, language=None, now=None):
    owner, name = full_name.split("/", 1)
    con.execute(
        """INSERT INTO repos(full_name, owner, name, role, created_at, description,
               topics_json, homepage, language, first_seen)
           VALUES(?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(full_name) DO UPDATE SET
             created_at=COALESCE(excluded.created_at, repos.created_at),
             description=COALESCE(excluded.description, repos.description),
             topics_json=COALESCE(excluded.topics_json, repos.topics_json),
             homepage=COALESCE(excluded.homepage, repos.homepage),
             language=COALESCE(excluded.language, repos.language)""",
        (full_name, owner, name, role, created_at, description,
         json.dumps(topics) if topics is not None else None, homepage, language, iso(now)))


def log_source(con, run_id, source, ok, n_requests=0, n_items=0, canary=None, error=None):
    con.execute(
        "INSERT INTO source_runs VALUES(?,?,?,?,?,?,?,?)",
        (run_id, source, iso(utcnow()), 1 if ok else 0, n_requests, n_items, canary, error))
    con.commit()


def last_ok(con, source):
    row = con.execute(
        "SELECT finished FROM source_runs WHERE source=? AND ok=1 ORDER BY finished DESC LIMIT 1",
        (source,)).fetchone()
    return row["finished"] if row else None
