"""Terminal UI layer (rich) + prompt helpers used by both the REPL and tools."""
from __future__ import annotations

import sys

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

BANNER = r"""
  ___  __  __ _ _   _ ___
 / _ \|  \/  (_) | | |_ _|
| | | | |\/| | | | | || |
| |_| | |  | | | |_| || |
 \___/|_|  |_|_|\___/|___|
"""


class RichUI:
    """Interactive UI. All confirm methods return safe defaults when stdin is
    not a terminal (so automated/scripted runs never auto-approve)."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console(highlight=False)
        self.tty = sys.stdin is not None and sys.stdin.isatty()

    # ------------------------------------------------------------- status ---
    def status(self, msg: str) -> None:
        self.console.print(f"[dim]… {escape(msg)}[/dim]")

    def info(self, msg: str) -> None:
        self.console.print(msg)

    def step(self, title: str, body: str = "") -> None:
        t = Text(title, style="bold cyan")
        if body:
            t.append("\n" + body, style="white")
        self.console.print(Panel(t, border_style="cyan", padding=(0, 1), expand=False))

    def tool_done(self, name: str, result: str, ms: int = 0) -> None:
        first = result.strip().splitlines()
        preview = "\n".join(first[:8])
        if len(first) > 8:
            preview += f"\n… (+{len(first) - 8} lines)"
        if len(preview) > 1100:
            preview = preview[:1100] + " …"
        color = "green" if "error" not in result[:200].lower() else "red"
        self.console.print(Panel(
            escape(preview or "(no output)"),
            title=f"[bold]{name}[/bold]  [dim]{ms} ms[/dim]",
            border_style=color, padding=(0, 1), expand=False))

    def answer(self, text: str) -> None:
        self.console.print(Panel(escape(text), border_style="bright_cyan",
                                 padding=(0, 1), title="[bold]OMNI[/bold]",
                                 expand=False))

    def alert(self, title: str, text: str, style: str = "bold yellow") -> None:
        self.console.print(Panel(escape(text), border_style="yellow",
                                 title=title, padding=(0, 1), expand=False))

    # ----------------------------------------------------------- confirms ---
    def _read(self, prompt: str) -> str:
        try:
            return self.console.input(prompt)
        except (EOFError, KeyboardInterrupt):
            return ""

    def confirm(self, prompt_markup: str, default: str = "y") -> bool:
        """generic yes/no gate (used by shell/browser/open_url internal asks)"""
        if not self.tty:
            return False
        if default not in ("y", "n"):
            default = "y"
        hint = "(Y/n)" if default == "y" else "(y/N)"
        while True:
            raw = self._read(f"[bold yellow]?[/bold yellow] {prompt_markup} {hint} ")
            if not raw:
                return default == "y"
            raw = raw.strip().lower()
            if raw in ("y", "yes"):
                return True
            if raw in ("n", "no", "q"):
                return False
            print("  reply y or n")

    def confirm_tool(self, tool, args_shown: str, risk: str, why: str):
        """Permission dialog. Returns (allowed, remember) with remember in
        ("", "always", "never")."""
        if not self.tty:
            return False, ""
        risk_names = {"safe": "safe (read-only)", "changes": "changes something",
                      "danger": "powerful action", "critical": "CRITICAL / irreversible"}
        default = "y" if risk == "changes" else "n"
        hint = "(Y/n)" if default == "y" else "(y/N)"
        lines = [
            f"[bold cyan]{tool.name}[/bold cyan] — {escape(args_shown)}",
            f"[yellow]risk:[/yellow] {risk_names.get(risk, risk)}"
            + (f"\n[yellow]⚠ {escape(why)}[/yellow]" if why else ""),
            "",
            f"[green]y[/green] allow once   [red]n[/red] deny   "
            f"[green]a[/green] always allow {tool.name}   [red]x[/red] never (deny always)",
        ]
        self.console.print(Panel("\n".join(lines), title="[bold]Permission needed[/bold]",
                                 border_style="yellow", padding=(0, 1)))
        while True:
            raw = self._read(f"? {hint} ").strip().lower()
            if not raw:
                return (default == "y"), ""
            if raw in ("y", "yes"):
                return True, ""
            if raw in ("a", "always", "yes always", "yall", "allow always"):
                return True, "always"
            if raw == "x":
                return False, "never"
            if raw in ("n", "no"):
                return False, ""
