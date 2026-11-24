"""Push alerts to Telegram. Runs from the GitHub Actions job, so no Claude thread is needed.

Needs two repository secrets: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID. If either is missing,
nothing is sent and the reason is returned (the run itself still succeeds).
Plain text is sent, so Telegram turns the URLs into tappable links.
"""
import requests

API = "https://api.telegram.org"
LIMIT = 4000  # Telegram allows 4096 characters per message


def chunks(text, limit=LIMIT):
    """Split on line boundaries so no message exceeds the limit."""
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:  # a single over-long line: hard split
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) > limit:
            out.append(cur)
            cur = ""
        cur += line
    if cur:
        out.append(cur)
    return out


def send(text, token, chat_id, post=requests.post):
    """Returns 'sent', or 'skipped: ...' / 'failed: ...'. Never raises."""
    if not text.strip():
        return "skipped: nothing to send"
    if not token or not chat_id:
        return "skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set"
    try:
        for part in chunks(text):
            r = post(f"{API}/bot{token}/sendMessage",
                     data={"chat_id": chat_id, "text": part,
                           "disable_web_page_preview": "false"},
                     timeout=30)
            if r.status_code != 200:
                # Do not echo the token: the URL contains it.
                return f"failed: Telegram HTTP {r.status_code}"
        return "sent"
    except requests.RequestException as e:
        return f"failed: {type(e).__name__}"
