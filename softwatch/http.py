"""HTTP with provenance. Every response is logged (url, status, sha256 of body) to raw_fetches."""
import hashlib
import time

import requests

from .db import iso, utcnow


class SourceError(RuntimeError):
    pass


class Http:
    def __init__(self, con, run_id, budget_key_map=None):
        self.con = con
        self.run_id = run_id
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "softwatch/2.0 (personal research feed)"
        self.last_call = {}

    def _pace(self, key, gap):
        if gap:
            wait = self.last_call.get(key, 0) + gap - time.monotonic()
            if wait > 0:
                time.sleep(wait)
        self.last_call[key] = time.monotonic()

    def request(self, method, url, *, params=None, json_body=None, headers=None,
                key="default", gap=0.0, timeout=(10, 30), attempts=3):
        """Returns the response, or raises SourceError. 403/429 are never retried."""
        last = None
        for attempt in range(attempts):
            self._pace(key, gap)
            try:
                r = self.s.request(method, url, params=params, json=json_body,
                                   headers=headers, timeout=timeout)
            except requests.RequestException as e:  # network or proxy failure
                last = str(e)
                time.sleep(2 ** attempt)
                continue
            digest = hashlib.sha256(r.content).hexdigest()
            self.con.execute("INSERT INTO raw_fetches(run_id,url,status,fetched_at,sha256) "
                             "VALUES(?,?,?,?,?)",
                             (self.run_id, url, r.status_code, iso(utcnow()), digest))
            if r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** attempt)
                continue
            return r
        raise SourceError(f"{url}: {last}")

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)
