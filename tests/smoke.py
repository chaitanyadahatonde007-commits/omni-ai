"""OMNI smoke tests — run offline:  python tests/smoke.py
Covers tool registration, permission engine, file/code/automation tools and
graceful AI-provider failure. Network tools are listed but not live-tested
(sandbox may have no internet)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok  " if cond else " FAIL ") + name + (f"  — {detail}" if detail and not cond else ""))


class StubUI:
    """Auto-approve UI for tests."""
    tty = False

    def __init__(self, approve=True):
        self.approve = approve
        self.asked = []

    def status(self, m): pass
    def info(self, m): pass
    def tool_done(self, n, r, ms=0): pass
    def answer(self, t): pass
    def confirm(self, prompt, default="y"):
        self.asked.append(prompt)
        return self.approve
    def confirm_tool(self, t, args, risk, why):
        self.asked.append(f"tool:{t.name}")
        if risk == "critical":
            return self.approve, ""
        return self.approve, ""


def make_ctx():
    tmp = Path(tempfile.mkdtemp(prefix="omni_test_"))
    from omni.context import Context
    ctx = Context(tmp, tmp)
    ctx.interactive_gate = lambda p, d="n": True
    ctx.auto_yes = True
    return ctx, tmp


def main():
    print("== OMNI smoke tests ==")
    os.environ.setdefault("OMNI_HOME", tempfile.mkdtemp(prefix="omni_home_"))
    from omni import config
    from omni.context import Context
    from omni.tools import tools, get
    from omni import permissions
    from omni.tools import CRITICAL, DANGER, SAFE

    registry = tools()
    check("tool registry loads 24+ tools", len(registry) >= 24, str(len(registry)))
    for want in ("web_search", "web_fetch", "web_verify", "write_file", "read_file",
                 "list_files", "find_files", "run_python", "run_file", "run_shell",
                 "browse", "open_url", "machine_control", "make_csv", "make_json",
                 "send_email", "notify", "remind_me", "schedule_task", "list_schedules",
                 "cancel_schedule", "remember", "recall", "forget"):
        check(f"registered: {want}", want in registry)

    # -- schema sanity ----------------------------------------------------
    ok = True
    for t in registry.values():
        params = t.parameters or {}
        if params.get("type") != "object":
            ok = False
            print(f"   bad schema on {t.name}: {params}")
    check("all tools have object schemas", ok)

    # -- permission engine ------------------------------------------------
    tool_w = get("write_file")      # danger
    tool_r = get("web_search")      # safe
    tool_c = get("machine_control") # critical
    check("guarded: safe auto", permissions.decision(tool_r, "guarded") == "allow")
    check("guarded: danger asks", permissions.decision(tool_w, "guarded") == "ask")
    check("guarded: critical asks", permissions.decision(tool_c, "guarded") == "ask")
    check("trusted: danger allows", permissions.decision(tool_w, "trusted") == "allow")
    check("trusted: critical asks", permissions.decision(tool_c, "trusted") == "ask")
    check("cautious: safe asks", permissions.decision(tool_r, "cautious") == "ask")
    permissions.remember_always("web_search", allow=True)
    perms = config.load_permissions()
    check("allow_always persisted", "web_search" in perms["allow_always"])
    permissions.remember_always("web_search", allow=False)
    check("deny wins over allow", permissions.decision(tool_r, "guarded") == "deny")
    permissions.remember_always("web_search", allow=True)
    # cleanup deny so later tests unaffected
    perms = config.load_permissions()
    perms["deny"] = [d for d in perms["deny"] if d != "web_search"]
    config.save_permissions()

    # -- file + python tools ----------------------------------------------
    ctx, tmp = make_ctx()
    out = get("write_file").fn(ctx, path=str(tmp / "hello.py"),
                               content="print('hello from omni')\nresult = 6 * 7\n")
    check("write_file ok", "wrote" in out, out)
    out = get("read_file").fn(ctx, path=str(tmp / "hello.py"))
    check("read_file ok", "hello from omni" in out, out[:80])
    out = get("run_python").fn(ctx, code="import os\nprint('cwd', os.getcwd())\nresult={'n': 5}")
    check("run_python ran", "RESULT VALUE" in out and "5" in out, out[:200])
    check("run_python sandbox cwd", "cwd" in out)
    out = get("run_python").fn(ctx, code="raise ValueError('boom')")
    check("run_python captures error", "ValueError" in out and "boom" in out, out[:200])
    out = get("run_file").fn(ctx, path=str(tmp / "hello.py"))
    check("run_file executes", "hello from omni" in out, out[:120])

    # -- workspace path guard ---------------------------------------------
    outside = Path(tempfile.mkdtemp(prefix="outside_")) / "secret.txt"
    outside.write_text("x")
    esc = get("read_file").escalate
    risk, why = esc(ctx, {"path": str(outside)})
    check("read outside workspace escalates", risk == "changes", f"{risk} {why}")
    risk, why = esc(ctx, {"path": str(Path.home() / ".ssh" / "id_rsa")})
    check("ssh file critical", risk == "critical", f"{risk} {why}")

    # -- automations -------------------------------------------------------
    out = get("remind_me").fn(ctx, when="in 0 minutes", message="drink water")
    check("remind_me ok", "✓" in out, out)
    out = get("remind_me").fn(ctx, when="in 60 minutes", message="walk the dog")
    from omni.tools.automation import due_items, _load_schedules
    due = due_items()
    check("scheduler fires due items", any("drink water" in (d.get("message") or "") for d in due))
    out = get("list_schedules").fn(ctx)
    check("list_schedules lists pending", "walk the dog" in out, out[:100])
    out = get("cancel_schedule").fn(ctx, "walk the dog")
    check("cancel_schedule", "cancelled" in out, out)
    out = get("make_csv").fn(ctx, path=str(tmp / "t.csv"), headers="a,b", rows="1,2\n3,4")
    check("make_csv", "t.csv" in out, out)
    check("csv exists", (tmp / "t.csv").exists())

    # -- memory ------------------------------------------------------------
    out = get("remember").fn(ctx, text="user likes chai", tag="preference")
    check("remember ok", "remembered" in out, out)
    out = get("recall").fn(ctx, query="chai")
    check("recall finds", "chai" in out, out)
    out = get("forget").fn(ctx, query="chai")
    check("forget ok", "forgot" in out, out)

    # -- provider layer offline -------------------------------------------
    from omni import providers
    cfg = providers.configured_providers()
    check("ollama always listed as option", "ollama" in cfg, str(cfg))
    check("no gemini/groq keys in sandbox",
          "gemini" not in cfg and "groq" not in cfg, str(cfg))
    check("pick_first_working returns None offline",
          providers.pick_first_working() is None)

    # -- notify & email offline fallback ----------------------------------
    out = get("notify").fn(ctx, message="test")
    check("notify returns a status string", isinstance(out, str) and len(out) > 0, out[:80])
    # -- web tools wired with ctx-first signature (degrade offline) --------
    from omni.tools.web import web_search as ws_fn
    got_ok = False
    try:
        res = ws_fn("test query")
        got_ok = isinstance(res, list)
    except Exception as e:
        got_ok = "engine" in str(e).lower() or "search" in str(e).lower()
    check("web_search degrades gracefully offline", got_ok)
    from omni.tools.web import fetch_page
    got_ok = False
    try:
        fetch_page("http://127.0.0.1:1/none")
    except Exception as e:
        got_ok = True
    check("web_fetch errors cleanly", got_ok)

    # -- permissions gate path in agent._execute_tool ----------------------
    from omni.agent import Agent
    ui = StubUI()
    ctx2, _ = make_ctx()
    ag = Agent(ctx2, ui, provider="x", model="y", level="trusted")
    res = ag._execute_tool("read_file", {"path": str(tmp / "hello.py")})
    check("agent trusted executes safe tool", "hello from omni" in res, res[:100])
    res = ag._execute_tool("unknown_tool_xyz", {})
    check("agent handles unknown tool", "unknown tool" in res, res[:80])
    res = ag._execute_tool("run_python", {"code": "result=1+1"})
    check("agent trusted runs python", "2" in res, res[:100])
    # guarded + deny-ui -> refusal flows back to model
    ui2 = StubUI(approve=False)
    ag2 = Agent(ctx2, ui2, provider="x", model="y", level="guarded")
    res = ag2._execute_tool("write_file", {"path": str(tmp / "no.txt"), "content": "x"})
    check("guarded denial returns refusal", "DENIED" in res, res[:100])

    # -- reminder due-item firing + notify mock ----------------------------
    print()
    if FAIL:
        print(f"{len(FAIL)} FAILED: {FAIL}")
        sys.exit(1)
    print(f"ALL {len(PASS)} CHECKS PASSED ✓")


if __name__ == "__main__":
    main()
