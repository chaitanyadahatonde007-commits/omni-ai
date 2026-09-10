"""SYSTEM POWER TOOLS — run shell commands, control the machine, open URLs.
Command-aware risk escalation: known-dangerous prefixes always ask, even in
trusted mode.
"""
from __future__ import annotations

import re
import subprocess

from omni.tools import CRITICAL, DANGER, register

DESTRUCTIVE_PATTERNS = [
    r"(^|[;&|]\s*)\s*(rm|del|erase|format|rd|rmdir|deltree|diskpart|shutdown|reboot|restart|taskkill|kill|pkill|mkfs|dd)\b",
    r"(^|[;&|]\s*)\s*(git\s+push|git\s+reset\s+--hard|git\s+clean|git\s+rebase|git\s+checkout\s+--\s*\.)\b",
    r"(^|[;&|]\s*)\s*(pip|pip3|conda|npm|yarn|pnpm|gem|brew|choco|winget)\s+(uninstall|remove|purge)\b",
    r"registry\s+(delete|del)|reg\s+delete",
    r"net\s+user\s+\S+\s+/delete|sc\s+delete",
]
SUPERUSER_PATTERNS = [r"(^|[;&|]\s*)\s*(sudo|runas|doas|su)\b"]


def _escalate(ctx, args):
    cmd = str(args.get("command", ""))
    low = cmd.lower()
    for pat in DESTRUCTIVE_PATTERNS:
        if re.search(pat, low):
            return CRITICAL, "destructive command pattern"
    for pat in SUPERUSER_PATTERNS:
        if re.search(pat, low):
            return CRITICAL, "super-user/admin command"
    return DANGER, ""


def _run_shell(ctx, command: str, timeout: int = 120) -> str:
    style = ctx.shell_style
    if ctx.interactive_gate is None:
        return "blocked: no interactive terminal to approve this command"
    approved = ctx.interactive_gate(
        f"Run shell command:\n[cyan]{command}[/cyan]", "y" if ctx.auto_yes else "n")
    if not approved:
        return "cancelled by user (command NOT run)"
    if style == "cmd":
        full = ["cmd.exe", "/d", "/s", "/c", command]
    elif style == "powershell":
        full = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        full = ["bash", "-lc", command]
    try:
        proc = subprocess.run(full, capture_output=True, text=True, timeout=timeout,
                              cwd=str(ctx.workspace or "."), errors="replace",
                              encoding="utf-8", shell=False)
    except subprocess.TimeoutExpired:
        return f"command timed out after {timeout}s (process killed)"
    except FileNotFoundError as e:
        return f"could not start shell: {e}"
    out = (proc.stdout or "")[:12000]
    err = (proc.stderr or "")[:4000]
    lines = []
    if out.strip():
        lines.append(out.rstrip())
    if err.strip():
        lines.append("---STDERR---\n" + err.rstrip())
    if proc.returncode != 0:
        lines.append(f"(exit code {proc.returncode})")
    return "\n".join(lines) if lines else "(done, no output)"


register(
    "run_shell", "Run a command in the machine's real shell (cmd on Windows, bash elsewhere). THE system controller: install software, git, launch apps, scripts, network tools…",
    {"type": "object", "properties": {"command": {"type": "string", "description": "full command line"}, "timeout": {"type": "integer", "description": "seconds, default 120"}}, "required": ["command"]},
    risk=DANGER, category="system", escalate=_escalate,
)(_run_shell)


def _machine_control(ctx, action: str, app: str = "") -> str:
    a = action.strip().lower()
    style = ctx.shell_style
    if a == "sleep":
        cmd = ("rundll32.exe powrprof.dll,SetSuspendState 0,1,0"
               if style != "bash" else "systemctl suspend")
    elif a == "lock":
        cmd = ("rundll32.exe user32.dll,LockWorkStation"
               if style != "bash" else "loginctl lock-session")
    elif a == "open_app":
        if not app:
            return "open_app needs app= (name or path of the program)"
        cmd = f'start "" "{app}"' if style != "bash" else f'"{app}" &'
    else:
        return f"unknown action '{action}'. Known: sleep, lock, open_app"
    return _run_shell(ctx, cmd, 30)


register(
    "machine_control", "Control THIS laptop: sleep, lock the screen, open an app. (Always asks — it touches your real machine.)",
    {"type": "object", "properties": {"action": {"type": "string", "enum": ["sleep", "lock", "open_app"]}, "app": {"type": "string", "description": "app name/path for open_app"}}, "required": ["action"]},
    risk=CRITICAL, category="system",
)(_machine_control)


def _open_url(ctx, url: str) -> str:
    import webbrowser
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if ctx.interactive_gate is not None:
        if not ctx.interactive_gate(f"Open in your real browser: {url}",
                                    "y" if ctx.auto_yes else "n"):
            return "cancelled by user"
    webbrowser.open(url)
    return f"opened {url} in your default browser"


register(
    "open_url", "Open a URL in the user's real web browser (visible on their screen).",
    {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
    risk="changes", category="system",
)(_open_url)
