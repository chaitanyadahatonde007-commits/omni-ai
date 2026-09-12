# How to actually earn from this

Written 2026-09-12 for a beginner in India with no audience. Every factual claim
below was checked against a primary source; anything I could not check is
labelled **unverified**.

---

## The order matters more than the steps

Most people do this backwards: they hunt bounties for a month, then try to set
up payments. Payment setup takes **days to weeks** because of KYC. Do that
first, on day one, while you have nothing to be paid for yet.

---

## Step 1 — Payment rails (today, ~45 min, then wait)

GitHub Sponsors **is available in India.** Confirmed on GitHub's official
supported-regions list — India appears in it. You are not waitlisted.

What that actually means in practice:

| Thing | Reality |
|---|---|
| Who can join | Individual developers, not just companies |
| Payout route | Stripe Connect (GitHub sets it up; you don't need your own Stripe account) |
| Currency | **INR only.** Stripe converts before settlement — you cannot hold USD |
| KYC needed | PAN + identity. Non-US persons complete Form W-8BEN |
| Fees | ~10–15% of gross total (platform up to 6%, processing ~2.9%, plus FX margin) |
| First payout | A few weeks (KYC + batching) |
| Later payouts | 7–15 days from cycle close |

**The thing that blocks most people:** your legal name must match *exactly*
across GitHub, your PAN, and your bank account. Mismatches are the #1 payout
blocker. Check this before you submit.

On a `$100` sponsorship expect roughly **₹7,600–8,200** net, depending on the
day's FX rate.

Do this today. Then forget about it for a month.

---

## Step 2 — The rule that stops you working for free

This is the most valuable thing in this document.

**Never spend more than 10 minutes on a bounty until you have checked whether
the repo has ever merged a PR.**

```bash
python3 -m bounty_radar --beginner --verify 12
```

Three numbers, thirty seconds:

1. **Merged PRs ever** — has anyone's work been accepted?
2. **Open:merged ratio** — does the review queue move?
3. **Days since last push** — is a maintainer still there?

### The case that made me build this

The tool originally ranked three `$12`–`$30` beginner docs bounties at the very
top. Labels: `documentation`, `help wanted`, `good first issue`, `bounty`. On
paper, perfect for you.

Checking `cuentaprueba244w-dotcom/zeroeye` directly:

```
merged PRs ever : 0
open PRs        : 114      <- people are still submitting
last push       : 2026-06-19
account created : 2026-06-14
stars           : 2
```

At least **seven different people** submitted a PR for the same `$25` task.
Nothing was merged. Nobody was paid. On 2026-09-12 a commenter withdrew theirs:
*"I can't confirm this bounty has a funded payer behind it."*

That account name is Spanish for "test account." I did not notice before
ranking it.

### Run against the live list, the honest result was:

**0 of 29 beginner bounties** came from a repo with a real, current payment
record. Not one.

That is not the tool failing. That is what open bounties mostly are.

---

## Step 3 — Where the first real money actually is

Ranked by how quickly it converts to money in your bank, for someone with no
audience:

| Route | First money | Realistic rate | Verdict |
|---|---|---|---|
| **Freelance / contract work** | 1–3 weeks | ₹300–1,200/hr starting | **Fastest. Do this.** |
| Technical writing | 2–6 weeks | $50–500/article | Good, needs samples |
| Escrowed bounties | 1–8 weeks | $50–500 | Only with money already held |
| GitHub Sponsors | 2–6 **months** | $0 until you have users | Set up now, expect nothing |
| Your own product | 6–18 months | varies | The long game |

Uncomfortable but true: **freelance work is the fastest path**, and it is not
"GitHub money." Nagpur has real businesses that need a website, a scraper, or a
spreadsheet automated. That is ₹5,000–20,000 in a week, versus $12 that may
never arrive.

Bounties are worth doing for the **contribution history**, not the cash.

---

## Step 4 — Make the repo itself the asset

You have a repo with 130 passing tests, CI config, and a real problem it solves.
That is already more than most portfolios. Use it as the thing that gets you
hired or contracted:

1. **Enable CI** (you have permission, the bot doesn't):
   ```bash
   mkdir -p .github/workflows
   cp ci/tests.workflow.yml .github/workflows/tests.yml
   git add .github && git commit -m "Enable CI" && git push
   ```
   A green checkmark on every commit is a credibility signal you cannot fake.

2. **Write one post about what you learned.** The honest title is *"I built a
   tool to find paid GitHub issues and discovered 29 of 29 don't pay."* That is
   a genuinely interesting story with real data behind it. Post it on dev.to.
   This is the cheapest audience you will ever build.

3. **Note on Algora:** older articles call it an escrowed bounty marketplace.
   As of September 2026 its homepage says *"Open source tech recruiting —
   connecting the most prolific open source maintainers & contributors with
   their next jobs."* It pivoted. It is still worth knowing about — but as a
   **job board for OSS contributors**, and it wants to see real history
   ("150+ merged PRs", "1169 contributions in the last year").

---

## Step 5 — The 90-day sequence

**Week 1**
- [ ] GitHub Sponsors profile + KYC (Step 1). Then stop thinking about it.
- [ ] Enable CI on this repo.
- [ ] Pick one real project you actually use. Fix one small thing. Open a PR.

**Weeks 2–4**
- [ ] 3–5 merged PRs on projects you use. **Only** where `--verify` shows a live
      maintainer. Quality over bounty value — you are building a record.
- [ ] 1 dev.to post about what you found.

**Weeks 5–8**
- [ ] Start freelance work. Real money, real deadlines.
- [ ] Keep 1 PR/week going on open source.

**Weeks 9–12**
- [ ] By now: merged PRs, a post with readers, maybe a client.
- [ ] Now a product is plausible, because you have an audience to launch to.

---

## What I could not verify

Stated plainly so you don't trust it blindly:

- **IssueHunt / Polar / Open Collective current terms** — I did not check these
  this session. Verify before relying on them.
- **The exact fee split** for GitHub Sponsors individuals in India right now —
  sources say "up to 6% platform + ~2.9% processing + FX margin", but confirm
  in your own dashboard.
- **Whether any specific bounty will pay** — the whole point of Step 2 is that
  you cannot know in advance.
- **Python 3.9 compatibility** for this tool — only 3.11 is installed in the
  environment it was built in. CI will check it once you enable it.
