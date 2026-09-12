"""Command line entry point: `python -m bounty_radar`.

Prints a ranked table of live, paying GitHub issues. Designed so the output can
be pasted straight into a note or a PR description.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import Optional, Sequence

from .fetch import DEFAULT_QUERIES, GitHubError, collect
from .rank import Bounty, rank_bounties


DOCS_QUERIES: list[str] = [
    'label:bounty docs state:open type:issue',
    'label:bounty translation state:open type:issue',
    'label:bounty i18n state:open type:issue',
    'label:documentation label:bounty state:open type:issue',
    'in:title bounty in:title translation state:open type:issue',
    'label:"good first issue" in:title bounty state:open type:issue',
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bounty-radar",
        description="Find open GitHub issues that pay, ranked by how winnable they are.",
        epilog="Set GITHUB_TOKEN (or log in with `gh auth login`) to raise the "
               "search rate limit from 10/min to 30/min.",
    )
    parser.add_argument("-n", "--limit", type=int, default=25,
                        help="how many bounties to show (default: 25)")
    parser.add_argument("--min-usd", type=float, default=0.0,
                        help="drop anything under this USD estimate")
    parser.add_argument("--no-crypto", action="store_true",
                        help="drop token-denominated bounties")
    parser.add_argument("--include-spam", action="store_true",
                        help="don't filter out auto-generated issues (debugging)")
    parser.add_argument("--include-uncollectable", action="store_true",
                        help="include payout-request / already-paid issues")
    parser.add_argument("--accessible-only", action="store_true",
                        help="only issues labelled good-first-issue / help wanted")
    parser.add_argument("--beginner", action="store_true",
                        help="docs/translation work ONLY, and search docs-specific "
                             "queries too. Lowest pay, highest merge rate. Use "
                             "--accessible-only instead for beginner-friendly CODE "
                             "tasks.")
    parser.add_argument("--language", type=str, default=None,
                        help="filter to issues mentioning this language, e.g. Python")
    parser.add_argument("--query", action="append", default=None, metavar="Q",
                        help="custom GitHub search query (repeatable)")
    parser.add_argument("--format", choices=("table", "json", "csv", "markdown"),
                        default="table")
    parser.add_argument("--save", type=str, default=None, metavar="PATH",
                        help="also write results to this file (format inferred from extension)")
    parser.add_argument("--verify", type=int, nargs="?", const=12, default=None,
                        metavar="N",
                        help="check whether the top N repos have ever merged a PR "
                             "(i.e. actually paid anyone). Costs API calls. STRONGLY "
                             "recommended before you spend an hour on a bounty.")
    parser.add_argument("--per-page", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=2)
    parser.add_argument("-q", "--quiet", action="store_true")
    return parser


def _fmt_usd(value: Optional[float]) -> str:
    if value is None:
        return "?"
    if value >= 1000:
        return f"${value:,.0f}"
    return f"${value:.0f}"


def render_table(rows: list[dict], limit: int) -> str:
    if not rows:
        return "No paying issues matched. Try dropping --min-usd or --accessible-only."

    header = f"{'#':>3}  {'USD~':>7}  {'CMNT':>4}  {'REPO':<34} {'ISSUE'}"
    rule = "-" * min(118, max(len(header), 78))
    lines = [header, rule]

    for index, row in enumerate(rows[:limit], start=1):
        stars = []
        if row.get("docs_work"):
            stars.append("docs")
        if row["accessible"]:
            stars.append("easy")
        if row["crypto"]:
            stars.append("token")
        tag = f" [{','.join(stars)}]" if stars else ""

        repo = row["repo"] if len(row["repo"]) <= 34 else row["repo"][:31] + "..."
        title = row["title"]
        budget = 118 - 3 - 2 - 7 - 2 - 4 - 2 - len(repo) - 2 - len(f"#{row['number']}")
        budget = max(30, budget)
        if len(title) > budget:
            title = title[: budget - 1] + "…"

        lines.append(
            f"{index:>3}  {_fmt_usd(row['usd_estimate']):>7}  {row['comments']:>4}  "
            f"{repo:<34} #{row['number']} {title}{tag}"
        )

    lines.append(rule)
    if any(row.get("payer_verdict") not in (None, "not checked") for row in rows[:limit]):
        lines.append("")
        lines.append("PAYER CHECK (merged PR history — has this repo ever paid anyone?)")
        seen: set[str] = set()
        for row in rows[:limit]:
            if row.get("payer_verdict") in (None, "not checked"):
                continue
            if row["repo"] in seen:
                continue
            seen.add(row["repo"])
            mark = "OK " if row.get("payer_verified") else "BAD"
            lines.append(f"  {mark} {row['repo']:<40} {row['payer_verdict']}")
        lines.append("")
        lines.append("BAD = never merged a PR, or went silent. Working there has a "
                     "known-zero expected return.")
    lines.append("")
    lines.append("USD~ = approximate USD (static FX rates, NOT live). CMNT = comment "
                 "count, a proxy for how many people are already on it.")
    return "\n".join(lines)


def render_markdown(rows: list[dict], limit: int) -> str:
    if not rows:
        return "_No paying issues matched._\n"
    lines = [
        "| # | Reward | ~USD | Comments | Repo | Issue |",
        "|--:|-------:|-----:|---------:|------|-------|",
    ]
    for index, row in enumerate(rows[:limit], start=1):
        title = row["title"].replace("|", "\\|")
        if len(title) > 70:
            title = title[:69] + "…"
        usd = _fmt_usd(row["usd_estimate"])
        crypto = " 🪙" if row["crypto"] else ""
        easy = " 🟢" if row["accessible"] else ""
        lines.append(
            f"| {index} | {row['reward'] or '?'}{crypto} | {usd} | {row['comments']} | "
            f"`{row['repo']}` | [#{row['number']}]({row['url']}) {title}{easy} |"
        )
    lines.append("")
    lines.append("🟢 beginner-friendly · 🪙 paid in tokens, USD unknown")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    log = (lambda _m: None) if args.quiet else (lambda m: print(m, file=sys.stderr))

    log("Bounty Radar — querying GitHub…")
    queries = args.query or (DEFAULT_QUERIES + DOCS_QUERIES if args.beginner
                             else DEFAULT_QUERIES)
    try:
        outcome = collect(queries,
                          per_page=args.per_page, max_pages=args.max_pages,
                          log=log)
    except GitHubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        print("If this is a rate limit, wait a minute or export GITHUB_TOKEN.",
              file=sys.stderr)
        return 2

    raw = outcome.bounties

    # Every query errored: say so loudly instead of printing an empty table
    # that looks like "no bounties exist today".
    if outcome.total_failure:
        print("error: every GitHub search query failed. No data was retrieved —",
              file=sys.stderr)
        print("this is NOT the same as 'no bounties found'.", file=sys.stderr)
        for err in outcome.errors[:3]:
            print(f"  - {err}", file=sys.stderr)
        print("\nLikely causes: an expired GITHUB_TOKEN/GH_TOKEN, or the search",
              file=sys.stderr)
        print("rate limit. Try `unset GITHUB_TOKEN GH_TOKEN` or `gh auth login`.",
              file=sys.stderr)
        return 2

    if outcome.queries_failed:
        log(f"  ! {outcome.queries_failed}/{outcome.queries_run} queries failed — "
            f"results are partial")

    log(f"  found {len(raw)} issues with a parseable amount")

    ranked = rank_bounties(
        raw,
        include_spam=args.include_spam,
        include_crypto=not args.no_crypto,
        include_uncollectable=args.include_uncollectable,
        min_usd=args.min_usd,
    )
    if args.accessible_only:
        ranked = [b for b in ranked if b.is_accessible]
    if args.beginner:
        # docs/translation ONLY. Keeping `is_accessible` here used to let code
        # tasks through under a beginner banner — "good first issue" does not
        # mean documentation, and a beginner who wanted docs work was shown
        # "[Bounty $600] Add Thursday's Boots".
        ranked = [b for b in ranked if b.is_docs_work]
    if args.language:
        needle = args.language.strip().lower()
        ranked = [b for b in ranked
                  if (b.language_hint or "").lower() == needle
                  or needle in " ".join(b.labels).lower()
                  or needle in b.title.lower()]

    log(f"  {len(ranked)} survived spam filtering")

    health: dict[str, object] = {}
    rejected: list[Bounty] = []
    if args.verify is not None:
        from .verify import apply_verification, verify_bounties

        log(f"verifying whether the top {args.verify} repos actually pay out…")
        health = verify_bounties(ranked, limit=args.verify, log=log)
        good, rejected = apply_verification(ranked, health)
        log(f"  {len(good)} from repos with a real merge history, "
            f"{len(rejected)} from repos with none")
        if not good and rejected:
            print("\nNone of the top results came from a repo that has ever merged "
                  "a PR.", file=sys.stderr)
            print("That is not bad luck — it is the normal state of open bounties.",
                  file=sys.stderr)
            print("Try Algora.io (escrowed bounties) instead of raw issue labels.",
                  file=sys.stderr)
        ranked = good if good else ranked

    rows = [b.as_row() for b in ranked]
    for row in rows:
        h = health.get(row["repo"])
        row["payer_verified"] = h.verified_payer if h is not None else None
        row["payer_verdict"] = h.verdict if h is not None else "not checked"

    if args.format == "json":
        print(json.dumps(rows[: args.limit], indent=2, ensure_ascii=False))
    elif args.format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys())) if rows else None
        if writer:
            writer.writeheader()
            writer.writerows(rows[: args.limit])
    elif args.format == "markdown":
        print(render_markdown(rows, args.limit))
    else:
        print(render_table(rows, args.limit))

    if args.save:
        path = args.save
        if path.endswith(".json"):
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(rows, handle, indent=2, ensure_ascii=False)
        elif path.endswith(".csv"):
            with open(path, "w", encoding="utf-8", newline="") as handle:
                if rows:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
                    writer.writeheader()
                    writer.writerows(rows)
        else:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(render_markdown(rows, args.limit) + "\n")
        log(f"  wrote {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
