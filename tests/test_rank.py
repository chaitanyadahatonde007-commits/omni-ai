from datetime import datetime, timedelta, timezone

import pytest

from bounty_radar.parse import extract_money
from bounty_radar.rank import Bounty, rank_bounties


def make_bounty(**overrides) -> Bounty:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    defaults = dict(
        number=1,
        title="Fix the thing",
        url="https://github.com/acme/widget/issues/1",
        repo="acme/widget",
        repo_owner="acme",
        labels=[],
        comments=0,
        created_at=now,
        updated_at=now,
        body_excerpt="A reasonably detailed description of the problem goes here.",
        money=extract_money("$100 bounty"),
    )
    defaults.update(overrides)
    return Bounty(**defaults)


def test_spam_detected_by_radar_tag():
    assert make_bounty(title="[radar] SN open bounty 2026-09-12T10:38").looks_spammy


def test_spam_detected_by_timestamp_in_title():
    assert make_bounty(title="sync 2026-09-12T05:39 something").looks_spammy


def test_spam_detected_by_bot_owner():
    assert make_bounty(repo_owner="spam-bot").looks_spammy
    assert make_bounty(repo_owner="dependabot[bot]").looks_spammy


def test_spam_detected_by_empty_body_without_money():
    assert make_bounty(body_excerpt="hi", money=None).looks_spammy


def test_normal_issue_is_not_spam():
    assert make_bounty().looks_spammy is False


@pytest.mark.parametrize("title", [
    "🎯 Micro Bounty Alert: 4 New Opportunities",
    "🎯 Bounty Alert: 13 New Opportunities found",
    "Daily bounty digest — 12 new bounties",
    "[BountyScout] weekly roundup",
])
def test_aggregator_bots_are_spam(title):
    assert make_bounty(title=title).looks_spammy


@pytest.mark.parametrize("repo", [
    "2510034127qq-wq/BountyScout",
    "someone/bounty-alert",
    "someone/bounty_tracker",
])
def test_aggregator_repos_are_spam(repo):
    owner, name = repo.split("/")
    assert make_bounty(repo=repo, repo_owner=owner).looks_spammy


@pytest.mark.parametrize("title", [
    "[Payout Request] Consolidated Bounty Claim for 10 Merged PRs",
    "Weekly Meeting Facilitation 04.07.2024",
    "[PAID] fix the login bug",
])
def test_uncollectable_issues_are_excluded_by_default(title):
    b = make_bounty(title=title)
    assert b.is_claimable is False
    assert rank_bounties([b]) == []
    assert len(rank_bounties([b], include_uncollectable=True)) == 1


def test_real_bounty_is_still_claimable():
    assert make_bounty(title="[Bounty $5,000] fix the bias_gelu approximation").is_claimable


def test_aggregator_repo_dropped_when_it_dominates_the_batch():
    mirror = [make_bounty(number=i, repo="someone/bounty-plaza", repo_owner="someone",
                          title=f"[Bounty ${100 * i}] mirrored issue {i}")
              for i in range(1, 5)]
    real = make_bounty(number=9, repo="tenstorrent/tt-metal", repo_owner="tenstorrent",
                       title="[Bounty $5,000] real issue")
    ranked = rank_bounties(mirror + [real])
    assert [b.repo for b in ranked] == ["tenstorrent/tt-metal"]


def test_aggregator_repo_kept_below_threshold():
    # Two hits is not enough evidence to condemn the whole repo.
    two = [make_bounty(number=i, repo="someone/bounty-plaza", repo_owner="someone",
                       title=f"[Bounty ${100 * i}] issue {i}") for i in (1, 2)]
    assert len(rank_bounties(two)) == 2


def test_aggregator_repos_helper_reports_what_was_dropped():
    from bounty_radar.rank import aggregator_repos
    mirror = [make_bounty(number=i, repo="someone/bounty-plaza", repo_owner="someone")
              for i in range(1, 4)]
    assert aggregator_repos(mirror) == [("someone/bounty-plaza", 3)]


def test_bounty_proposal_disclaimer_is_not_claimable():
    body = ("The US$25 below is my requested reward, not a funded offer from me. "
            "Only maintainers can approve bounty eligibility.")
    b = make_bounty(title="docs(cli): Serbian quickstart (US$25 bounty proposal)",
                    body_excerpt=body)
    assert b.is_claimable is False
    assert rank_bounties([b]) == []


@pytest.mark.parametrize("title", [
    "docs(cli): Serbian quickstart for omi-cli",
    "[Bounty $25] Translate README to Indonesian",
    "Add Japanese tutorial for the API",
    "Fix typo in CONTRIBUTING.md",
    "Proofread the getting started guide",
])
def test_docs_work_detected(title):
    assert make_bounty(title=title).is_docs_work


