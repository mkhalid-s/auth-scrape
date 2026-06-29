"""auth-scrape: crawl auth-walled sites via your browser session.

Public library API. Stable surface intended for downstream consumers
(RAG pipelines and private tooling). Non-exported names are implementation details.
"""
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from .config import (
    AuthConfig,
    CrawlConfig,
    ExtractConfig,
    FocusConfig,
    OutputConfig,
    Profile,
    ProfileError,
    SearchConfig,
    find_profile,
    list_profiles,
    load_profile,
)
from .crawler import combine, crawl, search_only
from .fetcher import FetchResult, Fetcher, HttpxFetcher, PlaywrightFetcher

try:
    __version__ = _pkg_version("auth-scrape")
except PackageNotFoundError:
    # Package not installed (e.g. running from a source tree without
    # `pip install -e .`). Fall back to a static version.
    __version__ = "0.1.0"

__all__ = [
    "__version__",
    # config
    "Profile",
    "ProfileError",
    "CrawlConfig",
    "AuthConfig",
    "ExtractConfig",
    "OutputConfig",
    "SearchConfig",
    "FocusConfig",
    "load_profile",
    "find_profile",
    "list_profiles",
    # crawler
    "crawl",
    "combine",
    "search_only",
    # fetcher
    "Fetcher",
    "FetchResult",
    "PlaywrightFetcher",
    "HttpxFetcher",
]
