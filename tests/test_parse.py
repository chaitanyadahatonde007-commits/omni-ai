import pytest

from bounty_radar.parse import extract_money, has_bounty_keyword, Money


@pytest.mark.parametrize("text,expected_amount,expected_currency", [
    ("[Bounty: $50] slugify() leaves double hyphens", 50.0, "USD"),
    ("Fix the race condition — $1,500 reward", 1500.0, "USD"),
    ("Reward: 200 EUR", 200.0, "EUR"),
    ("500 USD for a working patch", 500.0, "USD"),
    ("[bounty ¥200 · 仅支付宝] SandboxRunner adapter", 200.0, "CNY"),
    ("We will pay ₹5000 for this", 5000.0, "INR"),
    ("Paid issue: £75", 75.0, "GBP"),
    ("Bounty 0.5 ETH", 0.5, "ETH"),
    ("$25", 25.0, "USD"),
])
def test_extracts_common_formats(text, expected_amount, expected_currency):
    money = extract_money(text)
    assert money is not None, f"failed to parse: {text}"
    assert money.amount == expected_amount
    assert money.currency == expected_currency


def test_picks_the_highest_fiat_amount():
    # Headline number should win over an incidental one.
    money = extract_money("[Bounty: $500] fix X. Bonus $50 for tests. See line 42.")
    assert money is not None
    assert money.amount == 500.0


def test_ignores_line_numbers_and_ports():
    assert extract_money("crash at line 1080 when port $8080 is busy") is None


def test_no_money_in_plain_text():
    assert extract_money("Please fix the typo in the README") is None
    assert extract_money("") is None
    assert extract_money(None) is None


def test_usd_estimate_applies_fx_rate():
    money = extract_money("Reward: 100 EUR")
    assert money is not None
    assert money.usd_estimate == 109.0  # 100 * 1.09


def test_crypto_is_flagged_and_never_priced():
    money = extract_money("Bounty: 3 SOL")
    assert money is not None
    assert money.is_crypto is True
    assert money.usd_estimate is None


def test_stablecoin_is_treated_as_usd():
    money = extract_money("Pays 250 USDC")
    assert money is not None
    assert money.is_crypto is False
    assert money.usd_estimate == 250.0


def test_money_dataclass_is_immutable():
    m = Money(raw="$10", amount=10.0, currency="USD")
    with pytest.raises(Exception):
        m.amount = 20.0  # type: ignore[misc]


@pytest.mark.parametrize("text,expected", [
    # The Clawland-AI regression: bounty is $88, not the $48,000 it replaces.
    ("Create the kit documentation (replaces $48,000/yr operator with $88 kit).",
     88.0),
    ("Automate this — currently costs $2,500 per month in labour.", None),
    ("Our MRR is $12,000 and we will pay $300 for this fix.", 300.0),
    ("Saves $5,000/year. Bounty: $150.", 150.0),
    ("The subscription is $99/mo but the bounty is $400.", 400.0),
])
def test_ignores_valuations_and_rates(text, expected):
    money = extract_money(text)
    if expected is None:
        assert money is None, f"should not parse: {text} -> {money}"
    else:
        assert money is not None, f"failed to parse: {text}"
        assert money.amount == expected


def test_clawland_real_world_case():
    """Exact body text from Clawland-AI/clawland-kits#1."""
    body = ("## Description\nCreate the complete hardware kit documentation for the "
            "data center night shift monitoring scenario (replaces $48,000/yr "
            "operator with $88 kit).\n")
    money = extract_money(body)
    assert money is not None
    assert money.amount == 88.0
    assert money.usd_estimate == 88.0


@pytest.mark.parametrize("text,expected_amount,expected_currency", [
    ("docs(cli): Serbian quickstart (US$25 bounty proposal)", 25.0, "USD"),
    ("Pays HK$500 for the fix", 500.0, "HKD"),
    ("Reward S$300", 300.0, "SGD"),
    ("Bounty CA$1,200", 1200.0, "CAD"),
    ("A$75 please", 75.0, "AUD"),
])
def test_extracts_prefixed_dollar_variants(text, expected_amount, expected_currency):
    money = extract_money(text)
    assert money is not None, f"failed to parse: {text}"
    assert money.amount == expected_amount
    assert money.currency == expected_currency


@pytest.mark.parametrize("text,expected", [
    ("this is a bounty", True),
    ("we will pay for this", True),
    ("there is a reward", True),
    ("just a normal bug report", False),
])
def test_has_bounty_keyword(text, expected):
    assert has_bounty_keyword(text) is expected
