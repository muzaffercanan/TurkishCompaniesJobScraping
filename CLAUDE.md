# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

**İlan Radarı**: a local-only (127.0.0.1) Flask web app that scans the career pages of ~2,000 Turkish software/tech/game companies and shows all job postings in one UI. The user talks in Turkish; README, UI text, code comments and log messages are Turkish (comments/logs in ASCII Turkish without diacritics, e.g. `kariyer sayfasi bulunamadi`). Keep that style.

Requirements: Python 3.12, `pip install flask playwright openpyxl`, `python -m playwright install chromium`. No build step for the frontend.

## Commands

```bash
python -m app.server                                   # run (port 8765, opens browser, starts auto-scan thread); Baslat.bat does the same
python -m app.server --no-browser --no-auto --port 8766  # dev/test server: no browser, no automatic real scans
python -m unittest discover -s tests -t .              # all tests (offline, replay recorded responses)
python -m unittest tests.test_auto -v                  # one module
python -m unittest tests.test_auto.Config.test_defaults_when_no_file   # one test
python -m tests.record                                 # re-record live fixtures (needs internet)
python -m tests.record custom_baykar                   # re-record a single source
python -m scripts.program_listesi                      # export found program pages -> Program_Sayfalari.csv
```

`.claude/launch.json` defines `ilan-radari` (8765) and `ilan-radari-test` (8766, `--no-auto`). For preview/verification use **`ilan-radari-test`** so no real scan of 2,000 sites is kicked off. The server refuses to start if one is already running on the same port; `/api/meta` returns `code_stale=true` when files under `app/` changed after the server started — restart it after editing Python.

## Architecture

**Data flow:** `Turkiye_Yazilim_Firmalari_v2.xlsx` (sheet `Firmalar`, read-only) → `db.import_excel` (empty DB only, then seeds known ATS mappings from `ats_found.json`/`ats_manual.json`) and `db.sync_excel` (adds new rows by name on every start/scan) → `data/app.db` (SQLite, WAL) → `scanner` fills `jobs` → `server.py` JSON API → `app/static/app.js`.

**Database (`app/db.py`):** schema migrations are additive `ALTER TABLE ... ADD COLUMN` checks inside `connect()` — add new columns there, not in `SCHEMA`. Threads must use `db.tl()` (thread-local connection) and write through `db.write()` (global lock + commit). `trn()` is a SQL function (`fold`) for Turkish/case-insensitive search. Shared SQL fragments `db.RECENT` ("new job" rule, needs alias `j` and two cutoff args) and `db.FIT` ("Bana uygun" filter) are used by both the server and the scanner's end-of-scan summary — change them in one place.

**Scanning (`app/scanner.py`):** one scan at a time (`_run_lock`), running in a background thread; progress lives in the module-level `STATE` dict polled by `/api/scan/status`. Modes: `hizli` (known ATS + custom readers via ThreadPoolExecutor, then generic career pages and known program pages via Playwright pool), `tam` (+ discovery of all other companies), `yeni`, `program`, `firma` (one company), `site` (Brave Search for missing websites, then `yeni`).
- A company's source is decided by `companies.ats`: an ATS key in `ats.READERS` → `ats.fetch_jobs`; `'custom'` → `custom.REGISTRY[ats_slug]`; `'generic'` → Playwright render + `generic.extract`. `careers.discover` finds the career page and detects the ATS from page content (`ats.detect`).
- Every reader returns a list of dicts `{id, title, location, team, url, posted, remote, desc?, level?, tech?, detail?}` (optionally an `ats.Jobs` list carrying `note` for the status line and `confirmed=True` when an empty list is definitive, e.g. Workday has no Türkiye in its country facet — this bypasses the empty-list guard); `scanner.upsert` is the single place that classifies (level/tech/region), inserts/updates, and closes jobs missing from a definitive list. Guard: if a source that had many jobs suddenly returns 0, jobs are not closed.
- `is_baseline=1` marks jobs from a source's first successful scan so they don't count as "new".
- ATS 403/404/410 → company falls back to `generic` and gets rediscovered.
- `source_runs` records every per-source run; health flags (count drop, low ID overlap) feed the "Kaynak sağlığı" tab.
- `enrich.py` fetches detail pages for jobs without descriptions (TR/remote/unspecified only, max per company per scan, paced); `fetch_detail` returns `(desc, posted, location)` and an empty list location is filled from it. `seniority.py` derives level from description text.
- `generic.extract(url, links, html)` first takes schema.org `JobPosting` JSON-LD (`generic.jsonld_jobs`), then link heuristics. Workday filters to the Türkiye country facet when the tenant has one. Program pages get their location from `programs._location` (never hard-coded).
- Health: `scanner._check_health` runs for ATS/custom and `genel` (threshold 5 for `genel`); on ID churn the new rows get `is_baseline=1`.
- `browser.py` keeps one Playwright browser per thread (`close_local()` at worker exit). `_browser_pool` abandons a hung worker after `STALL_SECONDS`.

**HTTP (`app/util.py`):** every request goes through `util.fetch` (custom readers via `custom._open`): TLS verified first, per-host fallback to unverified only on certificate errors (`INSECURE_HOSTS`, shared with Playwright), max `HOST_LIMIT` concurrent requests per host, UA ends with `IlanRadari/1.0`. Pass `robots=True` for site crawling (career/program/detail pages, company endpoints); documented ATS APIs stay `robots=False`. `browser.render` always checks robots.txt. A robots block raises `HttpError('robots')`; the scanner closes that source's jobs and sets status `robots` (`_robots_block`). HTML readers use `app/dom.py` (stdlib tree), not regex. `util.log` (`ilan_radari` logger) goes to `data/logs/tarama.log` only after `util.setup_file_log` (called in `server.main`, never in tests).

**Auto-scan & notifications:** `auto.py` runs a scheduler thread (settings in `data/config.json`, shared with the Brave API key via `search.CONFIG`); after an auto scan, `scanner._notify_fit` sends a Windows toast through PowerShell (`notify.py`) for new "Bana uygun" jobs.

**Frontend:** plain `index.html` + `app.css` (design system/tokens, light/dark) + `app.js` (all logic, no framework). README's "Arayüz" section documents the intended behaviours (filters, seen state, keyboard shortcuts) — keep README in sync when changing them.

**`scripts/`:** one-off/maintenance scripts from building the company list (Excel building, ATS discovery, probing). Not used by the app at runtime.

## Tests

- `tests/readers.py` defines `CASES` and a `Recorder` that monkeypatches `util.fetch`, `ats.fetch`, `custom._open` and `time.sleep` to replay `tests/fixtures/*.json`. A changed job count vs. the fixture means a reader broke. When adding a new ATS/custom reader, add a case there and record it.
- DB tests subclass `tests.tempdb.TempDb`, which redirects `db.DB_PATH` to a temp file — never let tests touch the real `data/app.db`. Tests also redirect `search.CONFIG` and mock notifications.

## Data files

`data/app.db` and `data/config.json` hold the user's personal marks (applied/hidden/starred/notes) and API key; they are gitignored — don't delete, reset or commit them. The Excel file is never written by the app.
