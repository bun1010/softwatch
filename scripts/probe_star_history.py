"""Diagnostic: save raw star-history SVG responses so the parser can be built from real data."""
import pathlib
import requests

OUT = pathlib.Path("data/probe")
OUT.mkdir(parents=True, exist_ok=True)
for repo in ["omacom/omarchy", "ollama/ollama", "chromium/chromium"]:
    url = "https://api.star-history.com/svg"
    r = requests.get(url, params={"repos": repo, "type": "Date"}, timeout=60,
                     headers={"User-Agent": "softwatch-probe"})
    name = repo.replace("/", "__") + ".svg"
    (OUT / name).write_bytes(r.content)
    print(repo, r.status_code, r.headers.get("content-type"), len(r.content), flush=True)
