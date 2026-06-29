# auth-scrape

[![Tests](https://github.com/mkhalid-s/auth-scrape/actions/workflows/tests.yml/badge.svg)](https://github.com/mkhalid-s/auth-scrape/actions/workflows/tests.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

Crawl auth-walled websites through your already-authenticated browser session and produce LLM-ready markdown. Designed for sites where you'd otherwise have to copy-paste pages by hand: documentation portals, Confluence, Notion, SharePoint, and private wikis behind SSO.

Auth model: load cookies once from your host browser; the crawler reuses them through Playwright.

## Install

Two commands:

```bash
pipx install 'auth-scrape[host-cookies] @ git+https://github.com/mkhalid-s/auth-scrape'
auth-scrape setup
```

`auth-scrape setup` runs `playwright install chromium` (downloads ~150MB once), installs Linux system libs if needed, then runs `auth-scrape doctor` to verify. Pass `--skip-system-deps` if you're on Linux without sudo.

Developer / from-source:

```bash
cd path/to/auth-scrape
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,host-cookies]'
auth-scrape setup
```

## Quickstart

```bash
# 0. Verify the install
auth-scrape doctor

# 1. Create a profile from any URL
auth-scrape init mysite --site https://docs.example.com/foo/

# 2. Export cookies from your host browser (run on host, not container,
#    if your browser lives on the host)
auth-scrape cookies mysite --browser chrome
# → cookies.json

# 3. Smoke-test then crawl
auth-scrape run mysite --dry-run                  # review scope first
auth-scrape run mysite --max-pages 5 --headed --i-have-authorization
auth-scrape run mysite --i-have-authorization
auth-scrape run mysite --resume --i-have-authorization

# 4. Concatenate into one big markdown file for LLM context
auth-scrape combine mysite
```

## Safety And Authorization

Only crawl sites you are authorized to access and automate. Review each
profile's `seeds`, `allow_hosts`, and `allow_prefixes` before running a crawl,
and respect the target site's terms, rate limits, and robots or automation
policies.

`cookies.json`, browser cookie exports, `state/`, `output/`, and combined
markdown files can contain live credentials or private content. Do not commit,
publish, or share them unless you have reviewed and sanitized them.

Profile arguments accept either a **bare name** (looked up on the search path) or **a path to a YAML file** — useful for one-off external profiles you don't want to install:

```bash
auth-scrape run /path/to/external.yaml
auth-scrape cookies ./team-shared/confluence.yaml
```

## Subcommands

```
auth-scrape setup                      One-shot post-install: Chromium + system deps + verify.
   --cookies cookies.json
   --skip-system-deps                  Skip `playwright install-deps` on Linux.
auth-scrape doctor                     Check Python/Playwright/Chromium/cookies/profiles.
   --cookies cookies.json
   --strict                            Treat warnings as failures.
auth-scrape list                       List available profiles.
auth-scrape init <name>                Scaffold a new profile YAML.
   --site URL                          Seed URL (prompts if omitted).
   --description TEXT
   --keywords kw1,kw2                  Enable focus-mode with these keywords.
   --cookie-domains a.com,b.com        Override auto-derived cookie domains.
   --max-pages N                       Default 300.
   --delay SEC                         Default 1.5.
   --out PATH                          Default ~/.auth-scrape/profiles/<name>.yaml
   --print                             Print YAML to stdout instead.
   --force                             Overwrite an existing profile.
auth-scrape cookies <profile>          Export host browser cookies → cookies.json.
   --browser auto|chrome|edge|firefox|brave|chromium|safari
   --out cookies.json
auth-scrape run <profile>              Crawl using a profile.
   --cookies cookies.json              Cookie file (default: cookies.json)
   --out DIR                           Override profile output dir
   --state FILE                        Override resume-state file
   --max-pages N                       Override page cap
   --resume                            Continue from prior state
   --no-crawl                          Fetch only seeds; don't follow
   --headed                            Show browser (debug auth)
   --dry-run                           Print planned scope without crawling
   --redact-secrets                    Redact common secrets in saved markdown
   --i-have-authorization              Confirm you are allowed to crawl the target
auth-scrape combine <profile>          Concatenate output/*.md → combined.md.
auth-scrape search <profile>           Run profile.search queries; print harvested URLs.
   --cookies cookies.json
   --headed
auth-scrape --version                  Print version.
```

## Search-driven seeds

If the target site has its own search, point the profile at it and the crawler
will run your queries first and use the results as additional seeds. This is
much higher-quality than guessing seed URLs.

```yaml
search:
  url_template: "https://docs.example.com/search?q={query}"
  result_selector: "a.search-result-link"   # CSS for result <a> tags
  queries:
    - "admin guide"
    - "workflow setup"
  max_results_per_query: 25
```

Tune the `result_selector` once with:

```bash
auth-scrape search <profile> --headed   # watch the browser
```

## Focused (keyword-driven) crawl

When `focus.keywords` is set, the crawler scores each page and prunes
non-matching subtrees. Use `drilldown_depth` to control how far past a match
you keep exploring before resuming the prune:

| Setting | Behavior |
|---|---|
| `drilldown_depth: 0` | **Strict**: only matched-page → matched-page chains are followed (option *b*). |
| `drilldown_depth: N` | **Relaxed**: after a match, allow N more hops regardless of whether the children themselves match (option *a*). |
| `keywords: []` | **Disabled**: full BFS (default). |

Page scores weight title and headings higher than body text. URL paths and
anchor text get partial credit too — a link whose URL path contains a keyword
is treated as promising even before fetching it.

```yaml
focus:
  keywords:
    - admin
    - workflow
  min_score: 1.0           # below this → not a match
  drilldown_depth: 2       # 0=strict; N=allow N hops past a match
  save: matched_and_drilldown   # matched_only | matched_and_drilldown | all
  score_weights:
    title: 5.0
    h1: 4.0
    h2: 3.0
    url: 2.0
    anchor: 2.0
    body: 1.0
```

Each page's score and match status are written into the markdown frontmatter
(`score:`, `matched:`) so you can grep results later.

## Profiles

A profile is a YAML file describing one site. Place them in:

- `./profiles/` (next to where you invoke the CLI)
- `<repo>/profiles/` (this directory — bundled profiles)
- `~/.auth-scrape/profiles/` (per-user profiles)

Schema:

```yaml
name: my-site
description: One-line description.

seeds:                     # required — at least one URL to start crawling from
  - https://example.com/docs/

crawl:
  allow_hosts: []          # any path on these hostnames is followable
  allow_prefixes: []       # any URL starting with these prefixes is followable
                           # (defaults to seed parent dirs if both lists empty)
  deny_prefixes: []        # never follow URLs matching these
  max_pages: 200
  delay_seconds: 1.0

auth:
  cookie_domains:          # used by the `cookies` subcommand to filter
    - example.com

extract:
  content_selectors:       # tried in order; first match wins
    - main
    - article
    - "[role='main']"
  strip_tags:              # children removed before markdown conversion
    - script
    - style
    - nav
    - header
    - footer
    - aside
    - noscript
  strip_inline_svg: true
  strip_data_uri_images: true
  min_content_chars: 80    # below this, treat as auth-wall/empty

output:
  dir: output/my-site
  per_page: true
  combined: combined.md
```

Bundled profiles:

- **`confluence.example.yaml`** — Atlassian Confluence (fill in tenant/space).
- **`notion.example.yaml`** — Notion (fill in workspace/page IDs).
- **`sharepoint.example.yaml`** — SharePoint Online (fill in tenant/site).

To add a site: copy the closest example, edit `seeds` + `crawl` + `auth.cookie_domains`, run `auth-scrape cookies <name>` then `auth-scrape run <name>`.

## Testing

```bash
pip install -e '.[dev]'
pytest                     # ~80 unit tests across 7 modules
pytest -k state            # filter by name substring
pytest --cov=authscrape    # coverage
```

The unit tests are fast and require no browser. They cover URL handling, profile
loading + validation, cookie loading + export file mode, focus scoring,
content extraction, and resume-state round-trip / corruption recovery.

## Cookie expiry

SSO sessions are short-lived. When pages start coming back as `! looks empty (... chars). Cookie expired?`, re-run `auth-scrape cookies <profile>` and then `auth-scrape run <profile> --resume`. The state file means you don't lose the work already done.

## Rate Limits And Backoff

Start with a small smoke test and conservative `crawl.delay_seconds`. If a site
returns `429`, `503`, or other throttling responses, stop the crawl, increase
the delay, lower `max_pages`, and resume only when appropriate.

## When extensions are blocked

The `cookies` subcommand uses `browser-cookie3`, which reads cookies from the OS keystore — no browser extension needed. On Windows it's silent (DPAPI). On macOS you'll see a one-time Keychain prompt. On Linux it may unlock gnome-keyring.

If even `pip install` is locked down on the host, fall back to manual export:
- F12 → Application/Storage → Cookies → copy `name`, `value`, `domain`, `path` for the SSO + session cookies into `cookies.json`. The `cookies` schema accepts both Playwright `storage_state` and Cookie-Editor-style arrays.

## Repository Settings

Before inviting contributors or relying on this repository, enable these GitHub
settings:

- Secret scanning and push protection.
- Dependabot alerts and security updates.
- Branch protection for `main`.
- Required status checks for the test workflow.

## Layout

```
auth-scrape/
├── pyproject.toml
├── README.md
├── profiles/
│   ├── confluence.example.yaml
│   ├── notion.example.yaml
│   └── sharepoint.example.yaml
└── src/authscrape/
    ├── cli.py            # argparse dispatcher (`auth-scrape ...`)
    ├── config.py         # YAML profile loader & dataclasses
    ├── cookies.py        # storage_state loader + browser_cookie3 export
    ├── crawler.py        # Playwright BFS, resume, link discovery
    ├── extractor.py      # content selection + markdown conversion
    └── state.py          # visited/queue persistence
```
