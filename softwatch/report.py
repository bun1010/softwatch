"""Mini report for Telegram: a few tracked repos, each with a clickable link and a short description.

Built only from the database and the latest run. Numbers come from stored rows; nothing is invented.
Descriptions are the repo's own GitHub description, trimmed to one line.
"""
from .score import CLASS_RANK

MAX_ITEMS = 8
MAX_DESC = 150


def _trim(text):
    text = " ".join((text or "").split())
    if len(text) <= MAX_DESC:
        return text
    return text[: MAX_DESC - 1].rstrip() + "…"


def _latest(con, table, full_name):
    return con.execute(
        f"select * from {table} where full_name=? order by ts desc limit 1", (full_name,)
    ).fetchone()


def build(con, now_str, last_run=None):
    """Return the report text. Excludes repos the scorer rejected or marked dormant."""
    repos = con.execute(
        "select full_name, description, language from repos where status='watch'"
    ).fetchall()
    items = []
    for full_name, desc, lang in repos:
        score_row = _latest(con, "scores", full_name)
        snap = _latest(con, "snapshots", full_name)
        surge = _latest(con, "surge", full_name)
        cls = score_row[4] if score_row else "unscored"
        score = score_row[3] if score_row else None
        stars = snap[2] if snap else None
        status = surge[2] if surge else "unavailable"
        ratio = surge[6] if surge else None
        items.append({
            "full_name": full_name, "desc": desc, "lang": lang, "class": cls,
            "score": score, "stars": stars, "status": status, "ratio": ratio,
        })
    items.sort(key=lambda i: (-CLASS_RANK.get(i["class"], 0), -(i["score"] or 0)))
    lines = [f"Softwatch mini report, {now_str}", ""]
    if last_run:
        lines.append(
            f"Run {last_run.get('run_id')}: {last_run.get('repos_measured', '?')} repos measured, "
            f"{len(last_run.get('alerts') or [])} alerts."
        )
        lines.append("")
    for it in items[:MAX_ITEMS]:
        head = f"{it['full_name']} ({it['lang'] or 'language unknown'})"
        lines.append(head)
        lines.append(f"https://github.com/{it['full_name']}")
        lines.append(_trim(it["desc"]) or "No description on GitHub.")
        stat = f"Stars: {it['stars'] if it['stars'] is not None else 'unavailable'}"
        if it["status"] == "measured" and it["ratio"] is not None:
            stat += f"; last 90 days vs prior 90 days: {it['ratio']:.2f}x"
        else:
            stat += f"; surge test: {it['status']}"
        lines.append(stat + f"; class: {it['class']}")
        lines.append("")
    lines.append(f"Showing {min(len(items), MAX_ITEMS)} of {len(items)} tracked repos.")
    return "\n".join(lines).rstrip() + "\n"
