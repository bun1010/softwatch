"""GitHub REST, GraphQL and search. Authenticated with GITHUB_TOKEN (Actions) or SOFTWATCH_GH_TOKEN."""
import datetime as dt

from ..http import SourceError

API = "https://api.github.com"

STARGAZER_QUERY = """
query($o:String!, $n:String!, $before:String) {
  repository(owner:$o, name:$n) {
    stargazerCount
    createdAt
    stargazers(last:100, before:$before, orderBy:{field:STARRED_AT, direction:ASC}) {
      pageInfo { hasPreviousPage startCursor }
      edges { starredAt node { createdAt followers { totalCount } repositories { totalCount } } }
    }
  }
}
"""


def _parse_time(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


class GitHub:
    def __init__(self, http, token, budget, search_gap):
        self.http = http
        self.budget = budget
        self.search_gap = search_gap
        self.headers = {"Accept": "application/vnd.github+json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def repo(self, full_name):
        """REST repo metadata, or None if the repo does not exist."""
        self.budget.spend("github_rest")
        r = self.http.get(f"{API}/repos/{full_name}", headers=self.headers, key="github_rest")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise SourceError(f"repo {full_name}: HTTP {r.status_code}")
        j = r.json()
        return {
            "stars": j["stargazers_count"], "forks": j["forks_count"],
            "open_issues": j["open_issues_count"], "created_at": _parse_time(j["created_at"]),
            "pushed_at": j.get("pushed_at"), "topics": j.get("topics") or [],
            "description": j.get("description"), "homepage": j.get("homepage"),
            "language": j.get("language"), "archived": bool(j.get("archived")),
            "fork": bool(j.get("fork")), "name": j["name"], "owner": j["owner"]["login"],
        }

    def stargazers(self, owner, name, cutoff, page_cap):
        """Walk stargazers newest-first until `cutoff` or the page cap.

        Returns dict: total, created_at, starred (list of (starredAt, userCreatedAt, followers,
        repos) tuples, newest page first), covered_back_to (datetime, or None if truncated), pages.
        """
        starred, before, pages, covered, total, created = [], None, 0, None, None, None
        while True:
            self.budget.spend("github_graphql")
            r = self.http.post(f"{API}/graphql", json_body={
                "query": STARGAZER_QUERY,
                "variables": {"o": owner, "n": name, "before": before},
            }, headers=self.headers, key="github_graphql")
            if r.status_code != 200:
                raise SourceError(f"graphql {owner}/{name}: HTTP {r.status_code}")
            body = r.json()
            if body.get("errors"):
                raise SourceError(f"graphql {owner}/{name}: {body['errors'][0].get('message')}")
            repo = body["data"]["repository"]
            total, created = repo["stargazerCount"], _parse_time(repo["createdAt"])
            sg = repo["stargazers"]
            pages += 1
            for e in sg["edges"]:
                node = e["node"] or {}
                starred.append((
                    _parse_time(e["starredAt"]),
                    _parse_time(node["createdAt"]) if node.get("createdAt") else None,
                    (node.get("followers") or {}).get("totalCount"),
                    (node.get("repositories") or {}).get("totalCount"),
                ))
            if not sg["edges"]:
                covered = created
                break
            oldest = min(t for t, _, _ in starred)
            if not sg["pageInfo"]["hasPreviousPage"]:
                covered = created
                break
            if oldest <= cutoff:
                covered = oldest
                break
            if pages >= page_cap:
                covered = None  # truncated: cannot prove the prior window is observed
                break
            before = sg["pageInfo"]["startCursor"]
        return {"total": total, "created_at": created, "starred": starred,
                "covered_back_to": covered, "pages": pages}

    def search_repos(self, q, per_page=100):
        """Returns (total_count, items). Search is rate limited, so it is paced."""
        self.budget.spend("github_rest")
        r = self.http.get(f"{API}/search/repositories",
                          params={"q": q, "per_page": per_page},
                          headers=self.headers, key="github_search", gap=self.search_gap)
        if r.status_code != 200:
            raise SourceError(f"search '{q}': HTTP {r.status_code}")
        j = r.json()
        return j["total_count"], j["items"]
