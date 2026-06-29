# Security Policy

## Supported Versions

Security fixes are provided for the latest released version of `auth-scrape`.
If you are running from source, update to the latest `main` before reporting an
issue so we can rule out already-fixed problems.

## Reporting A Vulnerability

Please do not open a public issue for suspected security vulnerabilities. Use
GitHub Security Advisories for this repository, or contact the maintainer
privately through GitHub if advisories are unavailable.

Include enough detail to reproduce the issue, but do not include live cookies,
private documentation, crawl output, bearer tokens, API keys, or other secrets.
Synthetic examples using `example.com` are preferred.

## Sensitive Data Handling

`auth-scrape` works with authenticated browser sessions. Treat these files as
secrets:

- `cookies.json` and any browser cookie export.
- Playwright `storage_state` files.
- Files under `output/` and `state/`.
- Combined markdown files produced from private sites.

Never commit or share those files unless you have reviewed and sanitized them.
The repository `.gitignore` excludes the common local artifacts, but users are
responsible for checking their own generated files before publishing.
