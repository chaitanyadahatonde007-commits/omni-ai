"""Verify that a bounty's repo has actually paid anyone before you work on it.

This exists because of a concrete failure. The unverified ranking put three
$12-$30 "beginner docs" bounties from `cuentaprueba244w-dotcom/zeroeye` at the
very top. Checking the repo directly showed:

    merged PRs ever : 0
    open PRs        : 114
    last push       : 2026-06-19   (three months stale)
    account created : 2026-06-14

At least seven people had submitted a PR for the same $25 task. Nobody was
merged. Nobody was paid. A later commenter withdrew their attempt for exactly
this reason: *"I can't confirm this bounty has a funded payer behind it."*

Amount, labels and freshness say nothing about whether the payer is real. The
only honest signals are behavioural:

* **merged PRs** — has this repo ever accepted anyone's work?
* **open-to-merged PR ratio** — a pile of open PRs and zero merges is a queue
  that never moves.
* **last push** — a maintainer who vanished months ago is not reviewing PRs.

These cost API calls, so verification is opt-in and applied to the top N
candidates only.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from .rank import Bounty

API = "https://api.github.com"
USER_AGENT = "bounty-radar/0.2 (payer verification)"


@dataclass
class RepoHealth:
    """What we could establish about whether a repo actually ships work."""

    repo: str
    merged_prs: Optional[int] = None
    open_prs: Optional[int] = None
    stars: Optional[int] = None
    pushed_at: Optional[str] = None
    error: Optional[str] = None

    @property
    def days_since_push(self) -> Optional[float]:
        if not self.pushed_at:
            return None
        try:
            pushed = datetime.fromisoformat(self.pushed_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if pushed.tzinfo is None:
            pushed = pushed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - pushed).total_seconds() / 86400.0)

    @property
    def verified_payer(self) -> bool:
        """True only when there is positive, *recent* evidence the repo ships work.

        Two conditions, both required:
        * it has merged at least one PR (someone got their work accepted), and
        * it has been pushed to recently enough that a maintainer would see
          your PR. A repo that merged 40 PRs and then went silent 7 years ago
          is not going to merge yours.
        """
        if self.error is not None:
            return False
        if not self.has_merge_history:
            return False
        return not self.stalled and not self.backlogged

    @property
    def stalled(self) -> bool:
        """True when the repo looks abandoned — no push in 90 days.

        90 rather than 45: plenty of healthy repos go a month or two between
        pushes, and flagging those produced false "STALE" verdicts.
        """
        days = self.days_since_push
        return days is not None and days > 90

    @property
    def backlog_ratio(self) -> Optional[float]:
        """Open PRs per merged PR. High means the review queue never moves."""
        if self.open_prs is None or not self.merged_prs:
            return None
        return self.open_prs / self.merged_prs

    @property
    def backlogged(self) -> bool:
        """True when PRs pile up far faster than they get merged.

        `mergeos-bounties/Loru` has 50 merged and 253 open — a 5:1 ratio.
        People are submitting; the maintainer is not keeping up. Your PR joins
        the pile.
        """
        ratio = self.backlog_ratio
        return ratio is not None and ratio > 3.0 and (self.open_prs or 0) > 20

    @property
    def has_merge_history(self) -> bool:
        """Merged PRs at some point, regardless of whether it's alive now."""
        return bool(self.merged_prs and self.merged_prs > 0)

    @property
    def verdict(self) -> str:
        if self.error:
            return f"unknown ({self.error})"
        parts = [f"{self.merged_prs} merged PR", f"{self.open_prs} open PR"]
        if self.days_since_push is not None:
            parts.append(f"pushed {self.days_since_push:.0f}d ago")
        detail = ", ".join(p for p in parts if "None" not in p)

        if not self.has_merge_history:
            return f"NO EVIDENCE OF PAYMENT ({detail})"
        if self.backlogged:
            return f"BACKLOGGED {self.backlog_ratio:.0f}:1 open:merged ({detail})"
        if self.stalled:
            return f"PAID BEFORE, NOW STALE ({detail})"
        return f"PAID ({detail})"


def _get(url: str, retries: int = 3) -> Optional[dict]:
    """GET with retry. Returns None on hard failure rather than raising."""
    import os

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    for var in ("GITHUB_TOKEN", "GH_TOKEN"):
        token = os.environ.get(var)
        if token:
            headers["Authorization"] = f"Bearer {token}"
            break

    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429):
                retry_after = exc.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else 15
                time.sleep(min(wait, 60))
                continue
            return None
        except urllib.error.URLError:
            time.sleep(3 * (attempt + 1))
    return None


def check_repo(repo: str) -> RepoHealth:
    """Look up one repo's payment track record."""
    health = RepoHealth(repo=repo)

    info = _get(f"{API}/repos/{repo}")
    if info is None:
        health.error = "repo lookup failed"
        return health
    health.stars = info.get("stargazers_count")
    health.pushed_at = info.get("pushed_at")

    owner, _, name = repo.partition("/")
    query = urllib.parse.urlencode({"q": f"repo:{owner}/{name} type:pr is:merged"})
    merged = _get(f"{API}/search/issues?{query}")
    if merged is not None and "total_count" in merged:
        health.merged_prs = merged["total_count"]
    else:
        health.error = "merged-PR lookup failed"

    query = urllib.parse.urlencode({"q": f"repo:{owner}/{name} type:pr is:open"})
    open_prs = _get(f"{API}/search/issues?{query}")
    if open_prs is not None and "total_count" in open_prs:
        health.open_prs = open_prs["total_count"]

    return health


def verify_bounties(
    bounties: list[Bounty],
    *,
    limit: int = 12,
    delay: float = 2.5,
    log: Callable[[str], None] = lambda _m: None,
) -> dict[str, RepoHealth]:
    """Check the distinct repos behind the top `limit` bounties.

    Verification is capped because each repo costs up to three API calls and
    the search endpoint allows 30/minute when authenticated, 10 when not.
    """
    repos: list[str] = []
    for b in bounties:
        if b.repo not in repos:
            repos.append(b.repo)
        if len(repos) >= limit:
            break

    out: dict[str, RepoHealth] = {}
    for index, repo in enumerate(repos):
        if index:
            time.sleep(delay)
        log(f"verifying payer: {repo}")
        health = check_repo(repo)
        out[repo] = health
        log(f"  {health.verdict}")
    return out


def apply_verification(
    bounties: list[Bounty], health: dict[str, RepoHealth]
) -> tuple[list[Bounty], list[Bounty]]:
    """Split into (verified, unverified), preserving rank order.

    Bounties whose repo was never checked are treated as unverified — absence
    of evidence is not evidence of a payer.
    """
    good: list[Bounty] = []
    bad: list[Bounty] = []
    for b in bounties:
        h = health.get(b.repo)
        if h is not None and h.verified_payer:
            good.append(b)
        else:
            bad.append(b)
    return good, bad
