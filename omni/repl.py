"""OMNI command-line REPL: commands, permission levels, scheduler."""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path

from rich.console import Console

from omni import config
from omni.setupwizard import run as run_wizard

BANNER = r"""
  ___  __  __ _ _   _ ___
 / _ \|  \/  (_) | | |_ _|
| | | | |\/| | | | | || |
| |_| | |  | | | |_| || |
 \___/|_|  |_|_|\___/|___|
"""


class ReplUI:
    def __init__(self, console=None):
        from omni.ui import RichUI
        self.inner = RichUI(console)
        self.console = self.inner.console
        self.tty = self.inner.tty
        self.on_alert = None  # set by REPL for scheduler alerts

    def status(self, m): return self.inner.status(m)
    def tool_done(self, n, r, ms=0): return self.inner.tool_done(n, r, ms)
    def confirm(self, m, default="y"): return self.inner.confirm(m, default)
    def answer(self, t): return self.inner.answer(t)
    def info(self, t): return self.inner.info(t)
    def alert(self, t, x): return self.inner.alert(t, x)
    def confirm_tool(self, t, a, r, w): return self.inner.confirm_tool(t, a, r, w)
    def step(self, title, body=""): return self.inner.step(title, body)
    def _read(self, prompt): return self.inner._read(prompt)


