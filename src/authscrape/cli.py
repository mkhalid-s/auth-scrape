"""auth-scrape CLI: list, cookies, run, combine, search, init, doctor."""
from __future__ import annotations

import argparse
import sys
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

from .config import Profile, find_profile, list_profiles, load_profile
from .cookies import export_from_browser
from .crawler import combine, crawl, search_only


def _bundled_profiles_dir() -> Path:
    """Path to bundled profiles inside the installed package.

    Works for both editable installs (`pip install -e .`) and wheel installs
    because the YAMLs live under `src/authscrape/profiles/` and ship as
    package data via pyproject.toml's `[tool.setuptools.package-data]`.
    """
    return Path(__file__).resolve().parent / "profiles"


def _user_profiles_dir() -> Path:
    """Per-user profile dir; honors XDG_CONFIG_HOME on Linux."""
    import os
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "auth-scrape" / "profiles"
    return Path.home() / ".auth-scrape" / "profiles"


def _profile_search_dirs() -> list[Path]:
    """Search precedence (first match wins):

    1. ./profiles/         — project-local overrides
    2. <package>/profiles/ — bundled (ships with the wheel)
    3. ~/.auth-scrape/...  — per-user
    """
    return [
        Path.cwd() / "profiles",
        _bundled_profiles_dir(),
        _user_profiles_dir(),
    ]


def _resolve_profile(name_or_path: str) -> Profile:
    """Accepts either a profile name (looked up on the search path) OR an
    absolute/relative path to a .yaml file. The path-form lets users hand
    a one-off external profile to any subcommand without copying it
    anywhere — useful for testing and for shared/team profiles in git."""
    path = find_profile(name_or_path, _profile_search_dirs())
    return load_profile(path)


def _get_version() -> str:
    try:
        return _pkg_version("auth-scrape")
    except PackageNotFoundError:
        from . import __version__
        return __version__


# ---------- subcommands ----------

def _cmd_list(args) -> int:
    rows = []
    for path in list_profiles(_profile_search_dirs()):
        try:
            prof = load_profile(path)
            rows.append((prof.name, prof.description or "", str(path)))
        except Exception as e:
            rows.append((path.stem, f"(invalid: {e})", str(path)))
    if not rows:
        print(
            "No profiles found.\n"
            "Create one: auth-scrape init <name> --site <url>\n"
            "Or drop a YAML in: ./profiles/, the package, or ~/.auth-scrape/profiles/"
        )
        return 0
    name_w = max(len(r[0]) for r in rows)
    for name, desc, path in rows:
        print(f"{name:<{name_w}}  {desc}")
        print(f"{'':<{name_w}}  {path}")
    return 0


def _cmd_cookies(args) -> int:
    profile = _resolve_profile(args.profile)
    domains = profile.auth.cookie_domains
    if not domains:
        print(
            f"Profile '{profile.name}' has no auth.cookie_domains; "
            "exporting all cookies (no filter).",
            file=sys.stderr,
        )
    out = Path(args.out)
    n = export_from_browser(domains, out, browser=args.browser)
    print(f"Wrote {n} cookies to {out}", file=sys.stderr)
    return 0


def _cmd_run(args) -> int:
    profile = _resolve_profile(args.profile)
    cookies_path = Path(args.cookies)
    if not cookies_path.exists():
        print(
            f"Cookie file not found: {cookies_path}\n"
            f"Run:  auth-scrape cookies {profile.name}",
            file=sys.stderr,
        )
        return 1
    out_dir = Path(args.out or profile.output.dir)
    state_path = Path(args.state or out_dir / "state.json")
    n = crawl(
        profile,
        cookies_path,
        out_dir=out_dir,
        state_path=state_path,
        resume=args.resume,
        headed=args.headed,
        no_crawl=args.no_crawl,
        max_pages=args.max_pages,
    )
    return 0 if n > 0 else 1


def _cmd_combine(args) -> int:
    profile = _resolve_profile(args.profile)
    out_dir = Path(args.out or profile.output.dir)
    combined_name = args.name or profile.output.combined or "combined.md"
    path = combine(out_dir, combined_name)
    print(f"Wrote {path}")
    return 0


def _cmd_search(args) -> int:
    profile = _resolve_profile(args.profile)
    if not profile.search.url_template or not profile.search.queries:
        print(
            f"Profile '{profile.name}' has no `search` block "
            "(url_template + queries). Nothing to do.",
            file=sys.stderr,
        )
        return 1
    cookies_path = Path(args.cookies)
    if not cookies_path.exists():
        print(
            f"Cookie file not found: {cookies_path}\n"
            f"Run:  auth-scrape cookies {profile.name}",
            file=sys.stderr,
        )
        return 1
    urls = search_only(profile, cookies_path, headed=args.headed)
    print(f"\nHarvested {len(urls)} URL(s):")
    for u in urls:
        print(f"  {u}")
    return 0 if urls else 1


