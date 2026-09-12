# Bounty Radar

**Find GitHub issues that actually pay — and skip the ~53% that are bot spam.**

There are roughly 4,400 open GitHub issues carrying a `bounty` label at any
moment. When we last measured, **122 of the 230 top results were junk**:
aggregator bots reposting each other's bounties, payout requests for work
already done, "bounty proposals" that were never funded, and currency amounts
scraped out of line numbers.

Bounty Radar runs the search, kills the junk, and ranks what is left by how
*winnable* it is — not just how big the number is.

```
  #     USD~  CMNT  REPO                               ISSUE
------------------------------------------------------------------------------
  1   $5,000     4  tenstorrent/tt-metal               #55130 [Bounty $5,000] ttnn.bias_gelu silently…
  2   $7,500    12  tenstorrent/tt-metal               #56277 [Bounty $7500] Remove legacy sqrt/rsqrt…
  3  $50,000     7  sherlock-audit/2024-08-velar-ar…   #72 Funding fee will be zero because of precis…
  4   $1,250     7  Senthemodder/aquarium-of-gullib…   #1 [Bounty: $1,250] Optimize Subgraph Isomorph… [easy]
```

🟢 = beginner-friendly · CMNT = comment count, a proxy for how crowded it is

---

## Install & run

Python 3.9+. No third-party dependencies — standard library only.

```bash
git clone https://github.com/chaitanyadahatonde007-commits/omni-ai
cd omni-ai

python3 -m bounty_radar                       # top 25, live from GitHub
python3 -m bounty_radar --accessible-only     # only good-first-issue / help-wanted
python3 -m bounty_radar --min-usd 100         # ignore anything under ~$100
python3 -m bounty_radar --language Python     # filter by language
python3 -m bounty_radar --format markdown --save bounties.md
python3 -m bounty_radar --format json         # pipe into your own tooling
```

Set a token to raise the search rate limit from 10/min to 30/min:

```bash
export GITHUB_TOKEN=ghp_xxx      # or: gh auth login
```

---

## The honest economics

This tool was built by someone who was told "make money from GitHub" and wanted
to know what that actually means. Here are the real numbers, not the pitch.

| Route | Realistic payout | Effort | The catch |
|---|---|---|---|
| **Bounties** (this tool) | $50–$5,000/issue | Medium | ~15% merge rate on platforms like Algora |
| **Technical writing** | $50–$500/article | Low | Needs a portfolio to start |
| **Services / consulting** | $100–$300/hour | Medium | Only after OSS credibility exists |
| **GitHub Sponsors** | $50–$500/mo mid-tier | Ongoing | Requires an audience you don't have yet |

A few things worth knowing before you spend a weekend on this:

- **GitHub pays nothing for repositories.** Stars, forks and commits are not
  currency. An empty repo earns $0 forever.
- **Sponsors is not passive income.** ~49,000 developers have been funded with
  ~$50M paid out cumulatively since 2019 — an average of roughly $1,000 *each,
  total*, over seven years. The people earning $100k/yr from it maintain
  libraries that thousands of companies depend on.
- **Bounties are the only route that pays a newcomer.** No audience required.
  That is why this tool exists.
- **A documented 30-day attempt** at open-source bounties netted **$430 for 55
  hours — about $7.82/hour**. That is a real number from a real person. It is
  not a get-rich path; it is a way to get paid while building the portfolio
  that makes the other routes possible.

Use this tool to skip the two hours a week you would otherwise burn reading
bot-generated issues. That is the whole promise, and it is a real one.

---

## How the ranking works

The scoring formula lives in [`bounty_radar/rank.py`](bounty_radar/rank.py) and
is deliberately simple enough to argue with:

```
score = reward × accessibility × freshness ÷ (1 + 0.35 × comments)
```

- **reward** — USD estimate, square-root compressed so a $50,000 audit finding
  does not completely bury a realistic $150 fix.
- **accessibility** — ×1.3 if labelled `good first issue` / `help wanted`,
  ×0.6 if labelled `expert` / `security`.
- **freshness** — decays over ~90 days. Stale issues are usually stale for a
  reason.
- **comments** — competition. 40 comments means 40 people already tried.

### What gets filtered out

| Filter | Example it catches |
|---|---|
| **Bounty applications** | *"I would like to claim the ZH translation variant…"* — this is your **competition**, not an opportunity |
| **Unfunded proposals** | *"would you approve US$25 after acceptance and merge"* — the author is asking, nobody is offering |
| **Valuations, not payouts** | *"replaces **$48,000/yr** operator with **$88** kit"* — the bounty is $88 |
| **Aggregator bots** | `🎯 Bounty Alert: 13 New Opportunities found` |
| **Aggregator repos** | a repo named `bounty-plaza` dominating the result set |
| **Payout requests** | `[Payout Request] Consolidated Bounty Claim for 10 Merged PRs` |
| **Retracted issues** | *"Please disregard this issue"* |
| **Governance noise** | `Weekly Meeting Facilitation 04.07.2024` |
| **Bot authors** | `dependabot[bot]`, `*-bot` |
| **Not-money** | `port $8080`, `line $1080`, `© 2024` |

