# Contributing

Thanks for helping improve `auth-scrape`. Keep changes small, tested, and safe
for public review.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,host-cookies]'
auth-scrape setup
```

If you only need unit tests, Playwright browser installation is usually not
required.

## Test And Build

```bash
pytest
pytest --cov=authscrape
python -m build --sdist --wheel
```

Run focused tests while developing, then the full suite before opening a pull
request.

## Safe Test Data

Do not add real customer, employer, tenant, or private documentation URLs. Use
`example.com`, `*.test`, or clearly synthetic domains in tests and bundled
profiles.

Do not commit:

- `cookies.json` or browser cookie exports.
- Playwright storage-state files.
- Scraped markdown output.
- Private documentation, screenshots, or copied page content.

When adding profile examples, keep them templated and generic. Prefer names like
`TENANT`, `SPACE`, `WORKSPACE_ID`, and `SITE` over real identifiers.

## Code Style

Follow the existing straightforward Python style. Prefer focused functions,
explicit tests for CLI behavior, and clear error messages over broad refactors.
