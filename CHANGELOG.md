# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Deferred to a future release
- Replace `print()` calls with structured `logging` so library consumers can
  suppress or redirect output. Currently every diagnostic goes to stdout/stderr.
- Per-host adaptive rate limiting + exponential backoff on 429/503.
- Sitemap-driven seed discovery (`crawl.follow_sitemaps` is currently declared
  but not implemented).
- ToS acknowledgement gate (`--i-have-authorization`).

## [0.1.0] - 2026-05-01

Initial release.

### Added
- Profile-driven crawler with YAML configuration and example stubs for
  Confluence, Notion, and SharePoint.
- `Fetcher` protocol with two implementations:
  - `PlaywrightFetcher` — Chromium with cookie injection, default for any site.
  - `HttpxFetcher` — server-rendered docs, ~10× faster, no Chromium needed.
  Profile picks via `crawl.engine: playwright|http`.
- `auth-scrape` CLI with subcommands: `list`, `setup`, `init`, `doctor`,
  `cookies`, `run`, `combine`, `search`. All commands accept either a
  profile name or a path to an external YAML file.
- `auth-scrape setup` — one-shot post-install bootstrap that installs the
  Playwright Chromium browser (and Linux system deps if applicable), then
  verifies the environment. Reduces the install story to two commands:
  `pipx install auth-scrape && auth-scrape setup`.
- `auth-scrape doctor` — environment diagnostics: Python/Playwright/Chromium
  presence, container detection, cookies-file validity (counts + expiry).
- `auth-scrape init` — scaffold a profile from a seed URL with
  auto-derived `allow_prefixes` and `cookie_domains`.
- Resume contract with separate `visited` and `failed` sets; atomic state
  writes; corrupt-file backup with warning.
- Focused crawl with keyword scoring (title/h1/h2/url/anchor/body weighted)
  and configurable `drilldown_depth` (0 = strict matched→matched chains).
- Auth-wall detection: HTTP 401/403 plus URL-pattern-based login-redirect
  detection. Crawl aborts after N consecutive auth failures with a clear
  "re-export cookies and resume" message.
- Cookie-file hardening: written 0o600; warning when target is inside a
  git working tree.
- Slug collision protection via SHA-1 suffix; saved markdown files cannot
  silently overwrite each other.
- Profile schema validation: unknown YAML keys raise `ProfileError` with
  a "did you mean" suggestion instead of a raw `TypeError` traceback.
- Public library API exposed via `from authscrape import ...`.
- 100+ unit tests covering URL handling, profile loading, cookie loading,
  scoring, extraction, state persistence, and end-to-end BFS via a fake
  fetcher (no Chromium required).

[Unreleased]: https://github.com/mkhalid-s/auth-scrape/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mkhalid-s/auth-scrape/releases/tag/v0.1.0
