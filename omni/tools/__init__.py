"""Tool registry: every power OMNI has is a registered, permission-gated tool.

A tool declares:
  name         snake_case id used by the brain and in /allow rules
  description  for the LLM
  parameters   JSON-schema-ish {"type":"object","properties":...,"required":[]}
  risk         safe | changes | danger | critical   (see permissions.py)
  fn           callable(ctx, **kwargs) -> str
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable, Optional

# ----------------------------------------------------------------- risk ----
SAFE = "safe"          # read-only; runs without asking
CHANGES = "changes"    # modifies something local; asks unless session trusted
DANGER = "danger"      # powerful (runs code / shell / writes files); asks unless trusted
CRITICAL = "critical"  # destructive/irreversible: ALWAYS asks, even when trusted

RISK_ORDER = {SAFE: 0, CHANGES: 1, DANGER: 2, CRITICAL: 3}


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    fn: Callable
    risk: str = CHANGES
    category: str = "general"
    escalate: Optional[Callable] = None  # fn(ctx, args) -> (risk, reason) override
    needs_ctx: bool = True

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def __repr__(self):  # pragma: no cover
        return f"<Tool {self.name} [{self.risk}]>"


_REGISTRY: dict[str, Tool] = {}


def register(name, description, parameters, risk=CHANGES, category="general", escalate=None):
    def deco(fn):
        if name in _REGISTRY:
            raise RuntimeError(f"duplicate tool name: {name}")
        _REGISTRY[name] = Tool(name, description, parameters, fn, risk, category, escalate)
        return fn
    return deco


def tools() -> dict[str, Tool]:
    if not _REGISTRY:
        _import_all()
    return _REGISTRY


def get(name: str) -> Optional[Tool]:
    return tools().get(name)


def schemas() -> list[dict]:
    return [t.openai_schema() for t in tools().values()]


def describe_tools() -> str:
    lines = []
    for t in sorted(tools().values(), key=lambda x: (x.category, x.name)):
        lines.append(f"- {t.name} [{t.risk}]: {t.description}")
    return "\n".join(lines)


def _import_all() -> None:
    from omni.tools import automation, browser, code, memory_tool, system, web  # noqa: F401


# ------------------------------------------------------------------ misc ----
def pretty_args(args: dict, max_len: int = 300) -> str:
    try:
        s = json.dumps(args, ensure_ascii=False, indent=0, default=str)
    except Exception:
        s = str(args)
    if len(s) > max_len:
        s = s[:max_len] + "…"
    return s


def _inside(path: str, root) -> bool:
    from pathlib import Path
    try:
        p = Path(path).expanduser().resolve()
        r = Path(root).expanduser().resolve()
        return p == r or r in p.parents
    except Exception:
        return False


def path_guard(ctx, path: str, operation: str) -> tuple[str, str]:
    """Returns (risk, reason) — escalates when touching anything outside the
    OMNI workspace or files that look like credentials/system files."""
    from pathlib import Path
    inside = "safe"
    try:
        p = Path(path).expanduser().resolve()
    except Exception:
        return ("danger", "")
    if p.name and not _inside(str(p), ctx.workspace):
        inside = "outside" if p.name else "outside"
    else:
        inside = "inside"
    if operation == "read":
        risk = "safe"
    elif operation in ("write", "create"):
        risk = "danger"
    else:  # run / execute
        risk = "danger"
    low = p.name.lower()
    secretish = low in (".env", "id_rsa", "id_ed25519", "credentials", "passwords",
                        "secrets", "credential") or \
        any(part in str(p).lower() for part in ("\\.ssh", "/.ssh", "\\.aws", "/.aws"))
    if secretish:
        return "critical", "path looks like a secrets/credentials file"
    if inside == "outside":
        if operation in ("write", "create"):
            return "critical", f"writing OUTSIDE the OMNI workspace ({ctx.workspace})"
        if operation == "read":
            return "changes", f"reading OUTSIDE the OMNI workspace — outside files may be sensitive"
        return "danger", f"running a file OUTSIDE the OMNI workspace ({ctx.workspace})"
    return risk, ""


# eager registration: importing ANY omni.tools module registers ALL powers
_import_all()