@pytest.mark.parametrize("title", [
    "[Bounty $5,000] ttnn.bias_gelu silently computes approximate GELU",
    "Remove legacy sqrt/rsqrt compatibility paths",
    "Optimize Subgraph Isomorphism to strict O(n)",
])
def test_code_work_is_not_docs_work(title):
    assert make_bounty(title=title).is_docs_work is False


def test_docs_label_counts_even_without_keywords_in_title():
    assert make_bounty(title="Improve the onboarding flow",
                       labels=["documentation"]).is_docs_work


def test_expert_label_blocks_docs_classification():
    # A friendly-sounding title does not make an expert task beginner-friendly.
    assert make_bounty(title="Document the security model",
                       labels=["expert", "security"]).is_docs_work is False


def test_docs_work_appears_in_row():
    row = make_bounty(title="[Bounty $25] Translate README to Indonesian").as_row()
    assert row["docs_work"] is True


def test_good_first_issue_label_alone_is_not_docs_work():
    """Regression: 'good first issue' means beginner, not documentation.

    theselfish/SlopStation13#5 is "[Bounty $600] Add Thursday's Boots" and
    carries `good first issue`. It is a code task, not docs work.
    """
    b = make_bounty(title="[Bounty] [$600] Add Thursday's Boots",
                    labels=["good first issue", "BOUNTY"])
    assert b.is_docs_work is False
    # But it IS still beginner-accessible, which is a separate claim.
    assert b.is_accessible is True


def test_salesforce_integration_is_not_docs_work():
    assert make_bounty(title="[Bounty: $300] Salesforce integration",
                       labels=["good first issue"]).is_docs_work is False


def test_please_disregard_is_not_claimable():
    """JustTemmie/steam-presence#145 says 'Please disregard this issue'."""
    b = make_bounty(title="[Bounty: $300] Salesforce integration",
                    body_excerpt="## Task\nPlease integrate salesforce.\n\n"
                                 "## Note for humans\nPlease disregard this issue")
    assert b.is_claimable is False
    assert rank_bounties([b]) == []


@pytest.mark.parametrize("body", [
    "Please disregard this issue",
    "Note for humans: this is not a real bounty",
    "ignore this issue, it was a test",
    "this is just a test issue",
])
def test_retracted_issues_are_filtered(body):
    assert make_bounty(body_excerpt=body).is_claimable is False


def test_leading_proposed_adjective_is_not_claimable():
    """Regression: BasedHardware/omi#13513.

    Title "Proposed US$25 CLI docs bounty" — the old pattern required
    `proposed` to be immediately followed by bounty/reward/payout, but a
    currency sat in between, so an unfunded proposal ranked #4 for beginners.
    """
    body = ("Following the contribution guide's invitation to suggest paid work, "
            "would you approve **US$25 after acceptance and merge** for a "
            "PowerShell examples index? This proposal does not duplicate #13480.")
    b = make_bounty(title="Proposed US$25 CLI docs bounty: read-only PowerShell examples",
                    body_excerpt=body)
    assert b.is_claimable is False
    assert rank_bounties([b]) == []


@pytest.mark.parametrize("title,body", [
    ("Proposed US$25 CLI docs bounty", "details here about the work to be done"),
    ("Add Serbian quickstart", "would you approve US$25 after acceptance and merge?"),
    ("Translate the README", "This proposal asks for $50 on merge."),
    ("Fix the docs index", "I would like to be paid $30 for this."),
])
def test_ask_to_be_paid_forms_are_filtered(title, body):
    assert make_bounty(title=title, body_excerpt=body).is_claimable is False


def test_real_funded_bounty_is_not_caught_by_proposal_filter():
    """Guard against the filter becoming so eager it eats real work."""
    b = make_bounty(title="bounty: Chinese documentation translation",
                    body_excerpt="We will pay $150 on merge. "
                                 "Translate docs/ to Simplified Chinese. "
                                 "Approved and funded by the maintainers.")
    assert b.is_claimable is True


@pytest.mark.parametrize("body", [
    # liana-banyan/librarian-mcp#8
    "I would like to claim the ZH translation variant described in issues/002.",
    # SolanaNameService/sns-sdk-archive#128
    "I'm writing to express my strong interest in the $700 Superteam bounty "
    "for translating the SNS SDK into Python. I am a Python developer with "
    "experience building scripts for DeFi protocols.",
    # Clawland-AI/clawland-ai.github.io#2
    "I would like to work on the Chinese Documentation Translation bounty "
    "listed on the Clawland bounty board for $150. Before I start the full "
    "translation, could maintainers confirm the scope?",
])
def test_bounty_applications_are_filtered(body):
    """The worst false-positive class: showing you your own competition."""
    b = make_bounty(title="[Bounty $150] Chinese documentation translation",
                    body_excerpt=body)
    assert b.is_application is True
    assert b.is_claimable is False
    assert rank_bounties([b]) == []


def test_claim_prefix_in_title_is_an_application():
    b = make_bounty(title="Claim: ZH translation preload bounty (task 002, US$75)")
    assert b.is_application is True


