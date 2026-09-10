"""CODING POWER TOOLS — write, read, list, search files and run code.
Files outside the OMNI workspace or secret-looking paths trigger a higher
permission bar automatically (see path_guard in omni/tools/__init__.py).
"""
from __future__ import annotations

import os
from pathlib import Path

from omni import config
from omni.python_exec import run_python_sandbox, run_script
from omni.tools import path_guard, register

# ------------------------------------------------------------------ files ---


def _guard_risk(ctx, path, op):
    risk, why = path_guard(ctx, path, op)
    return risk, why


def _read_file_impl(ctx, path: str, limit: int = 15000) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"file not found: {path}"
    if p.is_dir():
        items = sorted(p.iterdir())
        names = [("📁 " if i.is_dir() else "📄 ") + i.name for i in items]
        return f"DIRECTORY {path}:\n" + "\n".join(names) if names else f"DIRECTORY {path} is empty"
    try:
        data = p.read_bytes()
    except Exception as e:
        return f"cannot read {path}: {e}"
    is_text = True
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        is_text = False
        text = ""
    if not is_text:
        return f"{path} is binary ({len(data)} bytes) — not shown. Use run_python to inspect."
    size = len(text)
    if size > limit:
        text = text[:limit] + f"\n…[truncated, {size - limit} more chars — file is {size} chars]"
    return f"FILE {p} ({size} chars):\n{text}"


def _write_file_impl(ctx, path: str, content: str) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    mode = "w"
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {p}"


def _list_files_impl(ctx, path: str = ".", pattern: str = "*", max_depth: int = 2) -> str:
    root = (Path(path) if path else Path(".")).expanduser()
    root = root.resolve()
    if not root.exists():
        return f"no such path: {path}"
    depth = max(1, min(int(max_depth or 2), 6))
    total = 0
    lines = []
    import fnmatch

    def walk(d: Path, level: int):
        nonlocal total
        try:
            entries = sorted(d.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            return
        for e in entries:
            if e.name.startswith(".") and len(e.name) > 1 and e.name not in (".env",):
                continue
            if e.is_dir():
                if level < depth:
                    lines.append("  " * level + "📁 " + e.name + "/")
                    walk(e, level + 1)
            else:
                if not fnmatch.fnmatch(e.name.lower(), pattern.lower()):
                    continue
                total += 1
                try:
                    size = e.stat().st_size
                except Exception:
                    size = 0
                if size < 1024:
                    sz = f"{size}B"
                elif size < 1048576:
                    sz = f"{size/1024:.0f}KB"
                else:
                    sz = f"{size/1048576:.1f}MB"
                lines.append("  " * level + f"📄 {e.name}  ({sz})")
                if total > 400:
                    lines.append("  …(too many files — narrow with pattern/max_depth)")
                    return
    walk(root, 0)
    return "\n".join(lines) if lines else f"(nothing matching '{pattern}' in {root})"


def _find_files_impl(ctx, name: str = "", content: str = "", path: str = ".", max_results: int = 50) -> str:
    root = Path(path).expanduser().resolve()
    if not root.exists():
        return f"no such path: {path}"
    name_l = (name or "").lower()
    hits = []
    for p in root.rglob("*"):
        try:
            if not p.is_file():
                continue
            if any(part.startswith(".") and part not in (".env",) for part in p.parts):
                continue
            if name_l and name_l not in p.name.lower():
                continue
            if content:
                try:
                    data = p.read_bytes()
                except Exception:
                    continue
                if content.lower() not in data.lower() and not _contains_text(p, content):
                    continue
            hits.append(str(p))
            if len(hits) >= max_results:
                break
        except Exception:
            continue
    if not hits:
        return f"nothing found (name={name or '*'} content={content or '-'} in {root})"
    return f"{len(hits)} match(es):\n" + "\n".join(hits)


def _contains_text(p: Path, needle: str) -> bool:
    try:
        return needle.lower() in p.read_text(encoding="utf-8", errors="ignore").lower()
    except Exception:
        return False


def _file_risk_escalate(op):
    def esc(ctx, args):
        path = str(args.get("path", args.get("file", "")))
        return path_guard(ctx, path, op)
    return esc


register(
    "read_file", "Read a file (text files) or list a directory. Use to inspect code, configs, documents in the workspace. Text is truncated at 15k chars.",
    {"type": "object", "properties": {"path": {"type": "string", "description": "file or folder path"}}, "required": ["path"]},
    risk="safe", category="code", escalate=_file_risk_escalate("read"),
)(_read_file_impl)

register(
    "write_file", "Create or overwrite a file with text content. ALWAYS fully write the file (never partial edits); read_file first when unsure of existing content.",
    {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
    risk="danger", category="code", escalate=_file_risk_escalate("write"),
)(_write_file_impl)

register(
    "list_files", "List a folder tree (2 levels by default) with file sizes — quick orientation in a project.",
    {"type": "object", "properties": {"path": {"type": "string", "description": "folder, default ."}, "pattern": {"type": "string", "description": "fnmatch filter like *.py"}, "max_depth": {"type": "integer"}}, "required": []},
    risk="safe", category="code",
)(_list_files_impl)

register(
    "find_files", "Search files by name and/or by text content inside them.",
    {"type": "object", "properties": {"name": {"type": "string", "description": "filename substring"}, "content": {"type": "string", "description": "text that must appear inside the file"}, "path": {"type": "string", "description": "folder to search, default ."}, "max_results": {"type": "integer"}}, "required": []},
    risk="safe", category="code",
)(_find_files_impl)


# ------------------------------------------------------------------ run -----
def _run_python_impl(ctx, code: str, timeout: int = 120) -> str:
    cwd = str(ctx.workspace) if ctx.workspace else "."
    return run_python_sandbox(code, cwd=cwd, timeout=timeout)


register(
    "run_python", "Execute Python 3 code (the ultimate power tool: math, data crunching, requests to APIs, file processing, scraping, automation…). Code runs in a sandboxed folder; `result` can carry a value back. Print what matters.",
    {"type": "object", "properties": {"code": {"type": "string", "description": "full python program"}, "timeout": {"type": "integer", "description": "seconds, default 120"}}, "required": ["code"]},
    risk="danger", category="code",
)(_run_python_impl)

register(
    "run_file", "Execute an existing script file by extension (.py via python, .js via node, .sh via bash) and return its output.",
    {"type": "object", "properties": {"path": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["path"]},
    risk="danger", category="code", escalate=_file_risk_escalate("run"),
)(lambda ctx, path, timeout=180: run_script(path, timeout))
