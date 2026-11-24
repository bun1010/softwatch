"""Entry points: daily, digest-prep, review, probe.

Usage: python -m softwatch daily [--dry-run] [--run-id ID]
"""
import argparse
import json
import os
import sys
from pathlib import Path

from .config import load as load_config
from .db import connect, utcnow
from .pipeline import ROOT, run_daily

OUT = ROOT / "out"
DATA = ROOT / "data" / "softwatch.db"


def _run_id(arg):
    return arg or utcnow().strftime("%Y%m%dT%H%M")


def cmd_daily(args):
    cfg = load_config()
    OUT.mkdir(exist_ok=True)
    DATA.parent.mkdir(exist_ok=True)
    con = connect(DATA)
    run_id = _run_id(args.run_id)
    token = os.environ.get("SOFTWATCH_GH_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    try:
        res = run_daily(cfg, con, run_id, args.dry_run, OUT, token, utcnow())
    except Exception as e:  # the run failed: tell Jack once, through notify.txt
        (OUT / "notify.txt").write_text(f"Health: the Softwatch daily run failed ({e}). "
                                        "Last good run is in out/last_run.json.\n")
        (OUT / "last_run.json").write_text(json.dumps(
            {"run_id": run_id, "finished_at": None, "ok": False, "error": str(e)}, indent=2))
        raise
    print(f"measured {len(res['results'])} repos, alerts {len(res['alerts'])}, "
          f"errors {len(res['errors'])}")
    return 0


def cmd_digest_prep(args):
    con = connect(DATA)
    rows = con.execute("""
        SELECT s.full_name, s.class, s.score, s.metrics_json, s.flags_json, s.ts
        FROM scores s JOIN (SELECT full_name, MAX(ts) AS ts FROM scores GROUP BY full_name) l
          ON s.full_name = l.full_name AND s.ts = l.ts
        WHERE s.class NOT IN ('dormant', 'rejected', 'unscored')
        ORDER BY s.score DESC LIMIT 12""").fetchall()
    health = [dict(r) for r in con.execute(
        "SELECT source, MAX(finished) AS last_ok FROM source_runs WHERE ok=1 GROUP BY source")]
    items = []
    for r in rows:
        m = json.loads(r["metrics_json"])
        items.append({
            "repo": r["full_name"], "class": r["class"], "score": r["score"], "as_of": r["ts"],
            "stars": m.get("stars"), "share90": m.get("share90"), "ratio90": m.get("ratio90"),
            "surge_status": m.get("surge_status"),
            "artifacts_new_120d": m.get("artifacts_new_120d"),
            "domains_90d": m.get("domains_90d"), "flags": json.loads(r["flags_json"]),
        })
    (OUT / "digest_input.json").write_text(json.dumps(
        {"generated_at": utcnow().isoformat(), "rows": items, "source_health": health},
        indent=2))
    print(f"digest input: {len(items)} rows")
    return 0


def cmd_review(args):
    con = connect(DATA)
    counts = {r["class"]: r["n"] for r in con.execute(
        "SELECT class, COUNT(*) AS n FROM scores GROUP BY class")}
    preds = con.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    lines = [
        f"Softwatch monthly review ({utcnow().date().isoformat()})",
        "Classes in latest run: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items()))
                                     or "none"),
        f"Predictions logged: {preds}",
        "Precision: not measured yet. Shadow controls and outcome labels are not implemented.",
        "Outcomes at 90/180 days: not implemented in this version.",
    ]
    (OUT / "notify.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="softwatch")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("daily")
    d.add_argument("--dry-run", action="store_true")
    d.add_argument("--run-id")
    d.set_defaults(fn=cmd_daily)
    dp = sub.add_parser("digest-prep")
    dp.set_defaults(fn=cmd_digest_prep)
    rv = sub.add_parser("review")
    rv.set_defaults(fn=cmd_review)
    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
