"""Tests for the failure paths — the ones that decide whether the tool lies."""

import pytest

from bounty_radar.fetch import CollectResult
from bounty_radar.parse import extract_money
from bounty_radar.rank import Bounty


def make_bounty(number=1, **kw):
    defaults = dict(
        number=number, title="[Bounty $100] fix it",
        url=f"https://github.com/acme/widget/issues/{number}",
        repo="acme/widget", repo_owner="acme",
        money=extract_money("$100 bounty"),
        body_excerpt="A detailed enough description of the problem.",
    )
    defaults.update(kw)
    return Bounty(**defaults)


def test_total_failure_detected_when_every_query_errored():
    result = CollectResult(bounties=[], queries_run=6, queries_failed=6,
                           errors=["q1: HTTP 401"])
    assert result.total_failure is True


def test_partial_failure_is_not_total_failure():
    result = CollectResult(bounties=[make_bounty()], queries_run=6, queries_failed=2)
    assert result.total_failure is False


def test_no_queries_run_is_not_total_failure():
    # Zero queries is a config problem, not an API outage — don't mislabel it.
    assert CollectResult().total_failure is False


def test_clean_run_is_not_a_failure():
    result = CollectResult(bounties=[make_bounty()], queries_run=6, queries_failed=0)
    assert result.total_failure is False


def test_cli_exits_nonzero_and_explains_on_total_failure(monkeypatch, capsys):
    """The regression this guards: an expired token must not print 'no bounties'."""
    from bounty_radar import cli

    def boom(*_args, **_kwargs):
        return CollectResult(bounties=[], queries_run=6, queries_failed=6,
                             errors=["label:bounty: HTTP 401 for https://api.github.com"])

    monkeypatch.setattr(cli, "collect", boom)
    code = cli.main(["--limit", "5"])

    captured = capsys.readouterr()
    assert code == 2
    assert "every GitHub search query failed" in captured.err
    assert "NOT the same as" in captured.err
    # It must not claim an empty result set instead.
    assert "No paying issues matched" not in captured.out


def test_cli_still_runs_when_all_queries_succeed(monkeypatch, capsys):
    from bounty_radar import cli

    def fine(*_args, **_kwargs):
        return CollectResult(bounties=[make_bounty()], queries_run=6, queries_failed=0)

    monkeypatch.setattr(cli, "collect", fine)
    code = cli.main(["--limit", "5"])

    captured = capsys.readouterr()
    assert code == 0
    assert "acme/widget" in captured.out


def test_cli_warns_but_continues_on_partial_failure(monkeypatch, capsys):
    from bounty_radar import cli

    def partial(*_args, **_kwargs):
        return CollectResult(bounties=[make_bounty()], queries_run=6, queries_failed=2)

    monkeypatch.setattr(cli, "collect", partial)
    code = cli.main(["--limit", "5"])

    captured = capsys.readouterr()
    assert code == 0
    assert "2/6 queries failed" in captured.err
    assert "acme/widget" in captured.out


def test_json_output_is_valid(monkeypatch, capsys):
    import json

    from bounty_radar import cli

    def fine(*_args, **_kwargs):
        return CollectResult(bounties=[make_bounty()], queries_run=1, queries_failed=0)

    monkeypatch.setattr(cli, "collect", fine)
    cli.main(["--format", "json", "--limit", "5"])

    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list) and len(payload) == 1
    assert payload[0]["usd_estimate"] == 100.0


def test_markdown_output_has_a_table(monkeypatch, capsys):
    from bounty_radar import cli

    def fine(*_args, **_kwargs):
        return CollectResult(bounties=[make_bounty()], queries_run=1, queries_failed=0)

    monkeypatch.setattr(cli, "collect", fine)
    cli.main(["--format", "markdown", "--limit", "5"])

    out = capsys.readouterr().out
    assert "| # | Reward |" in out
    assert "issues/1" in out


@pytest.mark.parametrize("flag", ["--no-crypto", "--accessible-only"])
def test_filters_do_not_crash_on_empty_results(monkeypatch, capsys, flag):
    from bounty_radar import cli

    monkeypatch.setattr(cli, "collect",
                        lambda *a, **k: CollectResult(queries_run=1, queries_failed=0))
    code = cli.main([flag, "--limit", "5"])

    assert code == 0
    assert "No paying issues matched" in capsys.readouterr().out
