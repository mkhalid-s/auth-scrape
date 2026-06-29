"""Profile scaffolding — `auth-scrape init`.

Generates a profile YAML from a seed URL plus optional flags, deriving
sensible defaults for `allow_prefixes`, `cookie_domains`, and the output
directory. The user can then `auth-scrape doctor` to verify, edit by hand
to enable focus/search blocks, and run.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse


def _registrable_domain(host: str) -> str:
    """Return the last two dot-separated labels of a hostname.

    `docs.staging.example.net` -> `example.net`
    `example.com`              -> `example.com`
    `localhost`                -> `localhost`

    Pure heuristic — handles the common case. Won't get co.uk / com.au
    right; that needs the public suffix list which we won't pull in for
    this. If a user is on a 2-label TLD they can edit the YAML.
    """
    if not host:
        return host
    parts = host.lower().split(".")
    if len(parts) < 2:
        return host
    return ".".join(parts[-2:])


def _allow_prefix_from_seed(seed: str) -> str:
    """Derive a path-prefix allow rule from a seed URL.

    Strategy: take the URL's directory (everything up to the last `/`).
    `https://docs.x.com/private/project/page` -> `https://docs.x.com/private/project/`
    `https://docs.x.com/private/project/`     -> `https://docs.x.com/private/project/`
    `https://docs.x.com/`                     -> `https://docs.x.com/`
    """
    parsed = urlparse(seed)
    path = parsed.path
    if not path or path == "/":
        return f"{parsed.scheme}://{parsed.netloc}/"
    if path.endswith("/"):
        prefix_path = path
    else:
        # Trim to the last directory component.
        prefix_path = path.rsplit("/", 1)[0] + "/"
    return f"{parsed.scheme}://{parsed.netloc}{prefix_path}"


def _yaml_string(s: str) -> str:
    """Quote a string for YAML if it contains special chars; else leave bare."""
    if not s:
        return '""'
    if any(c in s for c in ":#&*!|>'\"%@`{}[],"):
        # Use double quotes and escape any embedded double quotes.
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def render_profile_yaml(
    *,
    name: str,
    site: str,
    description: str = "",
    keywords: list[str] | None = None,
    cookie_domains: list[str] | None = None,
    max_pages: int = 300,
    delay_seconds: float = 1.5,
) -> str:
    """Render a profile YAML string from the given inputs.

    Pure function — no I/O. Returns the YAML text the caller can write or
    print.
    """
    parsed = urlparse(site)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"--site must be a full URL (got: {site!r})")
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"--site must be http(s) (got scheme: {parsed.scheme!r})")

    host = parsed.netloc.split(":")[0]
    allow_prefix = _allow_prefix_from_seed(site)
    derived_cookie_domain = _registrable_domain(host)

    # Default cookie domains: the registrable domain of the seed plus common
    # SSO providers. The user almost always wants Okta in the mix.
    if cookie_domains is None:
        cookie_domains = sorted({
            derived_cookie_domain,
            "okta.com",
            "oktapreview.com",
        })

    desc = description or f"Generated profile for {host}"

    lines = [
        f"name: {_yaml_string(name)}",
        f"description: {_yaml_string(desc)}",
        "",
        "seeds:",
        f"  - {site}",
        "",
        "crawl:",
        "  # Path-prefix scoping keeps the crawl inside the seed's directory.",
        "  # Add allow_hosts only if the docs span multiple sibling paths.",
        "  allow_hosts: []",
        "  allow_prefixes:",
        f"    - {allow_prefix}",
        "  deny_prefixes:",
        f"    - {parsed.scheme}://{parsed.netloc}/login",
        f"    - {parsed.scheme}://{parsed.netloc}/signin",
        f"  max_pages: {max_pages}",
        f"  delay_seconds: {delay_seconds}",
        "",
        "auth:",
        "  # Cookies whose domain contains any of these substrings will be",
        "  # included when running `auth-scrape cookies`.",
        "  cookie_domains:",
    ]
    for d in cookie_domains:
        lines.append(f"    - {d}")
    lines.append("")
    lines.append("extract:")
    lines.append("  strip_inline_svg: true")
    lines.append("  strip_data_uri_images: true")
    lines.append("")

    if keywords:
        lines.append("# Focused crawl: only save pages matching these keywords.")
        lines.append("focus:")
        lines.append("  keywords:")
        for k in keywords:
            lines.append(f"    - {_yaml_string(k)}")
        lines.append("  min_score: 1.0")
        lines.append("  drilldown_depth: 1")
        lines.append("  save: matched_only")
    else:
        lines.append("# Optional — focused crawl. Uncomment to keep only pages")
        lines.append("# whose title/headings/body contain a keyword.")
        lines.append("# focus:")
        lines.append("#   keywords:")
        lines.append("#     - your-keyword")
        lines.append("#   min_score: 1.0")
        lines.append("#   drilldown_depth: 1")
        lines.append("#   save: matched_only")
    lines.append("")

    lines.append("# Optional — search-driven seed harvest. Tune `result_selector`")
    lines.append("# once with: auth-scrape search <profile> --headed")
    lines.append("# search:")
    lines.append(f"#   url_template: \"{parsed.scheme}://{parsed.netloc}/search?q={{query}}\"")
    lines.append("#   result_selector: \"a.search-result\"")
    lines.append("#   queries:")
    lines.append("#     - your-query")
    lines.append("#   max_results_per_query: 25")
    lines.append("")

    lines.append("output:")
    lines.append(f"  dir: output/{name}")
    lines.append(f"  combined: {name}.md")
    lines.append("")
    return "\n".join(lines)


def default_profile_dir() -> Path:
    """Default location for user-created profiles."""
    # Honor XDG_CONFIG_HOME on Linux; fall back to ~/.auth-scrape elsewhere.
    import os
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "auth-scrape" / "profiles"
    return Path.home() / ".auth-scrape" / "profiles"


_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_\-]*$")


def validate_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Invalid profile name {name!r}. Must start with a letter and "
            "contain only letters, digits, hyphens, and underscores."
        )


def write_profile(
    *,
    name: str,
    yaml_text: str,
    out_path: Path | None = None,
    force: bool = False,
) -> Path:
    """Write the rendered YAML to disk. Returns the resolved path.

    Refuses to overwrite an existing file unless force=True.
    """
    if out_path is None:
        out_path = default_profile_dir() / f"{name}.yaml"
    out_path = Path(out_path)
    if out_path.exists() and not force:
        raise FileExistsError(
            f"Profile already exists at {out_path}. Use --force to overwrite."
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text, encoding="utf-8")
    return out_path
