"""Permission engine.

Levels (per session):
  cautious  -> EVERY tool asks (even searches)
  guarded   -> safe tools auto-run; anything else asks   (default)
  trusted   -> safe/changes/danger auto-run; critical still asks

Persistent rules (survive restarts):
  permissions.json {"allow_always": [...tool names], "deny": [...]}
  - deny wins over everything
  - allow_always auto-approves at any level except for critical tools

Every gate decision is written to the session log.
"""
from __future__ import annotations

import logging

from omni import config
from omni.tools import CRITICAL, DANGER, RISK_ORDER, SAFE, Tool

log = logging.getLogger("omni.permissions")


def decision(tool: Tool, level: str, why_critical: str = "") -> str:
    """Returns 'allow' | 'ask' | 'deny'"""
    perms = config.load_permissions()
    name = tool.name
    if name in perms.get("deny", []) or tool.name in perms.get("deny", []):
        return "deny"
    effective_risk = tool.risk
    if why_critical:
        effective_risk = CRITICAL
    if name in perms.get("allow_always", []):
        return "ask" if effective_risk == CRITICAL else "allow"
    if level == "trusted":
        return "ask" if effective_risk == CRITICAL else "allow"
    if level == "cautious":
        return "ask"
    # guarded
    if effective_risk == SAFE:
        return "allow"
    return "ask"


def remember_always(tool_name: str, allow: bool = True) -> None:
    perms = config.load_permissions()
    key = "allow_always" if allow else "deny"
    other = "deny" if allow else "allow_always"
    if tool_name not in perms[key]:
        perms[key].append(tool_name)
    if tool_name in perms[other]:
        perms[other].remove(tool_name)
    config.save_permissions()


def describe_decision(risk: str) -> str:
    return {
        SAFE: "safe (read-only)",
        "changes": "changes something",
        DANGER: "powerful — can run code/commands",
        CRITICAL: "CRITICAL — destructive or irreversible",
    }.get(risk, risk)


def render_prompt(tool: Tool, args_summary: str, level: str, why: str = "") -> str:
    risk = tool.risk
    if why:
        risk = CRITICAL
    base = (
        f"OMNI wants to use [bold]{tool.name}[/bold] "
        f"({describe_decision(risk)})"
    )
    if why:
        base += f"\n[yellow]⚠ reason: {why}[/yellow]"
    if tool.category == "browser":
        base += "\n[dim](opens/controls your real web browser — watch it happen)[/dim]"
    return base
