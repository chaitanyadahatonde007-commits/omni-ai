"""Configuration, secrets (.env) and persistent state for OMNI.

Everything lives under OMNI_HOME (~/.omni by default):
  ~/.omni/config.json      user preferences
  ~/.omni/.env             API keys (kept out of the repo!)
  ~/.omni/permissions.json remember-allowed / denied tools
  ~/.omni/memory.json      long-term memory
  ~/.omni/logs/            session logs
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import sys
import time
from pathlib import Path

APP = "omni"


def home_dir() -> Path:
    override = os.environ.get("OMNI_HOME")
    if override:
        p = Path(override).expanduser()
    else:
        p = Path.home() / ".omni"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _default_workspace() -> Path:
    return Path.home() / "omni-workspace"


DEFAULTS: dict = {
    "workspace": str(_default_workspace()),
    "shell_style": "auto",          # auto | cmd | powershell | bash
    "max_steps": 30,                # max tool actions per task
    "max_tool_output": 8000,        # characters of tool output the brain sees
    "plan_before": True,            # show a plan and ask before executing
    "permission_level": "guarded",  # guarded | trusted | cautious
    "provider_order": ["gemini", "groq", "openrouter", "github", "ollama", "custom"],
    "model_candidates": {},         # per-provider override of candidate models
    "web_search_engines": ["duckduckgo", "mojeek"],
    "logs": True,
    "telemetry": False,
}

_CONF: dict | None = None


def load() -> dict:
    global _CONF
    if _CONF is None:
        data = dict(DEFAULTS)
        f = home_dir() / "config.json"
        try:
            if f.exists():
                saved = json.loads(f.read_text(encoding="utf-8"))
                data.update({k: v for k, v in saved.items() if k in DEFAULTS})
        except Exception:
            pass
        _CONF = data
    return _CONF


def get(key: str, default=None):
    return load().get(key, default)


def set_config(key: str, value) -> None:
    load()[key] = value
    save()


def save() -> None:
    f = home_dir() / "config.json"
    try:
        f.write_text(json.dumps(load(), indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[omni] could not save config: {e}")


# ---------------------------------------------------------------- secrets ---
_ENV_CACHE: dict | None = None


def _parse_env_text(text: str) -> dict:
    out: dict = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def env_file() -> Path:
    return home_dir() / ".env"


def load_secrets(force: bool = False) -> dict:
    """Secrets = process env merged with ~/.omni/.env (env wins for tests)."""
    global _ENV_CACHE
    if _ENV_CACHE is not None and not force:
        return _ENV_CACHE
    secrets = {}
    for f in (Path.cwd() / ".env", env_file()):
        try:
            if f.exists():
                secrets.update(_parse_env_text(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    secrets.update({k: v for k, v in os.environ.items() if k.endswith("_API_KEY") or k in ("GITHUB_TOKEN", "GEMINI_API_KEY")})
    _ENV_CACHE = secrets
    return secrets


def save_secret(key: str, value: str) -> None:
    f = env_file()
    try:
        if f.exists():
            text = f.read_text(encoding="utf-8")
        else:
            text = ""
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#") and ln.split("=", 1)[0].strip() != key]
        lines.append(f"{key}={value}")
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if sys.platform != "win32":
            try:
                os.chmod(f, stat.S_IRUSR | stat.S_IWUSR)
            except Exception:
                pass
        _ENV_CACHE = None
    except Exception as e:
        raise RuntimeError(f"could not write secret file: {e}")


# ------------------------------------------------------------ permissions ---
_PERMS: dict | None = None


def load_permissions() -> dict:
    global _PERMS
    if _PERMS is None:
        f = home_dir() / "permissions.json"
        try:
            _PERMS = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
        except Exception:
            _PERMS = {}
        _PERMS.setdefault("allow_always", [])
        _PERMS.setdefault("deny", [])
    return _PERMS


def save_permissions() -> None:
    f = home_dir() / "permissions.json"
    try:
        f.write_text(json.dumps(load_permissions(), indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[omni] could not save permissions: {e}")


# ------------------------------------------------------------------ misc ----
def workspace_dir() -> Path:
    ws = Path(get("workspace")).expanduser()
    ws.mkdir(parents=True, exist_ok=True)
    return ws


def logs_dir() -> Path:
    d = home_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def session_log_path() -> Path:
    return logs_dir() / time.strftime("session_%Y%m%d_%H%M%S.log")


def data_dir() -> Path:
    d = home_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def system_facts() -> dict:
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "shell_style": detect_shell(),
        "cwd": str(Path.cwd()),
    }


def detect_shell() -> str:
    style = get("shell_style", "auto")
    if style != "auto":
        return style
    if sys.platform == "win32":
        if os.environ.get("SHELL", "").lower().endswith("pwsh") or os.environ.get("PSModulePath"):
            return "powershell"
        return "cmd"
    return "bash"


def which(name: str) -> str | None:
    return shutil.which(name)
