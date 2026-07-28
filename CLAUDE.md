# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Moodle course-material downloader for UNSW (`moodle.telt.unsw.edu.au`), targeting students downloading materials for courses they are enrolled in. Python 3.11+ (uses `tomllib`), Rich terminal UI (bilingual zh/en, Chinese default), Selenium-driven Okta SSO login with cookie persistence. See also `AGENTS.md` (Chinese) for the same conventions.

## Commands

```bash
pip install -r requirements.txt        # deps: requests, beautifulsoup4, selenium, rich
python -m pytest tests/ -q             # run all tests
python -m pytest tests/test_scanner.py -q            # one file
python -m pytest tests/ -k "keyword" -q               # one test by name
python -m compileall moodle_scraper/ main.py          # syntax check
```

Running the app: `python main.py` (interactive), `python main.py <course_id>`, `--browser chrome|edge|firefox`, `--workers N`, `--lang zh|en`, and an undocumented `--discover START-END` that probes a course-ID range.

Post-download study flags (these short-circuit in `main_impl()` **before** authentication, since they only read local files): `--index [DIR]`, `--obsidian VAULT` (+ `--overwrite`, `--copy-files`), `--notebook PATH` (+ `--days N`). The MCP server runs separately: `python -m moodle_scraper.mcp_server --root DIR`. PDF text extraction is an optional extra (`pip install pypdf`) — lazily imported, degrades to empty text when absent, never a hard dependency.

**Do not run `python main.py` from automation.** Both `main.py` and `moodle_scraper.__main__.main()` block on `input()` prompts (crash-guard "press Enter to exit", Y/n confirmations) and require a real browser for login. For programmatic checks, call `main_impl()` or the individual modules directly.

## Architecture

Flow: `main.py` → `moodle_scraper.__main__.main_impl()` → `AuthManager.get_authenticated_client()` → `Scanner(client)` → `Downloader(client)` → summary.

- **`main.py`** — thin launcher: crash guard (never lets the console window close silently), manual argv parsing (no argparse), Windows UTF-8 stdout fix. Delegates to the package.
- **`moodle_scraper/__main__.py`** — orchestration only. `main_impl(config, ...)` returns an exit code (0 ok, 1 error, 2 partial download failures); `main()` wraps it with the blocking exit prompt.
- **`moodle_scraper/http.py`** — the key seam. `HttpClient` is a Protocol (`get` / `get_stream`); `RequestsHttpClient` is production, `FakeHttpClient` is the test double (pre-registered responses with URL prefix matching, plus a `request_log`). Scanner and Downloader depend only on this Protocol, never on `requests`.
- **`moodle_scraper/auth.py`** — `AuthManager`: tries cached cookies from `moodle_cookies.json` first, validates them with a probe request, otherwise launches a Selenium browser (auto-detect order chrome → edge → firefox) and polls the URL until the user completes Okta login, then saves cookies and returns an authenticated `RequestsHttpClient`.
- **`moodle_scraper/scanner.py`** — `Scanner`: `list_courses()` parses the `/my/` dashboard; `fetch_course_name()`; `discover_courses()` probes an ID range in parallel; `scan_course()` is two-stage — direct `mod/resource` links from the course page, then drills into `mod/page` sub-pages for nested `pluginfile.php` links, filtered by `file_keywords` / `file_extensions` (empty filters = accept everything). Raises `ScanError` when a response is the login page.
- **`moodle_scraper/downloader.py`** — `Downloader.download_all()`: skips files that already exist on disk, downloads the rest with a `ThreadPoolExecutor`, writes to `.part` then `os.replace()` for atomicity, returns a `DownloadResult`.
- **`moodle_scraper/config.py`** — `AppConfig` dataclass loaded from `config.toml` (missing file/fields fall back to defaults). A module-level singleton `config = AppConfig.load()` is created at import time; tests should build their own `AppConfig` instead of mutating it.
- **`moodle_scraper/i18n.py`** — zh/en message catalogs and the `t(key, **kwargs)` lookup; `set_language()` mutates module-level state, resolved once in `main_impl()` from `--lang` / `config.language` (CLI wins, unknown values warn and fall back to zh).
- **`moodle_scraper/ui.py`** — `RichUI`; all user-facing output goes through `ui.status(emoji, msg)`, panels, and progress callbacks — no bare `print` in library code.
- **`moodle_scraper/utils.py`** — pure functions: `sanitize_filename`, `extract_extension`, `is_login_page`.
- **`moodle_scraper/study/`** — the post-download layer, operating on files already on disk (never the network, never login). `index.py` is its contract: `build_index()` walks a root treating each subdir as a course, producing `CourseIndex`/`Material` with heuristic `kind`/`week` and optional extracted text, persisted to `.moodle-index.json`. `obsidian.py` exports a vault (per-course MOC + week-bucketed notes with YAML frontmatter and wikilinks); `notebook.py` emits a revision `.ipynb` as raw JSON. Both consume `CourseIndex` and, like Scanner/Downloader, return dataclasses rather than printing.
- **`moodle_scraper/mcp_server.py`** — MCP server over stdio (hand-rolled JSON-RPC 2.0, no `mcp` dependency) exposing 5 tools to AI agents. `handle_request(request, index)` is a pure function so the protocol is testable without stdio; `serve()` takes injectable `stdin`/`stdout`.
- **`skills/moodle-revision/SKILL.md`** — agent-facing Skill describing the revision workflow over the MCP tools / vault.

The Moodle base URL is hardcoded in `scanner.py` and `auth.py`.

## Conventions

- Full type annotations on all parameters/returns; every module starts with `from __future__ import annotations`.
- Custom exceptions per domain (`ScanError`, `AuthError`); worker-level failures are swallowed per-item so one bad page/file never aborts the batch.
- Imports grouped stdlib → third-party → local, blank line between groups.
- Tests use `FakeHttpClient` through the `HttpClient` Protocol — never hit the network. Follow this seam pattern when adding dependencies.
- Never hardcode user-visible text: add a key to **both** the `_ZH` and `_EN` catalogs in `i18n.py` and call `t()` at the point of use (emoji prefixes stay in the code, not the catalog). `tests/test_i18n.py` enforces key and placeholder parity. Exception: `main.py` keeps bilingual static text because it must work before the package imports. Comments stay Chinese.

## Repo gotchas

- `ARTS1630-Japanese_1_(T2_26)/`, `PHYS1231_Materials/`, `UNSW_Moodle/` are downloaded course PDFs (output data), not source — leave them alone.
- `moodle_cookies.json` contains live session cookies. Never commit it or print its contents.
- `启动下载器.bat` is a Windows double-click launcher menu for end users.
- `assets/demo-*.png` (README demos) and `assets/social-preview.png` (GitHub social card) are real UI renders, generated by `python scripts/gen_assets.py` (Rich `export_html` → headless-browser screenshot; needs a WebDriver). Regenerate after changing user-facing UI text or layout. The social card template is `scripts/social_preview.html`.
