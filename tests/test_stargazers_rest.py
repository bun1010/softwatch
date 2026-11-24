"""REST stargazer walk: pages from the last page backwards, with Link-header paging."""
import datetime as dt

from softwatch.config import load
from softwatch.sources.github import GitHub, _last_page

NOW = dt.datetime(2026, 11, 24, 12, tzinfo=dt.timezone.utc)
CREATED = NOW - dt.timedelta(days=900)


class Resp:
    def __init__(self, items, link=None, status=200):
        self.status_code = status
        self._items = items
        self.headers = {"Link": link} if link else {}

    def json(self):
        return self._items


class FakeHttp:
    """Serves a repo whose stargazers are `pages` (list of lists, ascending in time)."""
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, params=None, headers=None, key=None, gap=0):
        page = params["page"]
        self.calls.append(page)
        last = len(self.pages)
        link = f'<https://api.github.com/x?per_page=100&page={last}>; rel="last"' if last > 1 else None
        items = [{"starred_at": t.strftime("%Y-%m-%dT%H:%M:%SZ")} for t in self.pages[page - 1]]
        return Resp(items, link)


class Budget:
    def spend(self, key, n=1):
        pass


def _ts(days_ago):
    return NOW - dt.timedelta(days=days_ago)


def test_last_page_parsing():
    link = '<https://api.github.com/x?page=2>; rel="next", <https://api.github.com/x?page=17>; rel="last"'
    assert _last_page(link) == 17
    assert _last_page(None) is None


def test_walk_stops_once_cutoff_is_covered():
    # 4 pages, ascending. Page 4 is newest. Oldest star on page 2 is 200 days ago (> 180).
    pages = [
        [_ts(380), _ts(300)],          # page 1, oldest
        [_ts(250), _ts(200)],          # page 2
        [_ts(150), _ts(100)],          # page 3
        [_ts(50), _ts(1)],             # page 4, newest
    ]
    gh = GitHub(None, "", Budget(), 0)
    gh.http = FakeHttp(pages)
    walk = gh.stargazers_rest("o", "r", _ts(180), 60, CREATED)
    assert walk["covered_back_to"] == _ts(250)  # page 2 holds the oldest star that covers the cutoff
    assert walk["total"] == 3 * 100 + 2
    assert gh.http.calls == [1, 4, 3, 2]  # page 1 only to read the Link header; cutoff covered at page 2


def test_walk_truncated_at_page_cap():
    pages = [[_ts(5)] for _ in range(10)]
    gh = GitHub(None, "", Budget(), 0)
    gh.http = FakeHttp(pages)
    walk = gh.stargazers_rest("o", "r", _ts(180), 3, CREATED)
    assert walk["covered_back_to"] is None  # truncated: guard will mark it unmeasurable


def test_full_first_page_without_link_header_is_an_error():
    import pytest
    from softwatch.http import SourceError

    class NoLink(FakeHttp):
        def get(self, url, params=None, headers=None, key=None, gap=0):
            items = [{"starred_at": _ts(1).strftime("%Y-%m-%dT%H:%M:%SZ")}] * 100
            return Resp(items, None)

    gh = GitHub(None, "", Budget(), 0)
    gh.http = NoLink([])
    with pytest.raises(SourceError):
        gh.stargazers_rest("o", "r", _ts(180), 60, CREATED)


def test_empty_stargazer_list_is_an_error_not_zero():
    import pytest
    from softwatch.http import SourceError

    class Empty(FakeHttp):
        def get(self, url, params=None, headers=None, key=None, gap=0):
            return Resp([], None)

    gh = GitHub(None, "", Budget(), 0)
    gh.http = Empty([])
    with pytest.raises(SourceError):
        gh.stargazers_rest("o", "r", _ts(180), 60, CREATED)