class REPL:
    def __init__(self, ui: ReplUI | None = None, console: Console | None = None):
        self.ui = ui or ReplUI(console or Console(highlight=False))
        self.ctx = None
        self.agent: Agent | None = None
        self.level = "guarded"
        self._sched_thread: threading.Thread | None = None
        self._sched_stop = threading.Event()

    # ----------------------------------------------------------- session ---
    def start_early(self) -> None:
        """Context, logging and gates — needed before any goal runs."""
        from omni.context import Context
        ws = config.workspace_dir()
        session_dir = config.home_dir() / "sessions"
        session_dir.mkdir(parents=True, exist_ok=True)
        self.ctx = Context(ws, session_dir)
        logfile = config.session_log_path()
        self.ctx.log_path = logfile
        logging.basicConfig(filename=str(logfile), level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
        self.ctx.interactive_gate = self.ui.confirm
        self.ctx.auto_yes = os.environ.get("OMNI_AUTO_YES") == "1"

    def start(self) -> None:
        self.start_early()
        self.ui.console.print(BANNER, style="bold cyan")
        self.ui.console.print("[bold]OMNI[/bold] — internet agent · coder · automator  [dim](free brains & tools)[/dim]\n")
        ws = self.ctx.workspace
        logfile = self.ctx.log_path
        self.ui.console.print(f"[dim]workspace:[/dim] {ws}")
        self.ui.console.print(f"[dim]session log:[/dim] {logfile}\n")
        self._print_rules()

        self._start_scheduler()
        try:
            while True:
                try:
                    raw = self.ui.console.input("[bold cyan]omni>[/bold cyan] ")
                except (EOFError, KeyboardInterrupt):
                    self.ui.console.print("\n[dim]bye. run `omni` anytime.[/dim]")
                    break
                cmd = raw.strip()
                if not cmd:
                    continue
                low = cmd.lower()
                if low in ("exit", "quit", "q", "/exit", "/quit"):
                    break
                if low in ("help", "/help", "h", "?"):
                    self._cmd_help()
                    continue
                if low in ("clear", "cls"):
                    os.system("cls" if os.name == "nt" else "clear")
                    continue
                if cmd.startswith("/"):
                    self._command(cmd[1:].strip())
                else:
                    self._run_goal(cmd)
        finally:
            self._sched_stop.set()
            self._stop_browser()

    def _print_rules(self) -> None:
        lvl = self.level
        txt = {
            "guarded": "guarded: safe read-only actions auto-run · anything powerful or changing asks you",
            "cautious": "cautious: every action asks you",
            "trusted": "trusted: OMNI runs powerful actions freely · destructive ones still ask",
        }[lvl]
        self.ui.console.print(f"[yellow]permissions:[/yellow] {txt}")
        self.ui.console.print("[dim]type 'help' for commands[/dim]\n")

    # ------------------------------------------------------------ brains ----
    def ensure_brain(self) -> bool:
        if self.agent is not None:
            return True
        from omni import providers
        cfg = config.get("brain", {}) or {}
        p, m = None, None
        self.ui.status("connecting to a free AI brain…")
        if cfg.get("provider"):
            try:
                got = providers.pick_first_working(provider=cfg["provider"], max_models=3)
                if got:
                    p, m = got
            except Exception:
                p, m = None, None
        if not p:
            got = providers.pick_first_working()
            if got:
                p, m = got
        if not p:
            self.ui.console.print(
                "[bold red]No AI brain connected.[/bold red] OMNI needs ONE free key "
                "(or local Ollama) to think.\n")
            if self.ui.tty:
                run_wizard(self.ui)
            got = providers.pick_first_working()
            if not got:
                self.ui.console.print("[red]Still offline. Run /setup anytime.[/red]")
                return False
            p, m = got
        brain = config.get("brain", {})
        brain["provider"], brain["model"] = p, m
        config.set_config("brain", brain)
        self.level = config.get("permission_level", "guarded")
        self.ui.console.print(f"[bold green]✓ brain online:[/bold green] "
                              f"{providers.provider_label(p, m)}")
        self._rebuild_agent()
        return True

    def _rebuild_agent(self) -> None:
        if not self.agent:
            brain = config.get("brain", {}) or {}
            if not brain.get("provider"):
                return
        from omni import providers
        brain = config.get("brain", {}) or {}
        self.agent = Agent(self.ctx, self.ui,
                           provider=brain.get("provider", ""),
                           model=brain.get("model", ""),
                           level=self.level,
                           workspace=str(self.ctx.workspace),
                           shell=self.ctx.shell_style)
        self.agent.level = self.level

    def _run_goal(self, text: str) -> None:
        if not self.ensure_brain():
            return
        self.ui.status("working…")
        try:
            reply = self.agent.run(text)
        except KeyboardInterrupt:
            reply = "(interrupted — you pressed Ctrl+C)"
        self.ui.answer(reply)

    # ------------------------------------------------------------ command ----
    def _command(self, cmdline: str) -> None:
        parts = cmdline.split()
        cmd = parts[0].lower() if parts else ""
        arg = " ".join(parts[1:]).strip()
        try:
            handler = getattr(self, f"_cmd_{cmd.replace('-', '_')}")
        except AttributeError:
            self.ui.console.print(f"[red]unknown command:[/red] /{cmd}  (type help)")
            return
        handler(arg)

    def _cmd_help(self, _=""):
        self.ui.console.print("""\
[bold]COMMANDS[/bold]
  help / ?                     show this
  exit / quit                  leave OMNI
  /trust | /guard | /cautious  permission level (cautious=ask everything)
  /brain                       show active brain + all free options
  /setup                       connect a free AI key (Gemini/Groq/OpenRouter/GitHub/Ollama)
  /model <provider>            switch brain (e.g. /model gemini) — lists options
  /workspace <folder>          show/change where OMNI creates files
  /memory <text>               save a fact to long-term memory (/forget <text>)
  /schedules                   list reminders & scheduled tasks
  /cancel <id>                 cancel a reminder/schedule
  /doctor                      diagnose: network, keys, Chrome, Ollama…
  /logs                        show this session's log location
  /status                      show session info

[bold]PERMISSIONS[/bold]
  safe actions (search, read pages/files) run automatically.
  code/shell/browser/email/writes ask you: y=allow once · a=always allow ·
  x=never. /trust lets OMNI run powerful actions freely this session —
  destructive commands & outside-workspace writes STILL ask.

[bold]EXAMPLES[/bold]
  omni> research the best free AI image tools of this month and save a report
  omni> make a python script that downloads today's top 10 GitHub repos
  omni> find if any scholarship deadlines are this month for Indian students
  omni> remind me in 10 minutes to drink water""")

    def _cmd_trust(self, _=""):
        self._set_level("trusted")

    def _cmd_guard(self, _=""):
        self._set_level("guarded")

    def _cmd_cautious(self, _=""):
        self._set_level("cautious")

    def _set_level(self, level: str) -> None:
        self.level = level
        if self.agent:
            self.agent.level = level
        self.ui.console.print(f"[yellow]permission level →[/yellow] {level} "
                              "(this session)")
        config.set_config("permission_level", level)

    def _cmd_brain(self, _=""):
        from omni import providers
        self.ui.console.print("[bold]active brain:[/bold] " +
                              (providers.provider_label(config.get("brain", {}).get("provider", "?"),
                                                        config.get("brain", {}).get("model", ""))
                               if config.get("brain", {}).get("provider") else "none"))
        self.ui.console.print("\n[bold]configured free options:[/bold]")
        self.ui.console.print(providers.list_providers_status())

    def _cmd_model(self, arg: str):
        from omni import providers
        if not arg:
            self._cmd_brain("")
            return
        prov = arg.strip().lower()
        if prov not in providers.FREE_CANDIDATES:
            self.ui.console.print(f"[red]unknown provider '{prov}'. one of: "
                                  + ", ".join(providers.FREE_CANDIDATES) + "[/red]")
            return
        secrets = config.load_secrets()
        need = providers.KEY_ENV[prov]
        if need and not secrets.get(need) and not self.ui.tty:
            self.ui.console.print(f"[red]missing key {need}[/red] — run /setup")
            return
        if need and not secrets.get(need):
            self.ui.console.print(f"[yellow]{prov} needs {need}.[/yellow] run /setup to add it.")
            return
        if self.ui.tty:
            cands = providers.FREE_CANDIDATES[prov]
            print(f"[bold]{prov}[/bold] candidate free models:")
            for i, m in enumerate(cands, 1):
                print(f"  {i}) {m}")
            pick = input("> pick model (Enter = first): ").strip()
            try:
                model = cands[int(pick) - 1] if pick else cands[0]
            except Exception:
                model = cands[0]
        else:
            model = providers.FREE_CANDIDATES[prov][0]
        self.ui.status(f"testing {prov} · {model}…")
        got = providers.pick_first_working(provider=prov, max_models=3)
        if not got:
            self.ui.console.print(f"[red]could not connect via {prov} — run /doctor[/red]")
            return
        brain = config.get("brain", {})
        brain["provider"], brain["model"] = got
        config.set_config("brain", brain)
        self._rebuild_agent()
        self.ui.console.print(f"[bold green]✓ brain switched:[/bold green] "
                              f"{providers.provider_label(*got)}")

    def _cmd_setup(self, _=""):
        run_wizard(self.ui)
        if config.get("brain", {}).get("provider"):
            self._rebuild_agent()

    def _cmd_workspace(self, arg: str):
        if arg:
            p = Path(arg).expanduser()
            try:
                p.mkdir(parents=True, exist_ok=True)
                config.set_config("workspace", str(p.resolve()))
                self.ctx.workspace = p.resolve()
            except Exception as e:
                self.ui.console.print(f"[red]{e}[/red]")
                return
        self.ui.console.print(f"workspace: [cyan]{self.ctx.workspace}[/cyan]")

    def _cmd_status(self, _=""):
        self.ui.console.print(
            f"brain: {config.get('brain', {}).get('provider')} · "
            f"{config.get('brain', {}).get('model', '')}\n"
            f"level: {self.level}\n"
            f"workspace: {self.ctx.workspace}\n"
            f"shell: {self.ctx.shell_style}")

    def _cmd_logs(self, _=""):
        print(f"session log: {self.ctx.log_path}\nlogs folder: {config.logs_dir()}")

    def _cmd_doctor(self, _=""):
        self._doctor()

    def _cmd_memory(self, text: str):
        if text:
            from omni.tools.memory_tool import remember_text
            print(remember_text(self.ctx, text))
        else:
            self._cmd_recall("")

    def _cmd_recall(self, q: str):
        from omni.tools.memory_tool import recall_text
        print(recall_text(self.ctx, q, limit=20))

    def _cmd_forget(self, q: str):
        from omni.tools.memory_tool import forget_text
        print(forget_text(self.ctx, q))

    def _cmd_schedules(self, _=""):
        from omni.tools.automation import _list_schedules
        print(_list_schedules(self.ctx))

    def _cmd_cancel(self, arg: str):
        from omni.tools.automation import _cancel_schedule
        print(_cancel_schedule(self.ctx, arg or ""))

    def _cmd_unblock(self, arg: str):
        from omni import permissions
        perms = config.load_permissions()
        for lst in (perms.get("deny", []), perms.get("allow_always", [])):
            if arg in lst:
                lst.remove(arg)
        config.save_permissions()
        self.ui.console.print(f"cleared saved rules for '{arg}'")

    # ----------------------------------------------------------- doctor ----
    def _doctor(self, _="") -> None:
        c = self.ui.console
        c.print("[bold]OMNI doctor[/bold]\n")
        def ok(msg): c.print(f"  [green]✓[/green] {msg}")
        def bad(msg): c.print(f"  [red]✗[/red] {msg}")
        def note(msg): c.print(f"  [yellow]·[/yellow] {msg}")
        try:
            import sys as _s
            ok(f"python {_s.version.split()[0]}")
            for mod in ("rich", "requests", "bs4", "trafilatura"):
                __import__(mod)
                ok(f"library {mod}")
        except ImportError as e:
            bad(f"missing library: {e} — run: pip install -r requirements.txt")
        from omni import providers
        import requests
        try:
            r = requests.head("https://www.google.com", timeout=5)
            ok("internet reachable")
        except Exception as e:
            bad(f"internet unreachable ({e})")
        cfg = providers.configured_providers()
        note(f"keys present for: {', '.join(cfg) or 'none — run /setup'}")
        if self.agent:
            ok(f"brain: {providers.provider_label(self.agent.last_provider, self.agent.last_model)}")
        from omni.tools.browser import is_available
        if is_available():
            ok("Chrome/Edge found")
            try:
                import selenium  # noqa: F401
                ok("selenium installed — full browser control enabled")
            except ImportError:
                note("selenium not installed — browser automation disabled. run: pip install selenium")
        else:
            note("Chrome/Edge not found — browse power limited to open_url")
        try:
            import urllib.request as _u
            with _u.urlopen("http://localhost:11434/api/tags", timeout=2):
                ok("local Ollama running")
        except Exception:
            note("Ollama not running (optional, for 100% private mode)")

    # --------------------------------------------------------- scheduler ----
    def _start_scheduler(self) -> None:
        self._sched_thread = threading.Thread(target=self._sched_loop, daemon=True)
        self._sched_thread.start()

    def _sched_loop(self) -> None:
        from omni.tools.automation import due_items
        from omni.tools.automation import _load_schedules  # noqa: F401
        while not self._sched_stop.is_set():
            try:
                for item in due_items():
                    what = item.get("message") or item.get("task") or "scheduled item"
                    self.ui.alert("⏰ OMNI reminder",
                                  f"{what}\n[dim](set for {item.get('at', '?')})[/dim]")
                    try:
                        from omni.tools.automation import _notify
                        _notify(self.ctx, what[:200])
                    except Exception:
                        pass
                    if item.get("type") == "task" and self.agent:
                        t = threading.Thread(target=self._run_goal, args=(item["task"],),
                                             daemon=True)
                        t.start()
            except Exception:
                pass
            self._sched_stop.wait(20)

    def _stop_browser(self) -> None:
        try:
            drv = self.ctx.get_state("browser")
            if drv is not None:
                drv.quit()
        except Exception:
            pass
