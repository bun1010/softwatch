"""Hacker News via Algolia. Confirmation counts distinct independent domains, not posts."""
import datetime as dt
from urllib.parse import urlparse

from ..http import SourceError

API = "https://hn.algolia.com/api/v1"
EXCLUDED_DOMAINS = {"github.com", "news.ycombinator.com", "gist.github.com"}


def _domain(url):
    if not url:
        return None
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


class HN:
    def __init__(self, http, budget, gap):
        self.http = http
        self.budget = budget
        self.gap = gap

    def _search(self, params):
        self.budget.spend("hn")
        r = self.http.get(f"{API}/search_by_date", params={"tags": "story", **params},
                          key="hn", gap=self.gap)
        if r.status_code != 200:
            raise SourceError(f"hn: HTTP {r.status_code}")
        return r.json()

    def canary(self, now):
        """Does the collector see a normal day? Fewer than 20 stories means it is broken."""
        since = int((now - dt.timedelta(hours=24)).timestamp())
        j = self._search({"query": "github.com", "numericFilters": f"created_at_i>{since}",
                          "hitsPerPage": 20})
        return j.get("nbHits", 0)

    def stories_for_repo(self, owner, name, since_epoch, own_domain=None):
        """URL-anchored story search for the repo, deduplicated and domain-counted.

        Returns dict: stories (list), domains (set of distinct independent domains),
        repost_campaign (bool).
        """
        j = self._search({
            "query": f"github.com/{owner}/{name}",
            "restrictSearchableAttributes": "url",
            "numericFilters": f"created_at_i>{since_epoch}",
            "hitsPerPage": 100,
        })
        seen, stories = set(), []
        for h in j.get("hits", []):
            key = (h.get("title"), h.get("author"))
            if key in seen:
                continue  # one submitter reposting the same title counts once
            seen.add(key)
            stories.append({
                "item_id": h["objectID"], "title": h.get("title"), "url": h.get("url"),
                "domain": _domain(h.get("url")), "author": h.get("author"),
                "points": h.get("points") or 0, "created_at": h.get("created_at"),
            })
        authors = [s["author"] for s in stories]
        repost = False
        if authors:
            top = max(set(authors), key=authors.count)
            share = authors.count(top) / len(authors)
            max_points = max(s["points"] for s in stories)
            repost = share > 0.5 and max_points < 30 and len(authors) >= 2
        domains = set()
        if not repost:
            for s in stories:
                d = s["domain"]
                if d and d not in EXCLUDED_DOMAINS and d != own_domain:
                    domains.add(d)
        return {"stories": stories, "domains": domains, "repost_campaign": repost}
