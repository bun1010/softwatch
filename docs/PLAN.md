# Softwatch Cloud — Implementation Plan (v1, revision 2)

> **Revision 2 (2026-11-23 22:50 UTC):** no GitHub account needed. Testing showed this cloud environment only allows GitHub API calls for repositories attached to the session, connected account or not, so the GitHub REST/GraphQL/search API cannot be used to track hundreds of arbitrary repos. GitHub data now comes from **GH Archive** (every public GitHub event, hourly files), the **OSS Insight GitHub passthrough**, **star-history** charts for backfill, and **raw.githubusercontent.com** for READMEs. Sections 1, 4.1, 4.2, 4.5, 4.6, 6.1, 15 and 16 are updated; §4.0 is new. Phone alerts confirmed as Claude app thread notifications (§2).

> **Revision 3 (2026-11-23 23:05 UTC) — READ THIS FIRST. It overrides §1, §3.2, §4 and §9 where they conflict.**
> Jack cannot change the cloud environment's network allowlist, so the Claude cloud session cannot reach most data sources (§1). Claude's WebFetch tool reaches some (tested: HN Algolia, OSS Insight passthrough, GitHub search API, github.com/trending, data.gharchive.org all OK; api.github.com/repos, api.star-history.com, lobste.rs, repology.org, api.deps.dev all failed). But WebFetch can't be called from code and passes through a summarizer, so it breaks rule 2. **Chosen runtime (Jack picked option A, 2026-11-23): GitHub Actions does all collection and scoring; the Claude scheduled task only reads the results and posts them.**
>
> **R3.1 Split of responsibilities**
> - **Repo:** one GitHub repo owned by Jack (public is fine and gives unlimited Actions minutes; private gets 2,000 free min/month, enough for about 15 min/day). It holds the code, `config.toml`, `data/softwatch.db` (committed; it's small if `raw_fetches.body_gz` is pruned after 30 days, see §14) and `out/`.
> - **GitHub Actions** (`.github/workflows/daily.yml`, `weekly.yml`, `monthly.yml`): `ubuntu-latest`, Python 3.12, `pip install requests`, run `python -m softwatch daily|digest-prep|review`, then commit `data/` and `out/` back to `main` with message `softwatch run <run_id>` (use `stefanzweifel/git-auto-commit-action` or plain git). `concurrency: softwatch` prevents overlap (replaces the lock file in §3.2; no DB copy-in/out needed, Actions has local disk). Cron in UTC: daily `17 6 * * *`, Monday digest prep `47 7 * * 1`, monthly `52 8 9 * *`. Also `workflow_dispatch` for manual runs.
> - **Network in Actions is unrestricted**, so use the **revision-1 sources**: GitHub REST + GraphQL stargazers with exact `starredAt` timestamps (§4.1-old, §4.2-old: implement these, they are no longer "old"), GitHub search for ecosystem (§4.5 original bullets), HN Algolia, Lobsters, dev.to, Bluesky, deps.dev, Repology, registries. GH Archive (§4.0) becomes an optional add-on for discovery (star leaders and new-repo feed); implement it last, behind `config.toml [gharchive] enabled=false`.
> - **Token:** Actions' built-in `GITHUB_TOKEN` (1,000 REST req/hr, GraphQL works) is enough for v1. If budgets bind, Jack can add a fine-grained personal access token with *public repositories read-only* as secret `SOFTWATCH_GH_TOKEN` (5,000/hr); code prefers it when present.
> - **Claude scheduled tasks** (bound to the Softwatch thread session, Europe/London): daily `43 7 * * *` (≈ 1 h after the Action), digest Monday `14 9 * * 1`, review `22 10 9 * *`. Each run: `git pull` the attached repo (Jack connects GitHub to Claude and the repo is attached with `add_repo`; attached repos are reachable from this environment), check `out/last_run.json` (run_id, finished_at, ok). If the Action hasn't produced today's run, post one Health line ("Softwatch: today's collection didn't run, last good run <time>") once per incident. Otherwise post `out/notify.txt` verbatim, or end silently if it is empty. Digest: the session writes the narrative from `out/digest_input.json` only.
> - **Failure alerting from Actions itself:** a failed workflow writes `out/last_run.json` with `ok=false` and the error if it gets far enough to commit; GitHub also emails Jack on workflow failure by default.
> - **Not needed under R3:** the allowlist prerequisite (P2), OSS Insight, star-history SVG parsing. Keep star-history only as a backfill fallback for repos above the GraphQL page cap.
>
> **R3.2 If Jack picks option B (Claude-only via WebFetch)** the plan must be cut down; do not implement until the planning thread rewrites it. **Option C (his computer via Remote Control)** uses revision 1 as-is with `run.sh` on his machine.
>
> **R3.3 Prerequisites under R3:** create a GitHub account and an empty repo `softwatch`; connect GitHub to Claude (https://claude.ai/connect-github); tell the planning thread the repo name so it can be attached. Turn on Claude app notifications for the Softwatch thread.

Status: **planning complete (option A chosen). Ready for Haiku once the GitHub repo exists and is connected (R3.3).**
Author: Claude (planning thread "Build cloud Softwatch with phone alerts"), 2026-11-23.
Audience: the implementing model. Follow this document literally. Where it says "decide", pick the simplest option and note it in `NOTES.md`.

The Pi handover pack (Hermes, Oct–Nov 2026) is design input. This plan keeps its core rules and fixes its known defects. Everything below is self-contained; you do not need the handover pack to implement it, but the original is attached to the project thread if you want the reference values.

---

## 0. Non-negotiable rules (carried over from the Pi system)

1. **Rank by switching, not attention.** The dominant signal is *new* third-party artifacts (ports, plugins, integrations, packaging) created in the last 120 days.
2. **Never invent a number.** Every number in the DB, in an alert, or in a digest comes from an HTTP response stored in `raw_fetches` or from arithmetic over stored values. If a value is missing, store `NULL` and render `unavailable`. No defaults, no interpolation, no "estimated".
3. **Measurement guard.** A surge figure (share90 / ratio90) is only valid if both the last-90-day and prior-90-day windows are actually observed. Otherwise the repo is `unmeasurable` for surge purposes and may not receive `resurgent` or `climber`. Never relax this.
4. **External confirmation required for `inflection`.** At least one distinct independent domain (not github.com, not news.ycombinator.com, not the project's own domain) inside 90 days.
5. **Deterministic code does all collection, arithmetic, state writes and verdicts.** The LLM only (a) runs the commands, (b) posts the text the code produced, (c) writes the weekly narrative from `out/digest_input.json`. The LLM never writes to the DB and cannot change a verdict.
6. **Every alert carries a falsifier** (generated by code from templates, see §8).
7. **Downloads corroborate, never trigger. Issue/star > 10% is adoption, not ill health. Mention counts are deduplicated by distinct domain.**

---

## 1. Environment facts (verified 2026-11-23 from this cloud environment)

| Thing | Status | Consequence |
|---|---|---|
| Python | 3.13 available | Use stdlib + `requests` only (plus `pytest` for tests). No heavy deps. |
| api.github.com / github.com | **Not usable for arbitrary repos.** The environment only permits GitHub API calls for repos attached to the session (tested: `api.github.com/repos/omacom/omarchy` → "GitHub access to this repository is not enabled for this session"; search → 403). Connecting a GitHub account does not change this. | Do **not** use the GitHub API. Use §4.0 sources. |
| raw.githubusercontent.com | **Reachable** (tested, 206) | READMEs and manifest files of any public repo: used for anchor checks (§5) and package mapping. |
| data.gharchive.org | Blocked by network policy | Allowlist (P2). Primary GitHub data source. |
| hn.algolia.com, lobste.rs, api.star-history.com, ossinsight, huggingface, npm, repology, deps.dev, bsky, ntfy.sh | **Blocked by the environment network policy** | Prerequisite P2: allowlist hosts (§1.1). |
| pypi.org | Reachable | |
| gcloud / bq | Installed, not authenticated | GH Archive via BigQuery is a *future* option (§12), not v1. |
| Container disk | Ephemeral; wiped between sessions | All durable state lives in `/mnt/project-files/softwatch/` (persists across threads and runs). |
| GitHub repo for the code | None attached | v1 keeps code in `/mnt/project-files/softwatch/`. If Jack later creates a repo, move code there; DB stays in project files. |

### 1.1 Hosts to allowlist (P2)

Required: `data.gharchive.org`, `api.ossinsight.io`, `api.star-history.com`, `hn.algolia.com`, `lobste.rs`, `api.deps.dev`, `repology.org`. (`raw.githubusercontent.com` already works.)
Recommended: `pypistats.org`, `api.npmjs.org`, `crates.io`, `formulae.brew.sh`, `dev.to`, `public.api.bsky.app`, `huggingface.co`.
Not needed: `api.github.com` / `github.com` (unusable here, see above).

**Phase 0 of implementation is a connectivity probe** (`softwatch probe`) that hits each host once and writes `out/probe.json`. Every source module must degrade gracefully when its host is unreachable: it records a failed `source_runs` row, and downstream code treats the value as missing (not zero).

---

## 2. Notifications — how alerts reach Jack's Android phone

**Finding:** no ntfy-style topic exists in project memory or elsewhere. Jack's two other recent projects ("Daily photo theme", "Braun IPL price watch") use **scheduled tasks bound to a project thread session, which post into the thread with `post_message`; the Claude Android app delivers that as a push notification.** ntfy.sh is also blocked by the network policy. So v1 uses the same mechanism:

- Scheduled tasks fire into **this project thread's session** (the Softwatch thread).
- The run executes the Python pipeline, which writes `out/notify.txt` (exact text, already formatted).
- The session posts `out/notify.txt` verbatim with `post_message`. If the file is empty, the session ends the turn with `no_reply_needed` (no push, no noise).

**Confirmed by Jack (2026-11-23):** alerts arrive through the Claude app's notifications for the thread; the scheduled task does not push by itself. So notifications must be switched on in the Claude app for the Softwatch thread. No ntfy. Keep delivery behind a small adapter (`notify/thread.py` just writes `out/notify.txt`) so another channel could be added later.

### 2.1 Notification types and budget

| Type | When | Max frequency | Content |
|---|---|---|---|
| **Alert** | A repo newly reaches `inflection`, `resurgent` or `climber`, or upgrades class (see §7 ledger) | ≤ 3 alerts per day, combined into one message | Per repo: class, score, the 3 strongest measured facts, why-now, falsifier, link |
| **Weekly digest** | Monday | 1/week | ≤ 12 rows, LLM narrative over `digest_input.json`, source health line, "outcomes this week" from the prediction ledger |
| **Health** | A source has failed or returned a broken canary for > 48h, or the daily run itself failed | 1 per incident (re-notify only after recovery + new failure) | Which source, since when, which verdicts are affected |
| **Monthly review** | 9th of month | 1/month | Backtest/precision update, threshold drift, control-set size |

Message formatting: plain text + simple Markdown, first line is the headline (it's what shows in the phone notification), e.g. `Softwatch: 2 new — foo/bar (inflection 81), baz/qux (resurgent 67)`. Wrap URLs in `<...>`.

---

## 3. Architecture

One pipeline, stages ordered by irreplaceability (Pi defect D6.10: a stage placed last got starved).

```
daily (06:4x London)                    weekly (Mon 08:1x)       monthly (9th 09:2x)
probe → discover → measure → ecosystem → confirm → score → alert   digest            review/backtest
         (cheap)   (stars,    (switching) (mentions)  (pure    (ledger,  (LLM narrative)   (deterministic +
                    surge,                            arithmetic)  notify.txt)                 short LLM summary)
                    shape)
```

- Each stage is a Python module with a `run(ctx)` function, callable alone (`python -m softwatch <stage>`) and via `python -m softwatch daily`.
- A shared **request budget** object (per host, per run) is passed to every stage. The surge measurement (`measure`) gets its budget reserved *first*; discovery gets the remainder. Never let a later stage starve an earlier, more important one.
- Every stage writes a `source_runs` row: `(run_id, source, started, finished, ok, n_requests, n_items, error)`.
- Failure isolation: a stage exception is caught, logged, recorded; later stages run on the latest available data, and the freshness of each input is carried into the scores (§6.6).

### 3.1 File layout (all under `/mnt/project-files/softwatch/`)

```
softwatch/
  PLAN.md               (this file)
  NOTES.md              (implementer's decisions + deviations)
  config.toml           (thresholds, weights, budgets, schedule labels; §13)
  run.sh                (entrypoint used by scheduled tasks; §9)
  softwatch/            (python package)
    __main__.py  cli.py  config.py  db.py  http.py  budget.py  util_text.py
    sources/  github_rest.py  github_graphql.py  hn.py  lobsters.py  devto.py  bsky.py
              depsdev.py  repology.py  registries.py  trending.py
    stages/   probe.py discover.py measure.py ecosystem.py confirm.py score.py alert.py
              digest.py review.py backtest.py outcomes.py
    render/   alert_text.py  digest_input.py  falsifiers.py
  tests/                (pytest; fixtures are saved JSON responses, no network)
  data/softwatch.db     (canonical DB)
  data/backups/         (daily copies, keep 14)
  out/                  (probe.json, shortlist.json, notify.txt, digest_input.json, run.log)
  seeds/test_set.toml   (acceptance test repos, §11)
```

### 3.2 SQLite on a network mount

`/mnt/project-files` is a network mount; do not run SQLite directly on it.
`run.sh` copies `data/softwatch.db` → `/tmp/softwatch/softwatch.db`, runs the pipeline there, runs `PRAGMA integrity_check`, then copies back to `data/softwatch.db.tmp` and `mv` into place; also copies to `data/backups/softwatch-YYYYMMDD.db` and prunes to 14. A lock file `data/RUNNING` (with run_id and start time) prevents overlapping runs; a lock older than 3h is considered stale and is removed with a log line.

---

## 4. Data sources and what each one measures

All HTTP goes through `http.py`: `requests.Session`, CA bundle from env, timeout 15s connect / 30s read, 2 retries with backoff on 5xx/timeouts, never retry 403/407 (policy). Every response's URL, status, timestamp and a SHA-256 of the body are written to `raw_fetches`; bodies themselves are written to `raw_fetches.body` only for responses < 200 KB, gzip-compressed. This is the provenance chain for rule 2.

### 4.0 GitHub data without the GitHub API (revision 2)

**GH Archive (`https://data.gharchive.org/YYYY-MM-DD-H.json.gz`, one file per UTC hour, no key, no quota)** is the primary source. Every public GitHub event is in it. The daily run downloads the previous UTC day's 24 files (parallel, 4 at a time, streamed through `gzip` line by line, never stored on disk) and keeps only:
- `WatchEvent` → exact stars per repo per day (`star_daily`), for **every** public repo, not just tracked ones.
- `ForkEvent` → forks per day. `IssuesEvent` (action=opened) → new issues per day. `ReleaseEvent` → releases (tag, date).
- `CreateEvent` with `ref_type=repository` → every new public repo that day (name, owner, description when present): the raw feed for ecosystem detection (§4.5) and discovery (§4.6).
- `PublicEvent` (repo made public) → treat like creation.
Speed: prefilter each line with a substring test (`"type":"WatchEvent"` etc.) before `json.loads`. Aggregate in memory into dicts and write to SQLite once per file. Store `gharchive_hours(hour, ok, n_events, bytes)` so missing hours are known; a day with < 24 ok hours marks those days `incomplete` in `star_daily_coverage`.
**Phase 0 spike:** time one hour file end to end and record size/time in NOTES.md. If a full day takes more than 40 min in one session, split into two scheduled runs (hours 0–11 and 12–23) or reduce to the event types above with a faster parser (e.g. `orjson` if installable). Record the decision.

**Star history before GH Archive coverage begins.** GH Archive gives exact daily stars only from the day collection starts (unless historical hours are backfilled). Two backfill tools:
1. **star-history SVG** (`api.star-history.com/svg?repos=o/r&type=Date`): parse path anchors and calibrate y against gridline labels (as on the Pi). Anchors are sparse (~26 days), so apply the Pi measurement guard: require ≥3 anchors in the last 90d and ≥1 in the prior 90d, else `unmeasurable`.
2. **Do not backfill GH Archive.** 180 days is ~4,300 hour files, too large, and sampling some hours would bias the counts. Use star-history until 180 days of GH Archive data exist, then switch the surge test to GH Archive automatically (per-repo `history_source` column: `star_history_svg` or `gharchive`). Show the source in every alert line.
After 180 days of collection (≈ late May 2027), the surge test runs on exact daily data for all repos and the guard becomes: both 90-day windows have 0 `incomplete` days (allow ≤3).

**OSS Insight passthrough (`https://api.ossinsight.io/gh/repos/{o}/{r}`, no quota):** current stars, forks, open issues, created_at, pushed_at, topics, homepage, description, language, archived, fork. Payload is nested under `{"data": {...}}` (Pi quirk D5: check `data.stargazers_count`, not top level). It stalls about 1 in 3 requests and always on the first per process: timeout 8s, no waiting, retry in a later pass of the same run (max 3 passes). **Phase 0 spike:** test whether the passthrough also serves `/gh/repos/{o}/{r}/releases` and `/gh/search/repositories?q=`; if search works, use it for ecosystem queries (budget 10/min to be safe) and record that in NOTES.md.

**raw.githubusercontent.com:** README (`/{o}/{r}/HEAD/README.md`, try `readme.md`, `README.rst`, `README`) and manifests (`package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `flake.nix`) for anchor checks and package→repo mapping. Budget 500 requests per run; cache by repo + pushed_at.

### 4.1 Repo metadata (was: GitHub REST — replaced)
Current stars/forks/issues/topics come from OSS Insight (§4.0). Releases come from GH Archive `ReleaseEvent` (complete from collection start) plus OSS Insight releases if the spike shows it works. Open PR count is not available: report issue/star using `open_issues_count` (which includes PRs on GitHub) and label it `issues+PRs` in output. Original v1 text below is kept for reference only; do not implement GitHub REST calls.

### 4.1-old GitHub REST (not used in revision 2)
- `GET /repos/{o}/{r}` → stars, forks, open_issues (subtract open PRs via `GET /search/issues?q=repo:{o}/{r}+is:pr+is:open` only for repos on the shortlist), created_at, pushed_at, topics, homepage, license, archived, fork, description.
- `GET /repos/{o}/{r}/releases?per_page=100` → release dates (cadence), asset download counts (corroboration only).
- Search API (30 req/min authenticated): discovery and ecosystem queries. Budget it at 25/min.

### 4.2-old GitHub GraphQL stargazers (NOT USED in revision 2: needs the GitHub API). Star-quality sampling (fake-star detection) is dropped for now; GH Archive `WatchEvent` includes `actor.login` only, so instead compute `pct_repeat_stargazers`: share of a repo's stargazers in the last 30 days who also starred ≥ 50 other repos the same day (star-farm behaviour), from GH Archive actor data.
Exact per-star timestamps, newest first:
```graphql
query($o:String!,$r:String!,$cursor:String){ repository(owner:$o,name:$r){
  stargazerCount
  stargazers(last:100, before:$cursor, orderBy:{field:STARRED_AT,direction:ASC}){
    pageInfo{ hasPreviousPage startCursor } edges{ starredAt node{ createdAt followers{totalCount} repositories{totalCount} } } } } }
```
Walk backward page by page until the oldest `starredAt` on a page is older than **now − 180 days**, or the per-repo page cap is reached (default 120 pages = 12,000 stars).
- `stars_last90` = count with starredAt ≥ now−90d; `stars_prior90` = count in [now−180d, now−90d).
- `share90 = stars_last90 / stargazerCount`; `ratio90 = stars_last90 / stars_prior90` (NULL if prior is 0).
- **Measurement guard (exact form):** the window is `measured` only if the walk reached a star older than now−180d (i.e. the prior window is fully covered). If the page cap stopped the walk first, mark `surge_status = 'unmeasurable_truncated'`. If the repo is younger than 180 days, `surge_status = 'too_young'`. Only `surge_status='measured'` may feed the surge classes.
- vel7 / vel28 / vel30 come from the same timestamps (daily counts), so acceleration is real, not the 26-day-anchor artifact (Pi defect D6.6). Store a daily histogram (`star_daily`) for the last 180 days.
- **Star-quality sample (new):** from the newest 200 stargazers, compute `pct_new_accounts` (account created < 30 days before starring) and `pct_empty_accounts` (0 repos and 0 followers). This directly attacks "velocity leaders are contaminated" (D6.1).
- **Phase 0 spike:** verify GraphQL `last/before` paging works beyond 40k stars and measure points cost. If paging is capped, the guard still holds (truncated → unmeasurable). Record findings in NOTES.md.
- Budget: max 2,000 GraphQL points per daily run; surge measurement for already-tracked repos is refreshed weekly (stars are stable over a day), new candidates measured on first sight.

Daily `GET /repos` snapshots are still stored in `snapshots`; cross-check: `abs(stargazerCount_graphql − snapshot_stars)/snapshot_stars ≤ 2%`, else mark the measurement `inconsistent` and exclude it (D6.7).

### 4.3 Hacker News (Algolia) — confirmation + discovery
- Discovery: `search_by_date?tags=story&query=github.com&numericFilters=created_at_i>{24h ago}` and `tags=show_hn`.
- Per-repo confirmation: two queries, both stored, neither trusted alone (D6.3):
  - URL-anchored: `query={owner}/{repo}` restricted to `url` attribute (`restrictSearchableAttributes=url`).
  - Name-anchored: `query="{name}"`, then filtered by the **collision filter** (§5).
- Record per story: objectID, title, url, domain, author, points, num_comments, created_at.

### 4.4 Other confirmation sources (each optional, gated by probe)
Lobsters (`/hottest.json`, `/newest.json`, `/search.json?q=`), dev.to (`/api/articles?tag=` and search), Bluesky (`public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=`; use only the *linked domains* inside posts, never post counts). Each contributes **linked domains**, not post counts.

### 4.5 Switching / ecosystem sources
- **New-repo feed (revision 2, replaces GitHub search):** every repo created in GH Archive `CreateEvent` is checked against the tracked universe by name pattern and description. Candidates get their README fetched from raw.githubusercontent.com and must pass the anchor test (§5). Matched artifacts are stored with their creation date, so "new in 120d" is exact from collection start. For the first 120 days, also use OSS Insight search if the spike shows it works; otherwise switching counts build up from zero and the digest says `switching: counting since <start date>` (never pretend the count is complete).
- **Name patterns for ports:** `{name}-(nix|nixos|rs|go|py|js|ts|swift|kt|port|plugin|mcp|vscode|nvim|cli)`, `(awesome-)?{name}-`, `{name}.(nvim|el)`.
- **deps.dev** (`api.deps.dev/v3alpha/systems/{sys}/packages/{pkg}:dependents`) for npm/PyPI/Cargo/Go packages whose source repo is this repo → dependent count. Map package↔repo via the package's `links.repo`.
- **Repology** (`/api/v1/project/{name}`) → number of distinct distro repositories packaging it, and first-seen tracking (store daily; "new packaging in 120d" = repos that appear later than first observation). Independent packagers are a strong switching signal.
- Registries (corroborate only): PyPI (pypistats), npm downloads, crates.io, Homebrew install analytics.

### 4.6 Discovery universe (candidate intake, daily)
1. **GH Archive star leaders (revision 2):** any repo with ≥ 40 stars in the last day or ≥ 150 in the last 7 days enters as a candidate (this covers both new repos and established repos waking up, for the surge path).
2. **GH Archive acceleration:** any repo whose last-7-day stars are ≥ 3x its previous 7 days and ≥ 50 absolute.
3. HN/Lobsters stories linking to GitHub in the last 24h.
4. GitHub trending HTML (daily/weekly, all languages) — intake only, never a signal.
5. Hugging Face trending spaces/models with a GitHub link (if allowlisted).
6. Ecosystem back-links: when an artifact is found that ports/extends a repo not yet tracked, enqueue that repo (this is how Omarchy-style leading signals surface).

Pre-filters before any expensive measurement (D6.5): drop forks, archived, `awesome`/`tutorial`/`course`/`boilerplate`/`template`/`interview`/`roadmap`/`cheatsheet` in name/topics/description, repos with no code (language NULL and size < 50 KB), and repos whose fork/star < 1% above 1,000 stars (store as `rejected_shape` so they're not re-checked for 30 days).

Universe cap: ~600 tracked repos (status `candidate|watch|report`), oldest-unrewarded pruned to `dormant` after 120 days below `watch`.

---

## 5. Name-collision filter (fixes medusa/Handy/hypit/xerj)

Implemented once in `util_text.py`, used by ecosystem and confirmation stages.

An artifact or story **matches** repo R only if at least one *anchor* holds:
- A1: it contains R's GitHub URL or `owner/repo` string, or R's homepage domain (if homepage is not a generic host like github.io root, vercel.app root, etc.).
- A2: it is a GitHub repo whose dependency manifest references R's published package (via deps.dev).
- A3: name match on **whole-word, case-insensitive** regex `\b{name}\b` AND topical overlap: Jaccard of token sets (topics + description words, stop-worded) ≥ 0.15 OR shares ≥ 1 GitHub topic with R, AND (if `name` is a dictionary word or ≤ 4 chars) the owner name or homepage also appears.

Name-only hits that fail all anchors are stored with `matched=0` so the collision rate is measurable: `collision_rate = 1 − matched/name_hits`. If `name_hits ≥ 20` and `collision_rate ≥ 0.8`, set flag `name_collision` and the ecosystem count uses anchored matches only.
Dictionary-word list: ship a 10k common English words file (`data/common_words.txt`, generated once from a public word list during implementation; if unavailable, use Python's `/usr/share/dict/words` if present, else treat all names ≤ 6 chars as "common").

Topical sanity check kept from the Pi: "a real ecosystem has 20+ new artifacts in 120 days and they are topically related; a collision set has 0–2 new among 40–50". The weekly digest lists 2 example artifact names per alerted repo so a human can eyeball them.

---

## 6. Scoring

Keep the Pi formula so results are comparable, with fixes marked **[new]**.

### 6.1 Components (0–100)
- velocity 25: `sqrt(min(vel7,100)/100)*25` — vel7 from exact GH Archive daily stars (NULL until 7 complete days collected).
- acceleration 20: `min(max(vel7/vel28 − 0.8, 0)/0.8, 1)*20`. **[new]** If vel28 < 1 star/day, use 30-day vs prior-30-day counts instead, and if both windows < 30 stars total, acceleration is NULL → component scores 0 and is flagged `low_volume`.
- switching 25: `min(new_artifacts_120d/10, 1)*25`, where new_artifacts_120d = anchored GitHub artifacts created in 120d + new Repology packagers in 120d + new deps.dev dependents in 120d (dependents counted at most 5 toward the total so one big library cannot dominate).
- substance 15: 15 if ≥3 real technical topics, 10 for 2, 5 for 1, 0 for 0 or any banned topic.
- confirmation 15: `min(distinct_independent_domains_90d/3, 1)*15`.

### 6.2 Penalties **[new]**
- Star-quality (revision 2): if `pct_repeat_stargazers > 0.30` → flag `suspicious_stars`, velocity component × 0.5, and the repo cannot be `inflection`.
- Repost campaign: if > 50% of HN/Lobsters stories for the repo come from one submitter and the max points < 30 → flag `repost_campaign`; those stories contribute 0 domains.

### 6.3 Shape metrics (reported, used in flags)
fork/star, issue/star (open issues minus open PRs where known). Flags: `adoption_strain` (issue/star > 10%), `star_collected` (fork/star < 2% above 800 stars).

### 6.4 Surge classes (age ≥ 180d for test, class awarded at age ≥ 365d; `surge_status='measured'` required)
- Surge candidate: `share90 ≥ 0.15` AND `stars_last90 ≥ 750` AND `800 ≤ stars ≤ 400000`.
- `fast`: ratio90 ≥ 1.5. `climb`: 0.7 ≤ ratio90 < 1.5. Below 0.7: `decelerating` (excluded).

### 6.5 Classification (apply in order)
1. age ≥ 365 AND surge `fast` AND score ≥ 55 → **resurgent**
2. age ≥ 365 AND surge `climb` AND score ≥ 55 → **climber**
3. score ≥ 75 AND acceleration_ratio ≥ 1.2 AND ≥1 independent domain in 90d AND confirmation data fresh AND not `suspicious_stars` → **inflection**
4. score ≥ 75 AND acceleration ≥ 1.2 otherwise → **emerging**
5. score ≥ 60 → **emerging**
6. score ≥ 40 → **watch**
7. otherwise → **dormant** (only if a *measured* retention failure or score < 40 on fresh data; missing data → `unscored`, never dormant)

Gates (reject unless surge-class): no series; age < 30 or > 730; ecosystem < 3 anchored artifacts; retention failure (latest 30d mentions < 50% of peak 30d month, only when ≥ 3 months of mention data).

### 6.6 Freshness (fixes stale HN, D8 #1) **[new]**
- Each source has a **canary**: HN must return ≥ 20 stories for `query=github.com` in the last 24h; Lobsters hottest must return ≥ 10 items; GitHub search must return results for a fixed query. A run where the canary fails is recorded `ok=0` even if the HTTP calls succeeded with zero rows. This distinguishes "no mentions" from "collector broken".
- Each score row stores `confirm_fresh_hours` = hours since the last successful confirmation-source run for that repo. If > 48h, confirmation is `stale`: the repo may not *newly* become `inflection` (it can keep a previously earned class), the alert/digest shows "confirmation data stale since <date>", and a Health notification fires once.
- `source_health` view: per source, last_ok, consecutive failures, last canary value. Shown as one line in every digest.

---

## 7. Alert ledger and dedupe (fixes duplicate alerts, D8 #2)

- Exactly **one** stage (`alert.py`) emits notifications, after all scoring paths have merged into a single `shortlist` keyed by repo. Surge path and score path both produce candidates; `alert.py` takes the higher class per repo.
- `alerts` table keyed by `full_name` (not by kind): `(full_name, first_alerted, last_alerted, last_class, last_score, times_alerted)`.
- Rules: alert if repo never alerted; or class rank increased (watch < emerging < climber < resurgent < inflection); or 60 days since last alert and still ≥ emerging with score up ≥ 10. Never more than one alert per repo per 7 days. Daily cap 3 (overflow goes to the digest as "also qualified").
- Idempotency: `alert.py` writes `notify.txt` and the ledger rows in one transaction with the run_id; re-running the same day produces the same (or empty) output and never double-alerts.

---

## 8. Explanation text (deterministic)

`render/alert_text.py` builds each alert from stored values only:
```
foo/bar — INFLECTION — score 81/100
stars 12,410 (GitHub API, 23 Nov 06:41) · +3,920 in 90d (share 31.6%, 2.4x prior 90d; exact stargazer timestamps)
switching: 14 new artifacts in 120d (of 22) e.g. foo-nix, bar-vscode
confirmation: 3 independent domains in 90d (lwn.net, theregister.com, simonwillison.net)
shape: fork/star 9.8% · issue/star 11.2% (adoption strain)
why now: v2.0 released 2 Nov (release cadence 11 days)        [surge classes only; else omitted]
falsifier: star pace falls below 0.7x prior 90d, or no new artifacts by 22 Feb 2027
<https://github.com/foo/bar>
```
- **why now**: the release closest before the acceleration start (largest weekly star jump in 90d) if within 21 days; else the top-points HN/Lobsters story within 14 days before it; else the literal text `cause unexplained (treat as a warning)`.
- **falsifier templates** (`render/falsifiers.py`) by class: inflection/emerging → "acceleration < 1.0 and fewer than N/2 new artifacts by <date+90d>"; resurgent → "ratio90 < 0.7 by <date+60d>"; climber → "ratio90 < 0.7 or share90 < 10% by <date+90d>". The falsifier is stored with the prediction (§10) and evaluated automatically.
- Any NULL renders as `unavailable`.

---

## 9. Scheduling (Claude scheduled tasks)

Times are Europe/London (Jack's other tasks use London). All bound to **the Softwatch project thread session** (same pattern as his other projects). Minutes are jittered off :00/:30.

| Task name | Cron | What the session does |
|---|---|---|
| Softwatch daily | `CRON_TZ=Europe/London 43 6 * * *` | `bash /mnt/project-files/softwatch/run.sh daily`; if `out/notify.txt` non-empty, post it verbatim with `post_message`; else `no_reply_needed`. |
| Softwatch weekly digest | `CRON_TZ=Europe/London 14 8 * * 1` | `run.sh digest` → read `out/digest_input.json` → write ≤ 12-row digest following §2.1 using only numbers in that file → post. |
| Softwatch monthly review | `CRON_TZ=Europe/London 22 9 9 * *` | `run.sh review` → post `out/notify.txt` (precision/recall table, control-set size, outcomes resolved, proposed threshold changes — proposals only, never auto-applied). |

`run.sh` responsibilities: `cd` into the folder, `pip install -q requests` if missing, DB copy-in (§3.2), `python -m softwatch <cmd> --run-id $(date -u +%Y%m%dT%H%M)`, copy-out, append to `out/run.log`, exit non-zero on failure. If the pipeline fails, `run.sh` writes a Health message to `notify.txt` itself so a failed run still reaches Jack once.

The scheduled task prompts must be short and refer to a prompt file: `Read /mnt/project-files/softwatch/prompts/<task>.md and follow it exactly.` Write `prompts/daily.md`, `prompts/digest.md`, `prompts/review.md` with the instructions above plus: "Do not alter, round or add numbers. Do not search the web to fill gaps. If a value says unavailable, keep it."

Token discipline: the daily run should cost one script call and at most one post. The LLM does not read the DB.

---

## 10. Prediction ledger, outcomes and controls (fixes survivorship bias + small control set, D8 #5/#6)

### 10.1 Prospective predictions
Every repo that receives class ≥ `watch` for the first time, and every alert, writes a frozen row in `predictions`: `(full_name, made_at, class, score, components_json, metrics_json, falsifier_json, horizon_days=90)`. Never updated.

### 10.2 Outcome labels (objective, computed by `outcomes.py` at made_at + 90 and + 180)
- **hit**: stars grew ≥ 2.5x OR independent domains (cumulative) ≥ 8 OR Repology packagers ≥ 5, AND ratio90 at evaluation ≥ 0.7.
- **fizzle**: ratio90 < 0.5 AND new artifacts in last 90d < 3.
- **falsified**: the stored falsifier condition is true.
- otherwise **open**.
Results feed precision by class in the monthly review. This is the first time the system learns how often identical signals *fizzled*.

### 10.3 Shadow controls (blind sample)
Each week, `discover` draws 30 random repos from the same strata as real candidates (age band × star band × language) out of all repos seen in GH Archive with ≥ 1 star that week, scores them with the same code, and writes them to `predictions` with `is_control=1`. They are never alerted. After 90 days their outcomes give a base rate: "of repos that looked like X, how many hit?". Target: ≥ 300 controls within 10 weeks (vs n=6 on the Pi).

### 10.4 Retrospective backtest (`backtest.py`, monthly)
Replay the reference hits (seeds) at T−90/60/30 using star-history SVG curves for past star counts (subject to the anchor guard) and GH Archive data once it covers the window. Mentions use HN `numericFilters=created_at_i<T`. Ecosystem uses stored artifact creation dates (only valid for T after collection start; earlier backtest points report switching as `unavailable`). Report recall, median lead time, precision vs controls. Unit-test the backtest on fixtures so it cannot silently crash (Pi D7: crashed on `KeyError('vel7')` and nobody noticed). A backtest that produces no number must fail loudly and send a Health message.

Known limit to state in every review: a repo that goes dormant→dominant inside 60 days is invisible to a 90-day system (Hermes Agent case).

---

## 11. Acceptance tests (must pass before scheduling)

1. `pytest` — unit tests for: collision filter (cases: medusa, Handy, hypit vs "hypothesis", xerj vs "Xerox", omarchy-nix as a true match), scoring formula (Pi reference numbers), measurement guard (truncated walk → unmeasurable; prior=0 → ratio NULL), dedupe ledger (surge+score path for the same repo → one alert), freshness (stale HN → no new inflection + one health message), renderers (NULL → `unavailable`), backtest on fixtures.
2. `softwatch probe` shows which hosts work; NOTES.md records the result.
3. **Test-set run** (`seeds/test_set.toml`): ARTEX, sglang, plannotator, AstrBot, cua, promptfoo, tuios, hypit; traps chromium/chromium, metabase/metabase, JetBrains/intellij-community; known quantities omacom/omarchy, CyberTimon/RapidRAW, NousResearch/hermes-agent, ollama/ollama, zed-industries/zed, meta/astryx. Output `out/test_set_report.md` in the Pi's per-repo format. Pass criteria:
   - The three traps must be `unmeasurable` (too few star-history anchors in the prior window) or measured-and-not-surging. They must never be resurgent/climber on unobserved windows.
   - ollama and zed must not be resurgent/climber unless the measured numbers say so (then explain).
   - Every number in the report traces to a `raw_fetches` row (write a check script `softwatch audit` that samples 20 numbers and prints their source URLs).
   - Compare with Hermes's sealed answers (in the handover file, Part C) and list disagreements with reasons. Agreement is not the goal; traceability is.
4. **Dry-run notification:** run `daily` with `--dry-run` (writes `notify.txt`, does not update the alert ledger), post it in the thread as a test alert so Jack confirms it arrives on his phone.

---

## 12. Out of scope for v1 (future)
- GH Archive via BigQuery (needs Jack's GCP project) for full-history backtests and a bigger control set.
- Reddit, Product Hunt, YouTube (blocked or token-only; YouTube is a lagging indicator anyway).
- Jack feedback loop (👍/👎 on alerts used to *order* the digest, never to change verdicts).

---

## 13. `config.toml` (initial values)

```toml
[gates]
min_age_days = 30
max_age_days = 730
min_ecosystem_artifacts = 3
retention_ratio = 0.5

[weights]
velocity = 25
accel = 20
switching = 25
substance = 15
confirm = 15

[verdict]
inflection = 75
emerging = 60
watch = 40
accel_trigger = 1.2

[surge]
min_age_days = 180
class_min_age_days = 365
share_90d = 0.15
min_growth_90d = 750
min_stars = 800
max_stars = 400000
fast_ratio = 1.5
min_ratio = 0.7

[quality]
pct_repeat_stargazers_max = 0.30
collision_rate_flag = 0.8

[alerts]
daily_cap = 3
per_repo_min_days = 7
realert_days = 60
realert_score_delta = 10

[freshness]
confirm_stale_hours = 48

[budget]
ossinsight_per_run = 1500
ossinsight_search_per_min = 10
raw_github_per_run = 500
star_history_per_run = 200
gharchive_parallel = 4
hn_per_run = 400
controls_per_week = 30
universe_cap = 600
```

---

## 14. DB schema (SQLite)

```sql
repos(full_name PK, owner, name, created_at, topics_json, homepage, language, status, first_seen, last_measured, flags_json)
snapshots(full_name, ts, stars, forks, open_issues, open_prs, pushed_at, PRIMARY KEY(full_name, ts))
star_daily(full_name, day, stars_added, PRIMARY KEY(full_name, day))
surge(full_name, ts, history_source, surge_status, stars_last90, stars_prior90, share90, ratio90, anchors_last90, anchors_prior90, pct_repeat_stargazers, PRIMARY KEY(full_name, ts))
gharchive_hours(hour PK, ok, n_events, bytes, seconds)
star_daily_coverage(day PK, hours_ok)
new_repos(full_name PK, created_at, description, checked, matched_to)
mentions(source, item_id, full_name, title, url, domain, author, points, comments, created_at, matched, anchor, PRIMARY KEY(source, item_id, full_name))
artifacts(full_name, artifact, kind, created_at, url, matched, anchor, first_seen, PRIMARY KEY(full_name, artifact))
packaging(full_name, repo_name, first_seen, PRIMARY KEY(full_name, repo_name))
releases(full_name, tag, published_at, downloads, PRIMARY KEY(full_name, tag))
scores(full_name, ts, run_id, score, class, components_json, metrics_json, flags_json, confirm_fresh_hours, PRIMARY KEY(full_name, ts))
alerts(full_name PK, first_alerted, last_alerted, last_class, last_score, times_alerted, last_run_id)
predictions(id PK, full_name, made_at, is_control, class, score, components_json, metrics_json, falsifier_json, horizon_days)
outcomes(prediction_id, evaluated_at, label, evidence_json, PRIMARY KEY(prediction_id, evaluated_at))
source_runs(run_id, source, started, finished, ok, n_requests, n_items, canary_value, error)
raw_fetches(id PK, run_id, url, status, fetched_at, sha256, body_gz)
```
`raw_fetches` older than 30 days: keep url/status/sha256, drop body_gz (keeps DB small; provenance retained).

---

## 15. Build order for the implementer (Haiku)

1. Phase 0: `http.py`, `budget.py`, `probe` stage; run probe; record results; GH Archive timing spike and OSS Insight spike (§4.0). **Stop and report** if data.gharchive.org or api.ossinsight.io is still unreachable (prerequisite P2 not done).
2. DB + config + `run.sh` with copy-in/copy-out and lock.
3. `gharchive` ingest (daily aggregates) and `measure` (OSS Insight snapshot + star-history backfill + guard + `pct_repeat_stargazers`) with tests.
4. `util_text` collision filter with tests; `ecosystem`; `confirm` (HN first, then others) with canaries.
5. `score` + classification + freshness, tests using Pi reference values.
6. `alert` ledger + renderers + falsifiers; `--dry-run`.
7. `discover` (intake + pre-filters + controls).
8. Test-set acceptance run (§11.3) and `audit`.
9. `digest`, `outcomes`, `review`, `backtest` with tests.
10. Prompt files, then hand back to the planning model/Jack for scheduled-task creation and the phone test (§11.4).

Keep each module < 300 lines. Commit-style changelog entries in NOTES.md after each step.

## 16. Prerequisites Jack must do before implementation starts
- **P1:** ~~Connect GitHub~~ Not needed (revision 2).
- **P2:** Allow the hosts in §1.1 in the project's cloud environment network settings (Project settings → Cloud environment → gear → Network access → Allowed domains).
- **P3:** Done: Claude app thread notifications. Make sure notifications are on for the Softwatch thread in the Claude app.
