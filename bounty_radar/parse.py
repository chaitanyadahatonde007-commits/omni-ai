"""Extract and normalise monetary amounts out of free-text issue titles/bodies.

Bounty amounts on GitHub are written in a dozen different ways by a dozen
different communities. This module turns that mess into a single
:class:`Money` value with a USD estimate so results can be ranked.

Design notes
------------
* Fiat conversion rates are *static* and intentionally conservative. They are
  good enough to sort a list of bounties; they are NOT a live FX feed and the
  code says so wherever the estimate is surfaced.
* Crypto amounts are detected and flagged, but never converted. Guessing the
  price of a token from a regex would be worse than admitting we don't know.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# Static, rough, one-directional-to-USD. Documented as approximate on purpose.
FIAT_TO_USD: dict[str, float] = {
    "USD": 1.0,
    "USDC": 1.0,
    "USDT": 1.0,
    "CAD": 0.74,
    "AUD": 0.66,
    "NZD": 0.61,
    "GBP": 1.27,
    "EUR": 1.09,
    "CHF": 1.13,
    "SEK": 0.095,
    "NOK": 0.094,
    "DKK": 0.146,
    "PLN": 0.25,
    "CZK": 0.043,
    "INR": 0.012,
    "CNY": 0.14,
    "JPY": 0.0067,
    "KRW": 0.00073,
    "BRL": 0.18,
    "MXN": 0.054,
    "SGD": 0.74,
    "HKD": 0.128,
    "TWD": 0.031,
    "TRY": 0.029,
    "ZAR": 0.055,
    "NGN": 0.00065,
    "KES": 0.0077,
    "EGP": 0.021,
    "AED": 0.272,
    "SAR": 0.267,
    "ILS": 0.27,
    "PHP": 0.0175,
    "IDR": 0.000062,
    "THB": 0.029,
    "VND": 0.00004,
    "PKR": 0.0036,
    "BDT": 0.0084,
    "RUB": 0.011,
    "UAH": 0.024,
}

# Tokens we recognise as crypto. Detected, never priced.
CRYPTO_TOKENS: set[str] = {
    "ETH", "BTC", "SOL", "MATIC", "AVAX", "DOT", "LINK", "UNI", "AAVE",
    "ARB", "OP", "XTZ", "NEAR", "AIGEN", "MRG", "USDC", "DAI",
}
# USDC/DAI are stablecoins pegged ~1 USD, so they are fiat-like for ranking.
STABLECOINS: set[str] = {"USDC", "USDT", "DAI"}

_SYMBOL_TO_CODE: dict[str, str] = {
    # Longest first — alternation is order-sensitive.
    "US$": "USD",
    "HK$": "HKD",
    "NT$": "TWD",
    "NZ$": "NZD",
    "CA$": "CAD",
    "C$": "CAD",
    "AU$": "AUD",
    "A$": "AUD",
    "S$": "SGD",
    "R$": "BRL",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "CNY",  # ambiguous with JPY; CNY is the more common bounty currency
    "₹": "INR",
    "₩": "KRW",
    "₽": "RUB",
    "₺": "TRY",
    "₦": "NGN",
    "₱": "PHP",
    "₫": "VND",
    "₴": "UAH",
    "₪": "ILS",
    "฿": "THB",
}

# Symbol alternation, longest first so "US$" is not read as "$".
_SYM_ALT = "|".join(re.escape(s) for s in sorted(_SYMBOL_TO_CODE, key=len, reverse=True))

# Number with optional thousands separators and decimals: 1,000 / 1000 / 12.50
_NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"

# Order matters: longest / most specific patterns first.
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # "$50" "€1,000" "R$200" "US$25"
    (re.compile(rf"(?<![\w.])({_SYM_ALT})\s*({_NUM})"), "symbol_prefix"),
    # "50$" "1000 USD" "200 EUR" "5000 INR"
    (re.compile(rf"(?<![\w.])({_NUM})\s*(USD|USDC|USDT|CAD|AUD|NZD|GBP|EUR|CHF|SEK|NOK|DKK|"
                rf"PLN|CZK|INR|CNY|JPY|KRW|BRL|MXN|SGD|HKD|TWD|TRY|ZAR|NGN|KES|EGP|AED|SAR|"
                rf"ILS|PHP|IDR|THB|VND|PKR|BDT|RUB|UAH|ETH|BTC|SOL|MATIC|AVAX|DOT|LINK|UNI|"
                rf"AAVE|ARB|OP|XTZ|NEAR|AIGEN|MRG|DAI)\b", re.IGNORECASE), "code_suffix"),
    # "USD 50" / "bounty: 50 USD"
    (re.compile(rf"\b(USD|EUR|GBP|INR|CNY|JPY|KRW|BRL|ETH|BTC|SOL)\s+({_NUM})(?![\w.])",
                re.IGNORECASE), "code_prefix"),
    # "50$"
    (re.compile(rf"(?<![\w.])({_NUM})\s*([\$€£¥₹])"), "symbol_suffix"),
]

# Words that indicate a *range* rather than a fixed amount.
_RANGE_RE = re.compile(
    rf"(?<![\w.])([\$€£¥₹]?\s*{_NUM})\s*(?:-|–|~|to)\s*[\$€£¥₹]?\s*({_NUM})(?![\w.])"
)

# If one of these words sits immediately before the number, the "$" is almost
# certainly a variable/regex/shell marker, not a currency. "port $8080",
# "line $1080", "$HOME", "issue #$42".
_TECHNICAL_CONTEXT_RE = re.compile(
    r"\b(line|lines|port|ports|row|rows|col|cols|column|columns|step|steps|"
    r"version|build|size|sizes|byte|bytes|ms|sec|secs|second|seconds|index|"
    r"id|ids|number|no|count|addr|address|offset|width|height|px|rem|timeout|"
    r"sleep|delay|status|code|error|errno|exit|var|variable|env|arg|args|"
    r"param|params|page|pages|limit|weight|height|length|len|index)\b\s*[:#]?\s*$",
    re.IGNORECASE,
)

# Words that show the author actually intends to pay somebody.
_PAYOUT_INTENT_RE = re.compile(
    r"\b(bounty|bounties|reward|rewards|paid|pay|pays|paying|usd|compensat\w*|"
    r"prize|stipend|honorarium|honorarium|offer\w*|grant|funded)\b",
    re.IGNORECASE,
)

_CONTEXT_WINDOW = 24


@dataclass(frozen=True)
class Money:
    """A parsed bounty amount."""

    raw: str
    amount: float
    currency: str
    is_range: bool = False
    amount_high: Optional[float] = None

    @property
    def is_crypto(self) -> bool:
        return self.currency.upper() in CRYPTO_TOKENS and self.currency.upper() not in STABLECOINS

    @property
    def usd_estimate(self) -> Optional[float]:
        """Approximate USD value, or None for non-pegged crypto.

        For a range we use the *low* end. Claiming the high end of a range
        would systematically overstate what a newcomer can actually earn.
        """
        if self.is_crypto:
            return None
        rate = FIAT_TO_USD.get(self.currency.upper())
        if rate is None:
            return None
        return round(self.amount * rate, 2)


# Suffixes that mark an amount as a *valuation or a rate*, not a payout.
# "replaces $48,000/yr operator with $88 kit" — the bounty is $88.
_NON_PAYOUT_SUFFIX_RE = re.compile(
    r"^\s*(?:/\s*(?:yr|year|mo|month|hr|hour|day|week|annum)\b|"
    r"per\s+(?:year|month|hour|day|week|annum)\b|"
    r"(?:a|an)\s+year\b|annually\b|yearly\b|monthly\b|"
    r"\b(?:salary|wage|revenue|profit|valuation|market\s+cap|budget|"
    r"cost(?:s|ing)?|worth|price(?:d)?|saves?|saved|saving|replaces?|"
    r"replacing|reduce[sd]?|cut(?:s|ting)?|loss|losses|fee(?:s)?|"
    r"subscription|plan|tier|invoice(?:d)?|bill(?:ed)?|"
    r"total(?:s|led)?|spent|spending|raised|funding|funded|"
    r"budget(?:ed)?|estimate(?:d)?|quote(?:d)?|pricing|msrp|rrp|"
    r"gmv|arpu|mrr|arr)\b)",
    re.IGNORECASE,
)

_SUFFIX_WINDOW = 28

# Valuation words that sit *before* the amount: "Our MRR is $12,000".
_NON_PAYOUT_PREFIX_RE = re.compile(
    r"\b(?:mrr|arr|gmv|arpu|revenue|salary|wage|valuation|"
    r"market\s+cap(?:italisation|italization)?|"
    r"budget(?:ed)?|cost(?:s|ing)?|worth|invoice(?:d)?|total(?:s|led)?|"
    r"raised|funding|funded|saves?|saved|saving|replaces?|replacing|"
    r"reduce[sd]?|cut(?:s|ting)?|loss(?:es)?|profit(?:s)?|estimate(?:d)?|"
    r"quote(?:d)?|pricing|price|msrp|rrp|subscription|spend|spent|spending|"
    r"bill(?:ed)?|earn(?:s|ed|ings)?|paid\s+out)\b"
    r"\s*(?:is|are|was|were|of|:|=|at|to|by|~)?\s*$",
    re.IGNORECASE,
)


def _is_valuation(full_text: str, match_start: int, match_end: int) -> bool:
    """True if the amount is a rate or valuation rather than a payout.

    Checks both sides: "replaces $48,000/yr" (suffix) and
    "Our MRR is $12,000" (prefix).
    """
    if _NON_PAYOUT_SUFFIX_RE.match(full_text[match_end:match_end + _SUFFIX_WINDOW]):
        return True
    return bool(_NON_PAYOUT_PREFIX_RE.search(
        full_text[max(0, match_start - _CONTEXT_WINDOW):match_start]))


def _to_float(text: str) -> float:
    return float(text.replace(",", ""))


def _in_technical_context(full_text: str, match_start: int) -> bool:
    """True if the match is preceded by a word that makes "$N" not-money."""
    window = full_text[max(0, match_start - _CONTEXT_WINDOW):match_start]
    return bool(_TECHNICAL_CONTEXT_RE.search(window))


def _looks_like_year(amount: float, currency: str, full_text: str) -> bool:
    """Guard against "© 2024" / "since 2021" style bare 4-digit numbers."""
    if currency != "USD" or amount != int(amount):
        return False
    if not (1900 <= amount <= 2100):
        return False
    return not _PAYOUT_INTENT_RE.search(full_text)


def extract_money(text: str) -> Optional[Money]:
    """Pull the most plausible bounty amount out of a blob of text.

    Returns the *highest* fiat amount found. Titles like
    "[Bounty: $500] fix X, up to $2000 for a follow-up" should rank on the
    headline number, not on an incidental figure.
    """
    if not text:
        return None

    best: Optional[Money] = None

    for pattern, kind in _PATTERNS:
        for match in pattern.finditer(text):
            if kind == "symbol_prefix":
                symbol, num = match.group(1), match.group(2)
                currency = _SYMBOL_TO_CODE.get(symbol, "USD")
                amount = _to_float(num)
                raw = match.group(0)
                high = None
                is_range = False
            elif kind == "code_suffix":
                num, code = match.group(1), match.group(2)
                currency = code.upper()
                amount = _to_float(num)
                raw = match.group(0)
                high = None
                is_range = False
            elif kind == "code_prefix":
                code, num = match.group(1), match.group(2)
                currency = code.upper()
                amount = _to_float(num)
                raw = match.group(0)
                high = None
                is_range = False
            else:  # symbol_suffix
                num, symbol = match.group(1), match.group(2)
                currency = _SYMBOL_TO_CODE.get(symbol, "USD")
                amount = _to_float(num)
                raw = match.group(0)
                high = None
                is_range = False

            # --- reject things that are not money ---------------------------
            if amount <= 0 or amount > 1_000_000:
                continue
            if _in_technical_context(text, match.start()):
                continue
            if _looks_like_year(amount, currency, text):
                continue
            if _is_valuation(text, match.start(), match.end()):
                continue

            # A bare symbol with no explicit currency code and no payout
            # language is ambiguous. Require the number to at least sit in a
            # plausible bounty band so we don't rank on typos.
            explicit_code = kind in ("code_suffix", "code_prefix")
            if not explicit_code and not _PAYOUT_INTENT_RE.search(text):
                if not (5 <= amount <= 50_000):
                    continue

            usd_value = (
                round(amount * FIAT_TO_USD.get(currency, 0.0), 2)
                if (currency.upper() not in CRYPTO_TOKENS or currency.upper() in STABLECOINS)
                else 0.0
            )
            if best is None or (best.usd_estimate or 0) < usd_value:
                best = Money(raw=raw.strip(), amount=amount, currency=currency,
                             is_range=is_range, amount_high=high)

    if best is not None:
        return best

    # Fall back to a bare range like "500 - 1000 USD"
    range_match = _RANGE_RE.search(text)
    if range_match:
        low = _to_float(range_match.group(1).replace("$", "").strip())
        high = _to_float(range_match.group(2))
        if 0 < low <= high <= 1_000_000:
            return Money(raw=range_match.group(0).strip(), amount=low,
                         currency="USD", is_range=True, amount_high=high)

    return None


def has_bounty_keyword(text: str) -> bool:
    """True if the text mentions paying out, in any common phrasing."""
    lowered = text.lower()
    keywords = (
        "bounty", "reward", "paid issue", "we will pay", "we'll pay",
        "usd", "compensat", "sponsor this", "prize", "stipend", "honorarium",
        "paid pr", "$", "€", "£", "₹",
    )
    return any(k in lowered for k in keywords)
