"""Bounty Radar — find GitHub issues that actually pay, and skip the bot spam."""

__version__ = "0.1.0"

from .parse import Money, extract_money, has_bounty_keyword
from .rank import Bounty, rank_bounties
from .fetch import CollectResult, collect, to_bounty, GitHubError
from .rank import aggregator_repos

__all__ = [
    "Money", "extract_money", "has_bounty_keyword",
    "Bounty", "rank_bounties", "aggregator_repos",
    "collect", "CollectResult", "to_bounty", "GitHubError",
    "__version__",
]
