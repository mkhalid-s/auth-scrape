"""Resume state — visited URLs, failed URLs, and pending queue.

`visited` records URLs whose markdown was successfully written.
`failed`  records URLs that were fetched but did not produce content
          (auth wall, sub-threshold body, etc.) — these will be RETRIED
          on `--resume` so cookie expiry is recoverable.
Queue items are dicts: {url, budget, matched}. Plain-string entries
from older state files are auto-upgraded.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import TypedDict


SCHEMA_VERSION = 1


class QueueItem(TypedDict):
    url: str
    budget: int
    matched: bool


class State:
    def __init__(self, path: Path):
        self.path = path
        self.visited: set[str] = set()
        self.failed: set[str] = set()
        self.queue: list[QueueItem] = []
        self.started_at: str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.updated_at: str = self.started_at

    @classmethod
    def load_or_new(cls, path: Path) -> "State":
        s = cls(path)
        if not path.exists():
            return s
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            s.visited = set(data.get("visited", []))
            s.failed = set(data.get("failed", []))
            raw_queue = data.get("queue", [])
            s.queue = [_normalize(item) for item in raw_queue]
            s.started_at = data.get("started_at", s.started_at)
        except (json.JSONDecodeError, OSError) as e:
            # Don't silently discard corrupt state — preserve it for forensics
            # and warn loudly. A fresh state means the next --resume will
            # re-crawl everything; the user must know.
            backup = path.with_suffix(path.suffix + f".corrupt-{int(time.time())}")
            try:
                os.replace(path, backup)
                print(
                    f"WARNING: state file {path} was corrupt ({e!s}); "
                    f"backed up to {backup} and starting fresh.",
                    file=sys.stderr,
                )
            except OSError:
                print(
                    f"WARNING: state file {path} was corrupt ({e!s}); "
                    "starting fresh (backup failed).",
                    file=sys.stderr,
                )
        return s

    def save(self) -> None:
        """Write atomically — write to .tmp then rename so a Ctrl-C
        between create and write never leaves a half-written state file."""
        self.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "schema_version": SCHEMA_VERSION,
            "visited": sorted(self.visited),
            "failed": sorted(self.failed),
            "queue": self.queue,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
        }, indent=2)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)


def _normalize(item) -> QueueItem:
    if isinstance(item, str):
        return {"url": item, "budget": 0, "matched": False}
    return {
        "url": item.get("url"),
        "budget": int(item.get("budget", 0)),
        "matched": bool(item.get("matched", False)),
    }


def make_item(url: str, budget: int = 0, matched: bool = False) -> QueueItem:
    return {"url": url, "budget": budget, "matched": matched}