def _cmd_init(args) -> int:
    """Create a new profile YAML from a seed URL."""
    from .scaffold import (
        default_profile_dir,
        render_profile_yaml,
        validate_name,
        write_profile,
    )

    try:
        validate_name(args.name)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    site = args.site
    if not site:
        site = input("Site URL (e.g. https://docs.example.com/foo/): ").strip()
        if not site:
            print("error: --site is required", file=sys.stderr)
            return 2

    keywords: list[str] | None = None
    if args.keywords:
        keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]

    cookie_domains: list[str] | None = None
    if args.cookie_domains:
        cookie_domains = [d.strip() for d in args.cookie_domains.split(",") if d.strip()]

    try:
        yaml_text = render_profile_yaml(
            name=args.name,
            site=site,
            description=args.description or "",
            keywords=keywords,
            cookie_domains=cookie_domains,
            max_pages=args.max_pages,
            delay_seconds=args.delay,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if args.print:
        sys.stdout.write(yaml_text)
        return 0

    out_path = Path(args.out) if args.out else default_profile_dir() / f"{args.name}.yaml"
    try:
        path = write_profile(
            name=args.name,
            yaml_text=yaml_text,
            out_path=out_path,
            force=args.force,
        )
    except FileExistsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    # Validate by re-loading; surfaces any rendering bugs immediately.
    try:
        prof = load_profile(path)
    except Exception as e:
        print(f"warning: profile written but failed to parse: {e}", file=sys.stderr)
        return 1

    print(f"Created profile '{prof.name}' at {path}\n")
    print(f"  seeds:           {', '.join(prof.seeds)}")
    if prof.crawl.allow_prefixes:
        print(f"  allow_prefixes:  {', '.join(prof.crawl.allow_prefixes)}")
    if prof.auth.cookie_domains:
        print(f"  cookie_domains:  {', '.join(prof.auth.cookie_domains)}")
    if prof.focus.enabled:
        print(f"  focus keywords:  {', '.join(prof.focus.keywords)}")
    print()
    print("Next steps:")
    print("  1. auth-scrape doctor")
    print(f"  2. auth-scrape cookies {prof.name}")
    print(f"  3. auth-scrape run {prof.name} --max-pages 5 --headed   # smoke test")
    print(f"  4. auth-scrape run {prof.name}")
    return 0


def _cmd_doctor(args) -> int:
    """Run environment diagnostics."""
    from .doctor import run_doctor
    cookies_path = Path(args.cookies)
    return run_doctor(cookies_path, _profile_search_dirs())


def _cmd_setup(args) -> int:
    """One-shot post-install bootstrap: install Chromium, verify environment.

    Designed so the install story is exactly two commands:
        pipx install 'auth-scrape[host-cookies]'
        auth-scrape setup
    """
    import subprocess

    print("auth-scrape setup")
    print("=" * 50)

    # 1. Install Chromium via Playwright. We invoke `python -m playwright`
    #    instead of the bare `playwright` CLI so this works inside a pipx
    #    venv (where `playwright` isn't on PATH but is importable).
    print("\n[1/3] Installing Chromium browser...")
    print("      (this downloads ~150MB; one-time)")
    rc = subprocess.call(
        [sys.executable, "-m", "playwright", "install", "chromium"]
    )
    if rc != 0:
        print(
            "\nerror: `playwright install chromium` failed.\n"
            "Diagnose with: python -m playwright install chromium",
            file=sys.stderr,
        )
        return rc

    # 2. System libs — Linux only. Chromium needs libnss/libatk/etc. and
    #    `playwright install-deps` is the canonical way to get them. Needs
    #    sudo on most distros.
    if sys.platform.startswith("linux") and not args.skip_system_deps:
        print("\n[2/3] Installing Linux system libraries for Chromium...")
        print("      (libnss3, libatk-bridge, libgbm, etc. — may need sudo)")
        # Try unprivileged first; fall through to sudo if it fails.
        rc = subprocess.call(
            [sys.executable, "-m", "playwright", "install-deps", "chromium"]
        )
        if rc != 0:
            print("      Retrying with sudo...")
            rc = subprocess.call(
                ["sudo", sys.executable, "-m", "playwright",
                 "install-deps", "chromium"]
            )
        if rc != 0:
            print(
                "\nwarning: install-deps did not complete. If Chromium fails "
                "to launch, run manually:\n"
                "  sudo " + sys.executable + " -m playwright install-deps chromium",
                file=sys.stderr,
            )
    else:
        reason = "not Linux" if not sys.platform.startswith("linux") \
            else "--skip-system-deps"
        print(f"\n[2/3] Skipping system deps ({reason}).")

    # 3. Verify with the same diagnostics that `auth-scrape doctor` runs.
    print("\n[3/3] Running auth-scrape doctor to verify...\n")
    from .doctor import run_doctor
    rc = run_doctor(Path(args.cookies), _profile_search_dirs())

    if rc <= 1:
        # rc 0 = all green; rc 1 = warnings only (e.g. cookies not yet exported,
        # which is expected on first install).
        print("\nSetup complete. Next steps:")
        print("  auth-scrape init <name> --site <url>     # create a profile")
        print("  auth-scrape cookies <name>               # export browser cookies")
        print("  auth-scrape run <name>                   # crawl")
    return rc


# ---------- main ----------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="auth-scrape",
        description="Crawl auth-walled sites via your browser session.",
    )
    ap.add_argument(
        "--version", "-V", action="version",
        version=f"%(prog)s {_get_version()}",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List available profiles.")
    p_list.set_defaults(func=_cmd_list)

    p_doctor = sub.add_parser(
        "doctor", help="Check environment, profiles, and cookies; print a report.",
    )
    p_doctor.add_argument("--cookies", default="cookies.json")
    p_doctor.set_defaults(func=_cmd_doctor)

    p_setup = sub.add_parser(
        "setup",
        help="One-shot post-install bootstrap: install Chromium + verify.",
    )
    p_setup.add_argument(
        "--cookies", default="cookies.json",
        help="Cookie file checked at the verify step (default: cookies.json).",
    )
    p_setup.add_argument(
        "--skip-system-deps", action="store_true",
        help="Skip `playwright install-deps` on Linux (saves a sudo prompt).",
    )
    p_setup.set_defaults(func=_cmd_setup)

    p_init = sub.add_parser(
        "init", help="Create a new profile YAML from a seed URL.",
    )
    p_init.add_argument("name", help="Profile name (letters, digits, _, -).")
    p_init.add_argument("--site", help="Seed URL (https://...). Prompted if omitted.")
    p_init.add_argument("--description", help="Optional description.")
    p_init.add_argument(
        "--keywords",
        help="Comma-separated focus keywords. If set, a focus block is enabled.",
    )
    p_init.add_argument(
        "--cookie-domains",
        help="Comma-separated cookie-domain filter. Defaults to "
             "registrable-domain-of-site + okta.com + oktapreview.com.",
    )
    p_init.add_argument("--max-pages", type=int, default=300)
    p_init.add_argument("--delay", type=float, default=1.5,
                        help="Seconds between requests (default 1.5).")
    p_init.add_argument(
        "--out",
        help=f"Output path. Default: ~/.auth-scrape/profiles/<name>.yaml",
    )
    p_init.add_argument("--print", action="store_true",
                        help="Print YAML to stdout instead of writing.")
    p_init.add_argument("--force", action="store_true",
                        help="Overwrite an existing profile.")
    p_init.set_defaults(func=_cmd_init)

    p_cook = sub.add_parser(
        "cookies", help="Export cookies from your host browser.",
    )
    p_cook.add_argument("profile", help="Profile name or YAML path.")
    p_cook.add_argument(
        "--browser",
        default="auto",
        choices=["auto", "chrome", "edge", "firefox", "brave", "chromium", "opera", "safari"],
    )
    p_cook.add_argument("--out", default="cookies.json")
    p_cook.set_defaults(func=_cmd_cookies)

    p_run = sub.add_parser("run", help="Crawl using a profile.")
    p_run.add_argument("profile", help="Profile name or YAML path.")
    p_run.add_argument("--cookies", default="cookies.json")
    p_run.add_argument("--out", help="Override output dir from profile.")
    p_run.add_argument("--state", help="Override state file path.")
    p_run.add_argument("--max-pages", type=int, help="Override page cap.")
    p_run.add_argument("--resume", action="store_true",
                       help="Continue from a previous crawl's state file.")
    p_run.add_argument("--no-crawl", action="store_true",
                       help="Fetch only seeds; don't follow links.")
    p_run.add_argument("--headed", action="store_true",
                       help="Show the browser (debug auth).")
    p_run.set_defaults(func=_cmd_run)

    p_comb = sub.add_parser(
        "combine", help="Concatenate scraped pages into one markdown file.",
    )
    p_comb.add_argument("profile", help="Profile name or YAML path.")
    p_comb.add_argument("--out", help="Output dir (default: from profile).")
    p_comb.add_argument("--name", help="Combined filename (default: from profile).")
    p_comb.set_defaults(func=_cmd_combine)

    p_search = sub.add_parser(
        "search", help="Run a profile's search queries; print harvested URLs.",
    )
    p_search.add_argument("profile", help="Profile name or YAML path.")
    p_search.add_argument("--cookies", default="cookies.json")
    p_search.add_argument("--headed", action="store_true")
    p_search.set_defaults(func=_cmd_search)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