def test_real_maintainer_offer_is_not_an_application():
    """Guard against the application filter eating genuine bounties."""
    b = make_bounty(
        title="[Bounty $150] Chinese documentation translation",
        body_excerpt="## Task\nTranslate everything under docs/ into Simplified "
                     "Chinese. We will pay $150 once the PR is merged. "
                     "Open to any contributor — no prior experience required.",
    )
    assert b.is_application is False
    assert b.is_claimable is True
    assert len(rank_bounties([b])) == 1


@pytest.mark.parametrize("labels", [
    ["level: hard"],           # codesphere-community/templates#15
    ["difficulty/hard"],
    ["priority: critical"],
    ["expert"],
    ["security"],
])
def test_hard_label_variants_are_recognised(labels):
    """Repos write 'level: hard', not 'hard' — exact set matching missed them."""
    assert make_bounty(labels=labels).is_hard is True


def test_hard_label_blocks_docs_classification_via_substring():
    b = make_bounty(title="LibreTranslator - SEO compliant webpage translator tool",
                    labels=["community", "paid", "level: hard"])
    assert b.is_hard is True
    assert b.is_docs_work is False


def test_plain_labels_are_not_hard():
    assert make_bounty(labels=["bug", "documentation"]).is_hard is False


def test_easy_marker_in_title_counts_as_accessible():
    assert make_bounty(title="[Bounty: $1,250] Optimise subgraph [easy]").is_accessible
    assert make_bounty(title="[Bounty: $1,250] Optimise subgraph").is_accessible is False


def test_accessible_labels_recognised():
    assert make_bounty(labels=["good first issue"]).is_accessible
    assert make_bounty(labels=["Help Wanted"]).is_accessible
    assert make_bounty(labels=["bug"]).is_accessible is False


def test_higher_payout_outranks_lower():
    cheap = make_bounty(number=1, money=extract_money("$50 bounty"))
    rich = make_bounty(number=2, money=extract_money("$2000 bounty"))
    ranked = rank_bounties([cheap, rich])
    assert [b.number for b in ranked] == [2, 1]


def test_fewer_comments_beats_more_comments_at_same_payout():
    quiet = make_bounty(number=1, comments=0)
    crowded = make_bounty(number=2, comments=40)
    ranked = rank_bounties([crowded, quiet])
    assert [b.number for b in ranked] == [1, 2]


def test_beginner_friendly_beats_equal_unlabelled():
    easy = make_bounty(number=1, labels=["good first issue"])
    plain = make_bounty(number=2)
    ranked = rank_bounties([plain, easy])
    assert [b.number for b in ranked] == [1, 2]


def test_expert_label_is_penalised():
    hard = make_bounty(number=1, labels=["expert", "security"])
    plain = make_bounty(number=2)
    ranked = rank_bounties([hard, plain])
    assert [b.number for b in ranked] == [2, 1]


def test_stale_issues_rank_below_fresh():
    fresh = make_bounty(number=1)
    old = make_bounty(
        number=2,
        created_at=(datetime.now(timezone.utc) - timedelta(days=200))
        .isoformat().replace("+00:00", "Z"),
    )
    ranked = rank_bounties([old, fresh])
    assert [b.number for b in ranked] == [1, 2]


def test_dedupes_on_repo_and_number():
    a = make_bounty(number=7, repo="acme/widget")
    b = make_bounty(number=7, repo="acme/widget")
    c = make_bounty(number=7, repo="other/widget")
    assert len(rank_bounties([a, b, c])) == 2


def test_issues_without_money_are_dropped():
    assert rank_bounties([make_bounty(money=None, body_excerpt="x" * 100)]) == []


def test_min_usd_filter():
    small = make_bounty(number=1, money=extract_money("$10 bounty"))
    big = make_bounty(number=2, money=extract_money("$900 bounty"))
    assert [b.number for b in rank_bounties([small, big], min_usd=100)] == [2]


def test_crypto_excluded_on_request():
    fiat = make_bounty(number=1, money=extract_money("$100 bounty"))
    token = make_bounty(number=2, money=extract_money("100 SOL bounty"))
    assert [b.number for b in rank_bounties([fiat, token], include_crypto=False)] == [1]
    assert len(rank_bounties([fiat, token], include_crypto=True)) == 2


def test_include_spam_lets_noise_through():
    spam = make_bounty(number=1, title="[radar] SN open bounty 2026-09-12T10:38")
    assert rank_bounties([spam]) == []
    assert len(rank_bounties([spam], include_spam=True)) == 1


def test_as_row_shape():
    row = make_bounty(labels=["good first issue"]).as_row()
    assert row["usd_estimate"] == 100.0
    assert row["accessible"] is True
    assert row["crypto"] is False
    assert isinstance(row["score"], float)


def test_score_is_stable_and_positive():
    b = make_bounty()
    assert b.score() == b.score()
    assert b.score() > 0
