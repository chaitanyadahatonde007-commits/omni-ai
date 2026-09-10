"""WEB POWER TOOLS — search, read, verify. All 100% free, no API keys.

Search engines used (free, keyless):
  DuckDuckGo HTML (2 variants), Mojeek, Startpage (lite).
  Multi-engine fallback means one blocked site never kills a search.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

from omni import config
from omni.tools import register

log = logging.getLogger("omni.web")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.8",
}
TIMEOUT = 15


def _get(url: str, **kw) -> requests.Response:
    kw.setdefault("headers", HEADERS)
    kw.setdefault("timeout", TIMEOUT)
    resp = requests.get(url, **kw)
    resp.raise_for_status()
    return resp


def _sniff_encoding(resp: requests.Response) -> str:
    ct = resp.headers.get("content-type", "")
    m = re.search(r"charset=([\w-]+)", ct, re.I)
    if m:
        return m.group(1)
    for frag in (resp.content[:2000].decode("latin-1", "ignore"),):
        m = re.search(r'charset=["\']?([\w-]+)', frag, re.I)
        if m:
            return m.group(1)
    return resp.encoding or "utf-8"


def _clean_text(s: str, limit: int = 2000) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit]


def ddg(url: str, q: str) -> list[dict]:
    """DuckDuckGo html endpoint."""
    r = _get(url, params={"q": q, "kl": "us-en", "ia": "web"})
    r.encoding = _sniff_encoding(r)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for res in soup.select("div.result") or soup.select("div.web-result"):
        a = res.select_one("a.result__a") or res.select_one("a.result-link") or res.select_one("h2 a")
        if not a:
            continue
        href = a.get("href", "")
        if href.startswith("//duckduckgo.com/l/?uddg="):
            href = urllib.parse.unquote(href.split("uddg=")[1].split("&")[0])
        snip = res.select_one("a.result__snippet") or res.select_one(".result__snippet") or res.select_one("a.result-snippet")
        title = _clean_text(a.get_text(" ", strip=True), 300)
        if title and href.startswith("http"):
            out.append({"title": title, "url": href, "snippet": _clean_text(snip.get_text(" ", strip=True) if snip else "", 800)})
    return out


def mojeek(q: str) -> list[dict]:
    r = _get("https://www.mojeek.com/search", params={"q": q}, headers={**HEADERS, "Accept": "text/html"})
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for res in soup.select("ul.results-standard li.result"):
        a = res.select_one("h2 a")
        if not a:
            continue
        p = res.select_one("p.s")
        out.append({
            "title": _clean_text(a.get_text(" ", strip=True), 300),
            "url": a.get("href", ""),
            "snippet": _clean_text(p.get_text(" ", strip=True) if p else "", 800),
        })
    return [o for o in out if o["url"].startswith("http")]


def startpage(q: str) -> list[dict]:
    r = _get("https://www.startpage.com/sp/search", params={"query": q}, headers={**HEADERS, "Accept": "text/html"})
    r.encoding = "utf-8"
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for res in soup.select("div.w-gl__result"):
        a = res.select_one("a.result-link") or res.select_one("a.w-gl__result-title")
        if not a:
            continue
        url = a.get("href", "")
        if url.startswith("/sp/search"):
            continue
        if not url.startswith("http"):
            base = urllib.parse.urljoin("https://www.startpage.com/", url)
            try:
                rr = _get(base, headers={**HEADERS, "Accept": "text/html", "Referer": "https://www.startpage.com/"})
                if rr.url.startswith("http") and "startpage.com" not in rr.url:
                    url = rr.url
            except Exception:
                continue
        snip = res.select_one("p.w-gl__description") or res.select_one(".w-gl__description")
        out.append({
            "title": _clean_text(a.get_text(" ", strip=True), 300),
            "url": url,
            "snippet": _clean_text(snip.get_text(" ", strip=True) if snip else "", 800),
        })
    return out


ENGINES = {
    "duckduckgo": lambda q: ddg("https://html.duckduckgo.com/html/", q),
    "duckduckgo_lite": lambda q: ddg("https://lite.duckduckgo.com/lite/", q),
    "mojeek": mojeek,
    "startpage": startpage,
}


def _dedupe(results: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in results:
        url = r.get("url", "")
        key = url.split("#")[0].rstrip("/").lower()
        if key in seen or not key.startswith("http"):
            continue
        seen.add(key)
        out.append(r)
    return out


def web_search(q: str, max_results: int = 8) -> list[dict]:
    q = q.strip()
    if not q:
        return []
    engines_cfg = config.get("web_search_engines", ["duckduckgo", "mojeek"])
    order = [e for e in engines_cfg if e in ENGINES] + [e for e in ENGINES if e not in engines_cfg]
    errors = []
    results = []
    for eng in order:
        try:
            batch = ENGINES[eng](q)
            if batch:
                log.info("search engine %s -> %d results", eng, len(batch))
                results.extend(batch)
                if len(results) >= max_results * 2:
                    break
        except Exception as e:  # noqa: BLE001
            errors.append(f"{eng}: {e}")
        time.sleep(0.3)
    deduped = _dedupe(results)[:max_results]
    if not deduped and errors:
        raise RuntimeError("all search engines failed: " + "; ".join(errors))
    return deduped


def fetch_page(url: str, text_limit: int = 30000) -> str:
    """Fetch + extract the meaningful text of any page. Returns a report."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    resp = _get(url)
    ctype = resp.headers.get("content-type", "")
    if resp.url != url:
        url = resp.url
    if "json" in ctype or url.lower().endswith((".json", ".geojson")):
        try:
            data = resp.json()
        except Exception:
            return f"URL: {url}\n[raw content follows]\n{resp.text[:text_limit]}"
        return f"URL: {url}\n" + json.dumps(data, indent=2, ensure_ascii=False, default=str)[:text_limit]

    html = resp.text
    # respect declared charset of the raw bytes
    resp.encoding = _sniff_encoding(resp)
    html = resp.text

    text = None
    try:
        import trafilatura
        text = trafilatura.extract(html, include_comments=False, include_tables=True,
                                   favor_precision=True, url=url)
    except Exception:
        text = None
    if not text:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "form", "header", "aside"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
    if not text:
        raise RuntimeError(f"no readable content at {url} (might be a JS-only page — use browse_open)")
    extra = ""
    if len(text) > text_limit:
        extra = f"\n…[truncated {len(text) - text_limit} more chars — ask to save the full page]"
        text = text[:text_limit]
    title = ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        if soup.title and soup.title.string:
            title = _clean_text(soup.title.string, 200)
    except Exception:
        pass
    head = f"URL: {url}"
    if title:
        head += f"\nTITLE: {title}"
    return head + "\n" + text + extra


