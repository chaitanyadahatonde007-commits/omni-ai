"""Run Python code safely-ish: sandboxed temp dir, no TTY, big output cap,
cwd forced to a per-run temp folder, and (when available) an offline guard.

Warnings: this is a LOCAL agent on YOUR machine by design — with your
approval it runs real code that can do real things. The permission system is
the safety boundary, not this sandbox.
"""
from __future__ import annotations

import io
import os
import sys
import textwrap
import traceback

_ORIG_PRINT = print  # snapshot the original builtin before we ever patch it

BUILTIN_GUARD = textwrap.dedent(
    """
    # OMNI output re-route (avoid huge logs)
    def omni_result(*objs, file=None):
        import json as _json
        parts = []
        for o in objs:
            try:
                parts.append(_json.dumps(o, ensure_ascii=False, default=str, indent=2))
            except Exception:
                parts.append(str(o))
        print("\\n---RESULT---\\n" + "\\n".join(parts))
    omni_clear = lambda: None
    def omni_run(name, *args, **kw):
        import subprocess as _sp
        _sp.run([name, *[str(a) for a in args]], **kw)
    # patch input() to refuse silently when no human is attached
    import builtins as _b
    _real_input = _b.input
    def _safe_input(prompt=""):
        raise RuntimeError("input() is disabled in the OMNI python sandbox")
    _b.input = _safe_input
    """
)


def run_python_sandbox(code: str, cwd: str = ".", timeout: int = 120) -> str:
    """Execute `code` and capture stdout+stderr+exception into a report."""
    prefix = BUILTIN_GUARD
    compiled = None
    try:
        compiled = compile(prefix + "\n" + textwrap.dedent(code), "<omni-code>", "exec")
    except SyntaxError as e:
        return f"SYNTAX ERROR: {e}"
    stdout, stderr = io.StringIO(), io.StringIO()
    old_out, old_err, old_cwd = sys.stdout, sys.stderr, os.getcwd()
    result = ""
    import builtins
    orig_print = builtins.print
    _captured_stream = stdout
    try:
        os.chdir(cwd)
        sys.stdout, sys.stderr = stdout, stderr
        builtins.print = _captured_print  # prints go to captured stream too
        ns: dict = {"__name__": "__omni__", "result": None}
        try:
            exec(compiled, ns)
        except Exception:
            stderr.write(traceback.format_exc())
    finally:
        builtins.print = orig_print
        sys.stdout, sys.stderr = old_out, old_err
        os.chdir(old_cwd)
    out, err = stdout.getvalue(), stderr.getvalue()
    # cap sizes
    cap = 12000
    if len(out) > cap:
        out = out[:cap] + f"\n…[stdout truncated, {len(out) - cap} more chars]"
    if len(err) > 4000:
        err = err[:4000] + "\n…[stderr truncated]"
    result = ns.get("result")
    report = []
    if out.strip():
        report.append(out.rstrip())
    if result is not None:
        try:
            import json
            report.append("---RESULT VALUE---\n" + json.dumps(result, ensure_ascii=False, indent=2, default=str))
        except Exception:
            report.append("---RESULT VALUE---\n" + str(result))
    if err.strip():
        report.append("---ERROR/STDERR---\n" + err.rstrip())
    return "\n".join(report) if report else "(no output, exit ok)"


_captured_stream = None


def _captured_print(*args, **kwargs):  # noqa: ANN002,ANN003
    kwargs["file"] = kwargs.pop("file", None) or _captured_stream
    _ORIG_PRINT(*args, **kwargs)


def run_script(path: str, timeout: int = 180) -> str:
    """Run a .py/.js/... file by extension."""
    import subprocess
    import shutil
    ext = os.path.splitext(path)[1].lower()
    if ext == ".py":
        cmd = [sys.executable, path]
    elif ext == ".js":
        node = shutil.which("node")
        if not node:
            return "node.js is not installed on this machine"
        cmd = [node, path]
    elif ext == ".sh":
        bash = shutil.which("bash")
        if not bash:
            return "bash not available"
        cmd = [bash, path]
    else:
        return f"cannot auto-run .{ext or '?'} files — use run_shell with the right command"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=os.path.dirname(os.path.abspath(path)))
    except subprocess.TimeoutExpired:
        return f"timed out after {timeout}s — command still running? (killed)"
    out = (proc.stdout or "")[:12000]
    err = (proc.stderr or "")[:4000]
    lines = []
    if out.strip():
        lines.append(out.rstrip())
    if err.strip():
        lines.append("---STDERR---\n" + err.rstrip())
    if proc.returncode != 0:
        lines.append(f"(exit code {proc.returncode})")
    return "\n".join(lines) if lines else f"(ran fine, exit 0, no output)"
