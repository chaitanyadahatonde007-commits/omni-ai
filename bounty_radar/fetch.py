"""Fetch candidate bounty issues from the GitHub search API.

Uses only the standard library so the tool runs anywhere with Python 3.9+.
Auth is optional but strongly recommended: anonymous search is limited to
10 requests/minute, authenticated is 30.

We deliberately issue a small number of *broad* queries and then rank locally,
rather than many narrow ones — the search rate limit is the real constraint.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from .parse import extract_money
from .rank import Bounty

SEARCH_URL = "https://api.github.com/search/issues"
USER_AGENT = "bounty-radar/0.1 (+https://github.com/chaitanyadahatonde007-commits/omni-ai)"

DEFAULT_QUERIES: list[str] = [
    'label:bounty state:open type:issue',
    'label:"paid" state:open type:issue',
    'label:reward state:open type:issue',
    'label:bounty label:"good first issue" state:open type:issue',
    'in:title bounty in:title "$" state:open type:issue',
    'label:"💰 bounty" state:open type:issue',
]


class GitHubError(RuntimeError):
    """Raised when the GitHub API refuses the request."""


def _token() -> Optional[str]:
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(var)
        if value:
            return value
    return None


def _get(url: str, retries: int = 3) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    last_error: Optional[str] = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            # 403/429 on search = rate limited. Honour Retry-After, else back off.
            if exc.code in (403, 429):
                retry_after = exc.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else 12 * (attempt + 1)
                last_error = f"rate limited ({exc.code}): {body}"
                print(f"  ! rate limited, waiting {wait}s ({attempt + 1}/{retries})",
                      file=sys.stderr)
                time.sleep(min(wait, 60))
                continue
            raise GitHubError(f"HTTP {exc.code} for {url}: {body}") from exc
        except urllib.error.URLError as exc:
            last_error = str(exc)
            time.sleep(3 * (attempt + 1))
    raise GitHubError(f"giving up on {url}: {last_error}")


def search_issues(query: str, per_page: int = 50, max_pages: int = 2) -> Iterable[dict]:
    """Yield raw issue dicts for one search query."""
    for page in range(1, max_pages + 1):
        params = urllib.parse.urlencode({"q": query, "per_page": per_page,
                                         "page": page, "sort": "updated", "order": "desc"})
        payload = _get(f"{SEARCH_URL}?{params}")
        items = payload.get("items", [])
        if not items:
            return
        yield from items
        total = payload.get("total_count", 0)
        if page * per_page >= total or page * per_page >= 1000:
            # GitHub caps result pagination at 1000 items.
            return


def to_bounty(item: dict) -> Optional[Bounty]:
    """Convert a raw search-API issue into a Bounty, or None if unparseable."""
    repo_url = item.get("repository_url", "")
    parts = repo_url.rstrip("/").split("/")
    if len(parts) < 2:
        return None
    owner, repo_name = parts[-2], parts[-1]

    title = item.get("title", "") or ""
    body = item.get("body", "") or ""
    money = extract_money(title) or extract_money(body[:4000])
    if money is None:
        return None

    labels = [l.get("name", "") for l in (item.get("labels") or []) if isinstance(l, dict)]

    return Bounty(
        number=item.get("number", 0),
        title=title,
        url=item.get("html_url", ""),
        repo=f"{owner}/{repo_name}",
        repo_owner=owner,
        labels=labels,
        comments=item.get("comments", 0) or 0,
        created_at=item.get("created_at"),
        updated_at=item.get("updated_at"),
        body_excerpt=body[:500],
        money=money,
        language_hint=_guess_language(labels + [title]),
    )


_LANGUAGE_HINTS = {
    "python": "Python", "rust": "Rust", "typescript": "TypeScript",
    "javascript": "JavaScript", "golang": "Go", "go": "Go", "java": "Java",
    "c++": "C++", "c#": "C#", "ruby": "Ruby", "php": "PHP", "swift": "Swift",
    "kotlin": "Kotlin", "react": "React", "vue": "Vue", "svelte": "Svelte",
    "flutter": "Flutter", "dart": "Dart", "solidity": "Solidity",
    "elixir": "Elixir", "haskell": "Haskell", "zig": "Zig", "css": "CSS",
    "html": "HTML", "docs": "Docs", "documentation": "Docs", "translation": "Docs",
}


def _guess_language(texts: list[str]) -> Optional[str]:
    blob = " ".join(texts).lower()
    for needle, label in _LANGUAGE_HINTS.items():
        if needle in blob:
            return label
    return None


@dataclass
class CollectResult:
    """Outcome of a search run, so callers can tell "nothing found" from "API broke"."""

    bounties: list[Bounty] = field(default_factory=list)
    queries_run: int = 0
    queries_failed: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_failure(self) -> bool:
        """True when every single query errored — i.e. we learned nothing."""
        return self.queries_run > 0 and self.queries_failed == self.queries_run


def collect(
    queries: Optional[list[str]] = None,
    *,
    per_page: int = 50,
    max_pages: int = 2,
    delay: float = 2.5,
    log: Callable[[str], None] = lambda _m: None,
) -> CollectResult:
    """Run the queries and return every parseable Bounty plus run diagnostics.

    Failures are recorded rather than swallowed: an authenticated token that
    has expired looks exactly like "no bounties exist" if you only count
    results, and that distinction is the whole difference between a useful
    tool and a liar.
    """
    queries = queries or DEFAULT_QUERIES
    result = CollectResult()
    for index, query in enumerate(queries):
        if index:
            time.sleep(delay)
        log(f"searching: {query}")
        result.queries_run += 1
        try:
            for item in search_issues(query, per_page=per_page, max_pages=max_pages):
                bounty = to_bounty(item)
                if bounty:
                    result.bounties.append(bounty)
        except GitHubError as exc:
            result.queries_failed += 1
            result.errors.append(f"{query}: {exc}")
            log(f"  ! query failed ({exc})")
    return result
