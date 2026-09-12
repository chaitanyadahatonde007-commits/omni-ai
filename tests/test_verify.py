"""Tests for payer verification — the check that stops you working for free."""

from datetime import datetime, timedelta, timezone

import pytest

from bounty_radar.parse import extract_money
from bounty_radar.rank import Bounty
from bounty_radar.verify import RepoHealth, apply_verification


def _days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace("+00:00", "Z")


def make_bounty(number=1, repo="acme/widget"):
    owner = repo.split("/")[0]
    return Bounty(
        number=number, title=f"[Bounty $100] task {number}",
        url=f"https://github.com/{repo}/issues/{number}",
        repo=repo, repo_owner=owner,
        money=extract_money("$100 bounty"),
        body_excerpt="A detailed enough description of the problem.",
    )


def test_zeroeye_real_world_case_is_not_a_verified_payer():
    """The exact numbers from cuentaprueba244w-dotcom/zeroeye."""
    h = RepoHealth(repo="cuentaprueba244w-dotcom/zeroeye", merged_prs=0,
                   open_prs=114, stars=2, pushed_at=_days_ago(85))
    assert h.verified_payer is False
    # Rejected for having never merged anything — the strongest signal, and it
    # fires even though 85 days is inside the 90-day staleness window.
    assert h.has_merge_history is False
    assert h.stalled is False
    assert "NO EVIDENCE OF PAYMENT" in h.verdict


def test_repo_with_merged_prs_is_verified():
    h = RepoHealth(repo="mergeos-bounties/PoseGuide", merged_prs=19,
                   open_prs=5, stars=13, pushed_at=_days_ago(2))
    assert h.verified_payer is True
    assert h.verdict.startswith("PAID (")
    assert "NO EVIDENCE" not in h.verdict


def test_single_merged_pr_still_counts():
    assert RepoHealth(repo="a/b", merged_prs=1, pushed_at=_days_ago(1)).verified_payer


def test_btcp_rebase_real_world_case_is_stale_not_paid():
    """BTCPrivate/BTCP-Rebase: 40 merged PRs, but pushed 2792 days ago.

    Reporting this as "PAID" would send someone to a repo that has not seen a
    commit in seven and a half years.
    """
    h = RepoHealth(repo="BTCPrivate/BTCP-Rebase", merged_prs=40,
                   open_prs=12, pushed_at=_days_ago(2792))
    assert h.has_merge_history is True
    assert h.stalled is True
    assert h.verified_payer is False
    assert "PAID BEFORE, NOW STALE" in h.verdict


def test_naous_stale_at_244_days():
    h = RepoHealth(repo="Uraxii/naous", merged_prs=35, open_prs=9,
                   pushed_at=_days_ago(244))
    assert h.verified_payer is False
    assert "STALE" in h.verdict


def test_loru_real_world_case_is_backlogged():
    """mergeos-bounties/Loru: 50 merged, 253 open — a 5:1 review queue."""
    h = RepoHealth(repo="mergeos-bounties/Loru", merged_prs=50, open_prs=253,
                   pushed_at=_days_ago(53))
    assert h.has_merge_history is True
    assert h.stalled is False          # 53 days is not abandoned
    assert h.backlogged is True        # but the queue is not moving
    assert h.verified_payer is False
    assert "BACKLOGGED 5:1" in h.verdict


def test_healthy_repo_passes_all_three_checks():
    h = RepoHealth(repo="acme/live", merged_prs=120, open_prs=14,
                   pushed_at=_days_ago(4))
    assert h.stalled is False
    assert h.backlogged is False
    assert h.verified_payer is True


def test_small_open_pr_count_does_not_trigger_backlog():
    # 10 open against 3 merged is a 3.3 ratio but only 10 PRs — too small to
    # call a trend.
    h = RepoHealth(repo="a/b", merged_prs=3, open_prs=10, pushed_at=_days_ago(2))
    assert h.backlogged is False
    assert h.verified_payer is True


@pytest.mark.parametrize("days,expected_stale", [(89, False), (91, True)])
def test_stalled_threshold_is_90_days(days, expected_stale):
    h = RepoHealth(repo="a/b", merged_prs=10, open_prs=2, pushed_at=_days_ago(days))
    assert h.stalled is expected_stale


def test_lookup_failure_is_not_a_verified_payer():
    """Never treat 'we couldn't check' as 'they pay'."""
    h = RepoHealth(repo="a/b", error="repo lookup failed")
    assert h.verified_payer is False
    assert "unknown" in h.verdict


def test_stalled_detection():
    assert RepoHealth(repo="a/b", merged_prs=5, pushed_at=_days_ago(400)).stalled is True
    assert RepoHealth(repo="a/b", merged_prs=5, pushed_at=_days_ago(3)).stalled is False
    assert RepoHealth(repo="a/b", merged_prs=5, pushed_at=None).stalled is False


def test_apply_verification_splits_and_preserves_order():
    bounties = [
        make_bounty(1, repo="good/repo"),
        make_bounty(2, repo="bad/repo"),
        make_bounty(3, repo="good/repo"),
    ]
    health = {
        "good/repo": RepoHealth(repo="good/repo", merged_prs=8, pushed_at=_days_ago(2)),
        "bad/repo": RepoHealth(repo="bad/repo", merged_prs=0, pushed_at=_days_ago(90)),
    }
    good, bad = apply_verification(bounties, health)
    assert [b.number for b in good] == [1, 3]
    assert [b.number for b in bad] == [2]


def test_unchecked_repos_land_in_unverified():
    """Absence of evidence is not evidence of a payer."""
    b = make_bounty(1, repo="never/checked")
    good, bad = apply_verification([b], {})
    assert good == []
    assert [x.number for x in bad] == [1]


def test_verdict_string_shows_the_numbers():
    h = RepoHealth(repo="a/b", merged_prs=0, open_prs=114, pushed_at=_days_ago(85))
    verdict = h.verdict
    assert "0 merged PR" in verdict
    assert "114 open PR" in verdict
    assert "85d ago" in verdict


def test_verify_flag_is_wired_into_the_parser():
    from bounty_radar.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["--verify"]).verify == 12       # const
    assert parser.parse_args(["--verify", "5"]).verify == 5   # explicit
    assert parser.parse_args([]).verify is None               # default off


@pytest.mark.parametrize("merged,open_prs,expected_flag", [
    (0, 114, "BAD"),
    (19, 5, "OK "),
])
def test_table_marks_payer_verdict(monkeypatch, capsys, merged, open_prs, expected_flag):
    from bounty_radar import cli
    from bounty_radar.fetch import CollectResult
    from bounty_radar.verify import RepoHealth

    bounty = make_bounty(1, repo="acme/widget")
    monkeypatch.setattr(cli, "collect",
                        lambda *a, **k: CollectResult(bounties=[bounty],
                                                      queries_run=1, queries_failed=0))
    monkeypatch.setattr("bounty_radar.verify.verify_bounties",
                        lambda bounties, **k: {
                            "acme/widget": RepoHealth(repo="acme/widget",
                                                      merged_prs=merged,
                                                      open_prs=open_prs,
                                                      pushed_at=_days_ago(1))})

    cli.main(["--verify", "1"])
    out = capsys.readouterr().out
    assert "PAYER CHECK" in out
    assert expected_flag in out
