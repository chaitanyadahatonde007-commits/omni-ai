"""BROWSER AUTOMATION POWER TOOL — real Chrome automation (via Selenium).

OPTIONAL: OMNI auto-enables it when Chrome (or Edge/Chromium) is installed
and a matching Selenium Manager driver can be fetched. All actions are gated
by the permission system and printed live, because a browser doing things on
websites is visible power — treat it like a real person borrowing your mouse.
"""
from __future__ import annotations

import shutil

from omni.tools import register

_AVAILABLE = None


def is_available() -> bool:
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            import selenium  # noqa: F401
            browser = shutil.which("chrome") or shutil.which("chromium") or \
                shutil.which("chromium-browser") or shutil.which("msedge") or \
                shutil.which("microsoft-edge") or shutil.which("google-chrome")
            _AVAILABLE = browser is not None or __import__("os").path.exists(
                r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        except Exception:
            _AVAILABLE = False
    return _AVAILABLE


def _driver(ctx, headless: bool = False):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    opts = Options()
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    if headless:
        opts.add_argument("--headless=new")
    try:
        return webdriver.Chrome(options=opts)
    except Exception:
        pass
    for cand in ("msedge", "chromium", "brave"):
        binary = shutil.which(cand) or {
            "msedge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "chromium": None, "brave": None}.get(cand)
        if binary:
            try:
                opts.browser_name = None
                opts.binary_location = binary
                return webdriver.Chrome(options=opts)
            except Exception:
                continue
    raise RuntimeError(
        "browser automation could not start Chrome/Edge. Run /doctor for help, "
        "or install Chrome and retry.")


def _browse(ctx, url: str = "", headless: bool = False) -> str:
    """Open (or reuse) a real browser window controlled by OMNI."""
    # a live visible browser session is kept in ctx.state
    driver = ctx.get_state("browser")
    try:
        if driver is not None:
            driver.current_url  # sanity
    except Exception:
        driver = None
    if driver is None:
        if ctx.interactive_gate is not None:
            mode = "opening a REAL BROWSER window you can watch" if not headless else "headless browser"
            if not ctx.interactive_gate(f"Browser automation: {mode}", "y"):
                return "cancelled by user"
        driver = _driver(ctx, headless=headless)
        ctx.remember_state("browser", driver)
    if url:
        driver.get(url)
        from selenium.webdriver.support.ui import WebDriverWait
        try:
            WebDriverWait(driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == "complete")
        except Exception:
            pass
    text = _page_summary(driver)
    return f"[browser] page: {driver.current_url}\ntitle: {driver.title}\n\n{text}"


def _page_summary(driver, maxlen: int = 6000) -> str:
    try:
        txt = driver.execute_script(
            "return document.body ? document.body.innerText : ''") or ""
        txt = "\n".join(line.strip() for line in txt.splitlines() if line.strip())
        if len(txt) > maxlen:
            txt = txt[:maxlen] + f"\n…[page text truncated, {len(txt)-maxlen} more chars]"
        return txt
    except Exception:
        return "(could not read page text)"


def _click(ctx, description: str = "", index: int = 0) -> str:
    driver = _driver_or(ctx)
    from selenium.webdriver.common.by import By
    cands = []
    if description:
        cands = driver.find_elements(By.XPATH,
            f"//*[self::a or self::button or self::input[@type='submit'] or self::input[@type='button']]"
            f"[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
            f"'{description.lower()}')]")
    if not cands:
        cands = driver.find_elements(By.XPATH, "//a | //button | //input[@type='submit'] | //input[@type='button']")
    total = len(cands)
    if total == 0:
        return "no clickable element found on the page"
    i = min(max(int(index), 0), total - 1)
    el = cands[i]
    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    try:
        el.click()
    except Exception:
        driver.execute_script("arguments[0].click();", el)
    return _page_summary(driver) + f"\n[clicked element {i+1}/{total}]"


def _type_text(ctx, text: str, selector: str = "") -> str:
    driver = _driver_or(ctx)
    from selenium.webdriver.common.by import By
    if selector:
        els = driver.find_elements(By.CSS_SELECTOR, selector)
    else:
        els = [e for e in driver.find_elements(By.CSS_SELECTOR, "input[type='text'],input:not([type]),textarea,[contenteditable='true']")
               if e.is_displayed() and e.is_enabled()]
    if not els:
        return "no text field found — pass selector= (CSS like '#search') or # id"
    el = els[0]
    el.clear()
    from selenium.webdriver.common.keys import Keys
    el.send_keys(text)
    return f"typed {len(text)} chars into field (tag={el.tag_name}) — {len(els)} field(s) found"


def _press_key(ctx, key: str) -> str:
    driver = _driver_or(ctx)
    from selenium.webdriver.common.keys import Keys
    k = getattr(Keys, key.upper().replace(" ", "_"), None) or key
    from selenium.webdriver.common.by import By
    body = driver.find_element(By.TAG_NAME, "body")
    body.send_keys(k)
    return f"pressed {key}"


def _driver_or(ctx):
    driver = ctx.get_state("browser")
    if driver is None:
        raise RuntimeError("no browser open — call browse_open first")
    try:
        driver.current_url
    except Exception:
        raise RuntimeError("browser session is dead — call browse_open again")
    return driver


def _browse_act(ctx, action: str, description: str = "", selector: str = "",
                text: str = "", index: int = 0, url: str = "", key: str = "") -> str:
    a = action.lower()
    if a == "open":
        return _browse(ctx, url=url)
    if a == "refresh":
        d = _driver_or(ctx)
        d.refresh()
        return _page_summary(d) + "\n[refreshed]"
    if a == "back":
        d = _driver_or(ctx)
        d.back()
        return _page_summary(d) + "\n[back]"
    if a == "forward":
        d = _driver_or(ctx)
        d.forward()
        return _page_summary(d) + "\n[forward]"
    if a == "current":
        d = _driver_or(ctx)
        return _page_summary(d)
    if a == "read":
        d = _driver_or(ctx)
        try:
            from omni.tools.web import fetch_page
            return fetch_page(d.current_url)
        except Exception:
            return _page_summary(d, 30000)
    if a == "click":
        return _click(ctx, description=description, index=index)
    if a == "type":
        return _type_text(ctx, text, selector)
    if a == "press":
        return _press_key(ctx, key)
    if a == "close":
        d = _driver_or(ctx)
        d.quit()
        ctx.remember_state("browser", None)
        return "[browser closed]"
    if a == "screenshot":
        d = _driver_or(ctx)
        from omni import config
        p = config.workspace_dir() / "omni_browser_shot.png"
        d.save_screenshot(str(p))
        return f"screenshot saved to {p}"
    return f"unknown action '{action}'"


_browse_actions = {
    "open": "open a URL in the OMNI-controlled browser (reuses an open one)",
    "current": "return current page text + url", "refresh": "reload page",
    "back": "go back", "forward": "go forward", "read": "read full page text (uses article extractor)",
    "click": "click a link/button by visible text (description) or nth index", 
    "type": "type text into a field (selector optional CSS)", "press": "press a key (Enter, Escape…)",
    "screenshot": "save screenshot of current page", "close": "close the browser",
}

register(
    "browse", "Full browser automation — opens a REAL Chrome window and can click, type, navigate, read, screenshot. Use for JS-heavy sites search can't read (logins behind consent, dashboards, maps, social feeds). One action per call.",
    {"type": "object", "properties": {
        "action": {"type": "string", "enum": list(_browse_actions.keys()),
                   "description": "; ".join(f"{k}: {v}" for k, v in _browse_actions.items())},
        "url": {"type": "string"}, "description": {"type": "string", "description": "visible text of element to click"},
        "selector": {"type": "string", "description": "CSS selector of field to type into"},
        "text": {"type": "string", "description": "text to type"}, 
        "index": {"type": "integer", "description": "nth clickable element (0-based) if description empty"},
        "key": {"type": "string", "description": "key name for press"}},
     "required": ["action"]},
    risk="danger", category="browser",
)(_browse_act)