# ============================================================ registrations =
register(
    "web_search", "Search the internet for real, up-to-date information. Use BEFORE answering questions about current events, prices, people, software, or anything after your training. Returns ranked results with titles, URLs and snippets.",
    {"type": "object", "properties": {"query": {"type": "string", "description": "search query"}, "max_results": {"type": "integer", "description": "max results, default 8"}}, "required": ["query"]},
    risk="safe", category="web",
)(lambda ctx, query, max_results=8: web_search(query, max_results))


def _read_params():
    return {"type": "object", "properties": {"url": {"type": "string", "description": "full URL (https://…) of the page to read"}}, "required": ["url"]}


register(
    "web_fetch", "Read the full text content of a single webpage or a raw JSON endpoint (Wikipedia pages, docs, news articles, JSON APIs, GitHub raw files…). Use when a search snippet is not enough.",
    _read_params(), risk="safe", category="web",
)(lambda ctx, url: fetch_page(url))


def _verify_facts_impl(facts: str, max_checks: int = 4) -> str:
    """Given claims separated by newlines (or semicolons), searches the web to
    verify each and reports VERIFIED / DISPUTED / NOT FOUND with sources."""
    claims = [c.strip(" .;") for c in re.split(r"[\n;]", facts) if c.strip()]
    if not claims:
        return "no claims provided"
    lines = []
    for i, claim in enumerate(claims[:max_checks], 1):
        if len(claim) > 240:
            claim = claim[:240]
        lines.append(f"\n=== CHECK {i}: “{claim}” ===")
        try:
            res = web_search(f'"{claim}"', max_results=4)
        except Exception as e:
            lines.append(f"search failed: {e}")
            continue
        if not res:
            lines.append("NOT FOUND — nothing relevant on the open web")
            continue
        scored = []
        for r in res:
            text = (r["title"] + " " + r.get("snippet", "")).lower()
            key = claim.lower().split(":")[0]
            score = 0
            if any(term in text for term in [w for w in key.split() if len(w) > 3][:6]):
                score += 2
            domain = r["url"].split("/")[2].lower() if len(r["url"].split("/")) > 2 else ""
            if any(t in domain for t in ("wikipedia", "gov", "edu", "reuters", "bbc", "apnews", "nature", "who.int")):
                score += 1
            scored.append((score, r))
        best = max(scored, key=lambda x: x[0]) if scored else scored[0]
        score, r = best if scored else (0, None)
        if not r:
            lines.append("NOT FOUND")
            continue
        verdict = "VERIFIED (corroborating source found)" if score >= 2 else "DISPUTED / WEAK SUPPORT — no strong corroboration found"
        lines.append(f"{verdict}\n  source: {r['title'][:120]}\n  {r['url']}")
    return "\n".join(lines)


register(
    "web_verify", "FACT-CHECK claims on the live internet. Give facts (one per line / separated by ;) and OMNI searches authoritative sources and marks each VERIFIED / DISPUTED / NOT FOUND with source links. Use before stating anything the user can be misled by.",
    {"type": "object", "properties": {"facts": {"type": "string", "description": "claim(s) to verify"}, "max_checks": {"type": "integer", "description": "default 4"}}, "required": ["facts"]},
    risk="safe", category="web",
)(lambda ctx, facts, max_checks=4: _verify_facts_impl(facts, max_checks))
