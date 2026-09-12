"""Turn raw GitHub issue search hits into a ranked, de-spammed bounty list.

The single biggest problem with "search GitHub for bounties" is that the raw
results are dominated by bot-generated noise. This module scores each issue on
three things that actually decide whether *you* can win it:

1. **Reward** — how much it pays, in USD where we can tell.
2. **Competition** — how many people are already arguing in the comments.
3. **Accessibility** — is it tagged beginner-friendly, is the repo alive.

The output is deliberately conservative: an unclaimed $200 issue in an active
repo beats a $5,000 issue with 40 comments and 12 duplicate PRs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .parse import Money

# Titles that come off an assembly line rather than a human maintainer.
_SPAM_TITLE_PATTERNS = [
    re.compile(r"\[radar\]", re.IGNORECASE),
    re.compile(r"^\s*\[?auto", re.IGNORECASE),
    re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}"),          # ISO timestamp in title
    re.compile(r"^\s*(sync|mirror|snapshot)\b", re.IGNORECASE),
    re.compile(r"^\s*\[\s*\]\s*$"),
    re.compile(r"^\s*test\s", re.IGNORECASE),
    # --- bounty *aggregator* bots: these link to bounties, they are not one ---
    re.compile(r"bounty\s*alert", re.IGNORECASE),
    re.compile(r"opportunit(y|ies)\s+found", re.IGNORECASE),
    re.compile(r"\b\d+\s+new\s+opportunit", re.IGNORECASE),
    re.compile(r"(daily|weekly)\s+(bounty\s+)?(digest|roundup|round-up)", re.IGNORECASE),
    re.compile(r"^\s*\[?bounty\s*(scout|bot|tracker|radar|hunter)", re.IGNORECASE),
]

# Repos that only exist to re-post other people's bounties.
_SPAM_REPO_PATTERNS = [
    re.compile(r"bountyscout", re.IGNORECASE),
    re.compile(r"bounty[-_]?(bot|alert|tracker|radar|hunter|feed|list)", re.IGNORECASE),
]

# Issues that are about money *already owed*, not money you can go earn.
_NOT_CLAIMABLE_PATTERNS = [
    re.compile(r"payout\s+request", re.IGNORECASE),
    re.compile(r"bounty\s+claim", re.IGNORECASE),
    re.compile(r"consolidated\s+.*\bclaim\b", re.IGNORECASE),
    re.compile(r"\bpaid\s+out\b", re.IGNORECASE),
    re.compile(r"invoice\s+for", re.IGNORECASE),
    re.compile(r"^\s*\[?\s*(paid|completed|done|merged)\s*\]", re.IGNORECASE),
    re.compile(r"meeting\s+facilitation", re.IGNORECASE),
    re.compile(r"\bproposal\b.*\breward\b|\breward\b.*\bproposal\b", re.IGNORECASE),
]

# Disclaimers an author writes when the number is a *wish*, not an offer.
# Checked against the body, because that is where maintainers put the caveat.
_DISCLAIMER_PATTERNS = [
    re.compile(r"not\s+a\s+funded\s+offer", re.IGNORECASE),
    re.compile(r"bounty\s+proposal", re.IGNORECASE),
    re.compile(r"proposed\s+(bounty|reward|payout)", re.IGNORECASE),
    re.compile(r"requested\s+reward", re.IGNORECASE),
    re.compile(r"awaiting\s+(maintainer\s+)?approval", re.IGNORECASE),
    # "Proposed US$25 CLI docs bounty" — leading adjective form. The earlier
    # `proposed\s+(bounty|reward|payout)` missed it because a currency sat
    # between the two words.
    re.compile(r"^\s*proposed\b", re.IGNORECASE),
    re.compile(r"\bthis\s+proposal\b", re.IGNORECASE),
    re.compile(r"\bproposal\b[^.]{0,60}\b(approve|approval|accept)\w*\b", re.IGNORECASE),
    re.compile(r"would\s+you\s+approve", re.IGNORECASE),
    re.compile(r"(pay|paid|reward)\w*\s+(me\s+)?after\s+(acceptance|merge|approval)",
               re.IGNORECASE),
    re.compile(r"i\s+(would|could)\s+(like|love)\s+to\s+be\s+paid", re.IGNORECASE),
    re.compile(r"no\s+budget", re.IGNORECASE),
    re.compile(r"unpaid\s+volunteer", re.IGNORECASE),
    re.compile(r"if\s+(i\s+)?get\s+approved", re.IGNORECASE),
    # Test / joke / retracted issues. Found in the wild:
    # "[Bounty: $300] Salesforce integration" -> "Please disregard this issue".
    re.compile(r"please\s+disregard", re.IGNORECASE),
    re.compile(r"disregard\s+this\s+issue", re.IGNORECASE),
    re.compile(r"ignore\s+this\s+issue", re.IGNORECASE),
    re.compile(r"note\s+for\s+humans", re.IGNORECASE),
    re.compile(r"this\s+is\s+(just\s+)?a\s+(test|joke|joke\s+issue)\b", re.IGNORECASE),
    re.compile(r"not\s+a\s+real\s+(issue|bounty|task)", re.IGNORECASE),
    re.compile(r"^\s*(test|joke|dummy|placeholder)\s*issue\b", re.IGNORECASE | re.MULTILINE),
]

# The biggest false-positive class: the issue is written by a *would-be
# contributor* applying for a bounty, not by a maintainer offering one.
# Found live: "I would like to claim the ZH translation variant...",
# "I'm writing to express my strong interest in the $700 Superteam bounty",
# "I would like to work on the Chinese Documentation Translation bounty".
# Showing these is worse than useless — it is literally the competition.
_APPLICATION_PATTERNS = [
    re.compile(r"i\s+would\s+like\s+to\s+(claim|work\s+on|take|start|apply|"
               r"contribute|help|pick\s+this|submit)", re.IGNORECASE),
    re.compile(r"i'?d\s+like\s+to\s+(claim|work\s+on|take|apply|start)", re.IGNORECASE),
    re.compile(r"i'?m\s+writing\s+to\s+express", re.IGNORECASE),
    re.compile(r"express(?:ing)?\s+(?:my\s+)?(?:strong\s+)?interest", re.IGNORECASE),
    re.compile(r"i\s+am\s+interested\s+in\s+(this|the|claiming|working)", re.IGNORECASE),
    re.compile(r"i\s+want\s+to\s+(claim|work\s+on|take)\s+(this|the)", re.IGNORECASE),
    re.compile(r"\bclaiming\s+(this|the)\b", re.IGNORECASE),
    re.compile(r"\bapplying\s+for\b", re.IGNORECASE),
    re.compile(r"bounty\s+application", re.IGNORECASE),
    re.compile(r"^\s*(claim|application|application\s+for)\s*[:\-]",
               re.IGNORECASE | re.MULTILINE),
    re.compile(r"i\s+am\s+a\s+[\w\s]{0,40}(developer|engineer|writer|translator)\s+"
               r"with\s+experience", re.IGNORECASE),
    re.compile(r"could\s+(the\s+)?maintainers?\s+(confirm|approve|clarify|verify|"
               r"let\s+me\s+know)", re.IGNORECASE),
    re.compile(r"before\s+i\s+start\b", re.IGNORECASE),
    re.compile(r"please\s+assign\s+(this|it|me)", re.IGNORECASE),
    re.compile(r"i\s+have\s+(already\s+)?(started|begun)\s+work(?:ing)?\s+on", re.IGNORECASE),
]

# Repo names that betray a bounty *aggregator* rather than a real project.
_AGGREGATOR_REPO_RE = re.compile(
    r"bounty|bounties|plaza|scout|alert|radar|hunter|tracker|aggregat|"
    r"bountyboard|bounty[-_]?feed|bounty[-_]?list",
    re.IGNORECASE,
)
# How many hits from one such repo before we treat the whole repo as a mirror.
_AGGREGATOR_MIN_HITS = 3

_ACCESSIBLE_LABELS = {
    "good first issue", "good-first-issue", "help wanted", "helpwanted",
    "beginner", "beginner friendly", "easy", "first issue", "easy fix",
    "up-for-grabs", "up for grabs",
}

_HARD_LABELS = {
    "expert", "hard", "complex", "architecture", "security", "p0", "critical",
    "blocked", "needs design", "rfc",
}

# Work that a beginner can realistically land without knowing the codebase.
# Docs and translation bounties pay the least ($25-$150) but have by far the
# highest merge rate, which is what builds the profile that pays later.
_DOCS_WORK_RE = re.compile(
    r"\b(docs?|documentation|readme|readme\.md|translat\w*|i18n|l10n|"
    r"localis\w*|localiz\w*|typo|typos|tutorial|quickstart|quick-start|"
    r"guide|guides|comment|comments|docstring|changelog|copy\s?edit|"
    r"proofread|serbian|indonesian|japanese|spanish|french|german|hindi|"
    r"portuguese|korean|chinese|arabic|language)\b",
    re.IGNORECASE,
)


@dataclass
class Bounty:
    """One candidate bounty, enriched with the signals we rank on."""

    number: int
    title: str
    url: str
    repo: str
    repo_owner: str
    labels: list[str] = field(default_factory=list)
    comments: int = 0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    body_excerpt: str = ""
    money: Optional[Money] = None
    language_hint: Optional[str] = None

    # --- derived ------------------------------------------------------------
    @property
    def labels_lower(self) -> set[str]:
        return {l.strip().lower() for l in self.labels}

    @property
    def is_accessible(self) -> bool:
        if self.labels_lower & _ACCESSIBLE_LABELS:
            return True
        # Some maintainers tag difficulty in the title instead: "[easy]", "(beginner)"
        return bool(re.search(r"[\[\(]\s*(easy|beginner|good first issue|simple)\s*[\]\)]",
                              self.title, re.IGNORECASE))

    @property
    def is_hard(self) -> bool:
        # Substring match, not set membership: repos write "level: hard",
        # "difficulty/hard", "priority: critical" — none of which equal "hard".
        return any(keyword in label
                   for label in self.labels_lower
                   for keyword in _HARD_LABELS)

    @property
    def is_docs_work(self) -> bool:
        """True for docs/translation work a beginner can land without codebase depth.

        Deliberately excludes anything also flagged `is_hard` — a "docs" issue
        that is labelled `expert` or `security` is not a beginner task no
        matter how friendly the title sounds.
        """
        if self.is_hard:
            return False
        # NOTE: "good first issue" is deliberately NOT in this set. It means
        # beginner-friendly, not documentation — maintainers slap it on code
        # tasks too, and treating it as docs work produced false positives
        # like "[Bounty $600] Add Thursday's Boots".
        if self.labels_lower & {"documentation", "docs", "doc", "translation",
                                "i18n", "l10n", "localization", "translations",
                                "translate", "content", "writing"}:
            return True
        return bool(_DOCS_WORK_RE.search(self.title))

    @property
    def is_application(self) -> bool:
        """True when the issue is someone *applying* for a bounty, not offering one."""
        haystack = f"{self.title}\n{self.body_excerpt}"
        return any(p.search(haystack) for p in _APPLICATION_PATTERNS)

    @property
    def is_claimable(self) -> bool:
        """False for issues about money already owed — or money only *hoped* for.

        A "bounty proposal" is someone asking to be paid, not an offer you can
        claim. Those waste an afternoon, so they are filtered out by default.
        """
        if any(p.search(self.title) for p in _NOT_CLAIMABLE_PATTERNS):
            return False
        haystack = f"{self.title}\n{self.body_excerpt}"
        if any(p.search(haystack) for p in _DISCLAIMER_PATTERNS):
            return False
        return not self.is_application

    @property
    def looks_spammy(self) -> bool:
        if any(p.search(self.title) for p in _SPAM_TITLE_PATTERNS):
            return True
        if any(p.search(self.repo) for p in _SPAM_REPO_PATTERNS):
            return True
        owner = self.repo_owner.lower()
        if owner.endswith("[bot]") or "-bot" in owner:
            return True
        # A bounty issue with essentially no description is almost always noise.
        if len(self.body_excerpt.strip()) < 40 and self.money is None:
            return True
        return False

    @property
    def age_days(self) -> Optional[float]:
        if not self.created_at:
            return None
        try:
            created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError:
            return None
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - created).total_seconds() / 86400.0)

    def score(self) -> float:
        """Ranking score. Higher is better.

        Formula (documented so you can argue with it):

            score = reward * access * freshness / (1 + 0.35 * comments)

        * `reward` is the USD estimate, log-compressed so a $5,000 bounty
          doesn't completely drown out a realistic $150 one.
        * `access` is 1.3x for beginner-friendly, 0.6x for expert-only.
        * `freshness` decays a bounty's appeal over ~90 days; stale issues are
          usually stale for a reason.
        * `comments` is the competition proxy. 40 comments means 40 people
          already tried.
        """
        usd = self.money.usd_estimate if self.money else None
        if usd is None:
            reward = 1.0          # crypto / unknown: ranked on merit, not money
        else:
            reward = 1.0 + (usd ** 0.5) / 3.0

        access = 1.3 if self.is_accessible else (0.6 if self.is_hard else 1.0)

        age = self.age_days
        if age is None:
            freshness = 0.8
        else:
            freshness = max(0.25, 1.0 - (age / 90.0) * 0.5)

        competition = 1.0 + 0.35 * self.comments

        return round((reward * access * freshness) / competition, 4)

    def as_row(self) -> dict:
        usd = self.money.usd_estimate if self.money else None
        return {
            "repo": self.repo,
            "number": self.number,
            "title": self.title,
            "url": self.url,
            "reward": self.money.raw if self.money else "",
            "usd_estimate": usd,
            "currency": self.money.currency if self.money else "",
            "crypto": bool(self.money and self.money.is_crypto),
            "comments": self.comments,
            "accessible": self.is_accessible,
            "docs_work": self.is_docs_work,
            "claimable": self.is_claimable,
            "application": self.is_application,
            "labels": ",".join(sorted(self.labels)),
            "age_days": round(self.age_days, 1) if self.age_days is not None else None,
            "score": self.score(),
        }


def rank_bounties(
    bounties: list[Bounty],
    *,
    include_spam: bool = False,
    include_crypto: bool = True,
    include_uncollectable: bool = False,
    min_usd: float = 0.0,
) -> list[Bounty]:
    """Filter, then sort best-opportunity-first."""
    kept: list[Bounty] = []
    for b in bounties:
        if not include_spam and b.looks_spammy:
            continue
        if not include_uncollectable and not b.is_claimable:
            continue
        if b.money is None:
            continue
        if not include_crypto and b.money.is_crypto:
            continue
        usd = b.money.usd_estimate
        if usd is not None and usd < min_usd:
            continue
        kept.append(b)

    # De-duplicate on (repo, number) — overlapping searches return repeats.
    seen: set[tuple[str, int]] = set()
    unique: list[Bounty] = []
    for b in kept:
        key = (b.repo, b.number)
        if key in seen:
            continue
        seen.add(key)
        unique.append(b)

    if not include_spam:
        unique = _drop_aggregator_repos(unique)

    return sorted(unique, key=lambda b: b.score(), reverse=True)


def _drop_aggregator_repos(bounties: list[Bounty]) -> list[Bounty]:
    """Remove whole repos that only re-post other people's bounties.

    A single issue titled "[Bounty]" in a repo called `bounty-plaza` is not
    evidence of a bounty — it is evidence of a mirror. If a bounty-flavoured
    repo name shows up several times in one batch, the repo is an aggregator
    and every one of its rows is a duplicate of the original project's issue.
    """
    if not bounties:
        return bounties

    hits: dict[str, int] = {}
    for b in bounties:
        repo_name = b.repo.split("/")[-1]
        if _AGGREGATOR_REPO_RE.search(repo_name):
            hits[b.repo] = hits.get(b.repo, 0) + 1

    aggregators = {repo for repo, count in hits.items() if count >= _AGGREGATOR_MIN_HITS}
    if not aggregators:
        return bounties

    return [b for b in bounties if b.repo not in aggregators]


def aggregator_repos(bounties: list[Bounty]) -> list[tuple[str, int]]:
    """Expose which repos were treated as aggregators (for tests and --verbose)."""
    hits: dict[str, int] = {}
    for b in bounties:
        repo_name = b.repo.split("/")[-1]
        if _AGGREGATOR_REPO_RE.search(repo_name):
            hits[b.repo] = hits.get(b.repo, 0) + 1
    return sorted(
        ((repo, count) for repo, count in hits.items() if count >= _AGGREGATOR_MIN_HITS),
        key=lambda pair: pair[1], reverse=True,
    )