Every one of these was found in live data, not imagined. Each has a regression
test named after the issue that exposed it.

Override any of it with `--include-spam` / `--include-uncollectable` if you
think the filter is being too aggressive.

### Payer verification — read this first

```bash
python3 -m bounty_radar --beginner --verify 12
```

This is the most important flag in the tool. Amount, labels and freshness say
**nothing** about whether anyone will pay you.

When this was first run against the beginner list, it checked the top 29
results and found **not one of them** came from a repo with a live payment
record:

```
BAD cuentaprueba244w-dotcom/zeroeye    NO EVIDENCE OF PAYMENT (0 merged PR, 114 open PR, pushed 86d ago)
BAD mergeos-bounties/Loru              BACKLOGGED 5:1 open:merged (50 merged PR, 253 open PR, pushed 53d ago)
BAD HBesso31/LiquidFenix               NO EVIDENCE OF PAYMENT (0 merged PR, 4 open PR, pushed 2349d ago)
BAD BTCPrivate/BTCP-Rebase             PAID BEFORE, NOW STALE (40 merged PR, 12 open PR, pushed 2792d ago)
```

The worst case, `cuentaprueba244w-dotcom/zeroeye`, had posted `$12`–`$30`
beginner docs bounties labelled `good first issue` + `help wanted`. On the
surface, exactly what a beginner should chase. In reality:

- **0 PRs merged, ever.** 114 open and unreviewed.
- Account created 2026-06-14, repo created 2026-06-17, last push 2026-06-19.
- At least **seven different people** submitted a PR for the same `$25` task.
- A commenter on 2026-09-12 withdrew theirs: *"I can't confirm this bounty has
  a funded payer behind it."*

Three signals, all cheap to check, all decisive:

| Signal | Question it answers |
|---|---|
| **merged PRs** | Has this repo ever accepted anyone's work? |
| **open:merged ratio** | Does the review queue move, or pile up? |
| **days since push** | Is a maintainer still there to review yours? |

A repo with 40 merged PRs that has been silent for 2,792 days is not a
opportunity. Neither is one with a 5:1 backlog — your PR just joins the pile.

**If verification finds nothing, that is the honest answer**, and the tool says
so rather than printing a table that looks encouraging:

```
None of the top results came from a repo that has ever merged a PR.
That is not bad luck — it is the normal state of open bounties.
Try Algora.io (escrowed bounties) instead of raw issue labels.
```

Escrowed platforms hold the money *before* the work starts, which removes the
failure mode entirely. Label-scraping cannot.

### Beginner mode

```bash
python3 -m bounty_radar --beginner
```

Docs and translation **only**. These pay the least ($6–$150) but have by far the
highest merge rate, which is what builds the contribution history that makes
better-paid work reachable.

Note that `--beginner` deliberately does **not** mean "labelled `good first
issue`". Maintainers put that label on code tasks constantly — treating it as
documentation is how `[Bounty $600] Add Thursday's Boots` ended up recommended
to someone who asked for docs work. Use `--accessible-only` for
beginner-friendly code tasks.

---

## Known limitations

Be honest about these — they are real:

- **FX rates are static.** `FIAT_TO_USD` in `parse.py` is a hand-maintained
  table, not a live feed. Fine for sorting, wrong for invoicing.
- **Crypto bounties are never priced.** A token amount is flagged 🪙 and ranked
  on merit. Guessing a token price from a regex would be worse than admitting
  we do not know.
- **`¥` is assumed to be CNY.** It is ambiguous with JPY. CNY is the more
  common bounty currency, but this will occasionally misread a Japanese bounty.
- **The docs classifier is heuristic.** It reads titles and labels, not the
  full body or the diff. An issue labelled `documentation` that is really a
  multi-domain epic will still show up under `--beginner`.
- **Comments are a rough competition proxy.** They do not capture linked PRs or
  private claims.
- **The search API caps pagination at 1,000 results.** Very popular queries
  will not return everything.
- **A listed bounty is not a guaranteed bounty.** Always read the issue and
  confirm the terms before you start. Some are contests; some get closed while
  you work.

---

## Development

```bash
pip install pytest
python3 -m pytest tests/ -q
```

### Enabling CI

A GitHub Actions workflow is included at **`ci/tests.workflow.yml`**. It is
deliberately *not* in `.github/workflows/`, because the bot account used to push
this repo is not granted the `workflows` scope and GitHub rejects the push:

```
! [remote rejected] (refusing to allow a GitHub App to create or update
  workflow `.github/workflows/tests.yml` without `workflows` permission)
```

To turn it on yourself (your account has full permission):

```bash
mkdir -p .github/workflows
cp ci/tests.workflow.yml .github/workflows/tests.yml
git add .github/workflows/tests.yml && git commit -m "Enable CI" && git push
```

It runs the test suite on Python 3.9 / 3.11 / 3.12 plus a `--help` smoke test.

130 tests cover amount parsing, spam/application detection, payer verification,
ranking order, output formats, and — importantly — the failure paths, so an
expired token can never be reported as "no bounties found". Several tests are
named after the specific live issue or repo that exposed the bug they guard.

## Licence

MIT — see [LICENSE](LICENSE).
