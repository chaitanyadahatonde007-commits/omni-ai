"""OMNI AGENT CORE — the reasoning loop that turns your goals into tool actions.

Every action the brain wants to take is filtered through the permission
engine (guarded by default: safe = auto, everything else asks; trusted =
most auto; critical always asks). Denials and tool outcomes are fed back so
the brain adapts instead of dying.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

from omni import config, permissions, providers
from omni.tools import describe_tools, get, schemas

log = logging.getLogger("omni.agent")

SYSTEM_CORE = """You are OMNI, a powerful AI agent that lives in the user's terminal on their own laptop and does REAL work for them on the internet and on their machine.

YOUR POWERS (tools) — think of each as a real action you can take:
{tools}

GROUND RULES
1. Actually DO things with tools — never just describe how. Research before answering current questions (web_search), read pages before quoting them (web_fetch), verify important facts (web_verify), and produce real files/code/automations when asked.
2. Code you write must be complete and runnable. Prefer write_file for scripts, run_python for quick computations/requests.
3. When a tool errors, read the error, adapt, retry (max ~2 retries), then tell the user honestly.
4. Be concise in chat: short explanations + concrete results. Format lists with "- ". Keep prose tight.
5. If the task needs several actions, work through them one tool call at a time.
6. Never claim something is done unless a tool confirmed it. If a step needs the user (login, decision, payment), stop and ask them plainly.
7. You may ask ONE clarifying question before starting if the request is genuinely ambiguous — otherwise just start sensibly.
8. Money-spending, account-changing or identity-claiming actions: never attempt; explain that OMNI won't do that without explicit human steps.
9. Long outputs: write results to files in the workspace (write_file) instead of dumping everything into chat.
10. When the user asks something that depends on their personal data (their accounts, their location beyond what's given, their email), ask them or search publicly — never invent.

ENVIRONMENT
- User OS: {os}; shell: {shell}; working folder for files: {workspace}
- Today: {date} ({tz})
- Session: {session} (guarded = read-only actions auto-run, others ask; trusted = powerful actions auto-run, destructive still ask)
- Long-term memory (user facts, preferences, project notes — use it!):
{memory}

Conversation history follows. When you reply in natural language you are DONE unless you still have tool calls queued. If you need to use a tool, output ONLY tool calls (multiple allowed when independent)."""


@dataclass
class ToolBlocked(Exception):
    message: str


class Agent:
    def __init__(self, ctx, ui, provider: str, model: str, level: str = "guarded",
                 workspace=None, shell="cmd"):
        self.ctx = ctx
        self.ui = ui
        self.provider = provider
        self.model = model
        self.level = level
        self.messages: list[dict] = []
        self.history_limit = 90000  # chars; old turns get pruned
        self.steps = 0
        self.last_provider = provider
        self.last_model = model
        self._seed_messages(workspace, shell)

    # ------------------------------------------------------------ prompts ---
    def _seed_messages(self, workspace, shell) -> None:
        import datetime
        try:
            from zoneinfo import ZoneInfo
            tz = datetime.datetime.now(ZoneInfo("Asia/Calcutta")).tzname()
        except Exception:
            tz = ""
        from omni.tools.memory_tool import memory_entries
        mem_lines = []
        for m in memory_entries()[-18:]:
            mem_lines.append(f"- ({m.get('tag')}) {m.get('text','')[:220]}")
        memory = "\n".join(mem_lines) or "(empty — save facts with remember)"
        date = datetime.date.today().isoformat()
        self.system = SYSTEM_CORE.format(
            tools=describe_tools(), os=config.system_facts().get("os", "?"),
            shell=shell or "cmd", workspace=workspace or config.workspace_dir(),
            date=date, tz=tz, session=self.level,
            memory=memory)

    def _apply_system(self) -> None:
        # system message first, refreshed each call (cheap on Gemini prefix)
        pass

    def reset(self) -> None:
        self.messages = []

    # --------------------------------------------------------------- main ---
    def run(self, user_text: str) -> str:
        """Full loop for one user request. Returns the final text answer."""
        self.messages.append({"role": "user", "content": user_text})
        self.steps = 0
        max_steps = int(config.get("max_steps", 30))
        while self.steps < max_steps:
            self.steps += 1
            self.ui.status(f"thinking… (step {self.steps})")
            try:
                text, calls, used_provider, used_model = self._call_model()
            except providers.ProviderError as e:
                # fall back across models/providers
                try:
                    text, calls, used_provider, used_model = self._call_model_fallback()
                except providers.ProviderError as e2:
                    return (f"⚠ All AI providers failed: {e}\n\n"
                            f"Fix: type /setup to add a free API key, or /doctor.")
            self.last_provider, self.last_model = used_provider, used_model
            if calls:
                ok = self._dispatch_all(calls)
                if not ok:
                    continue
                self._prune()
                continue
            # natural-language answer = done
            self._prune()
            if text.strip():
                self.messages.append({"role": "assistant", "content": text})
            return text.strip() or "(empty reply)"
        return ("I hit my step limit — the task needs more actions than I'm allowed "
                "this session. Tell me 'continue' or raise the limit with /set max_steps 60.")

    # ------------------------------------------------------- model calls ----
    def _model_messages(self) -> list[dict]:
        msgs = []
        if self.provider == "gemini":
            msgs.append({"role": "system", "content": self.system})
        else:
            msgs.append({"role": "system", "content": self.system})
        msgs.extend(self.messages)
        return msgs

    def _tools_for(self) -> list | None:
        if self.provider == "ollama":
            m = self.model.lower()
            capable = any(k in m for k in ("qwen", "llama3.2", "llama3.3", "llama4",
                                           "mistral", "phi", "gemma", "command-r",
                                           "deepseek-r1", "deepseek-v3", "granite"))
            return schemas() if capable else None
        return schemas()

    def _call_model(self):
        tools = self._tools_for()
        text, calls, used, prov = providers.chat(
            self.provider, self.model, self._model_messages(),
            tools=tools, temperature=0.3)
        return text, calls, used, prov

    def _call_model_fallback(self):
        """Retry across remaining candidate models/providers."""
        from omni import providers as pv
        cands = pv.FREE_CANDIDATES.get(self.provider, [])
        errs = []
        for m in cands:
            if m == self.model:
                continue
            try:
                self.model = m
                return self._try()
            except providers.ProviderError as e:
                errs.append(str(e))
        for prov2 in pv.configured_providers():
            if prov2 == self.provider:
                continue
            for m in pv.FREE_CANDIDATES.get(prov2, []):
                try:
                    self.provider, self.model = prov2, m
                    return self._try()
                except providers.ProviderError as e:
                    errs.append(str(e))
        raise providers.ProviderError("all models failed: " + "; ".join(errs[:3]))

    def _try(self):
        text, calls, used, prov = providers.chat(
            self.provider, self.model, self._model_messages(),
            tools=self._tools_for(), temperature=0.3)
        return text, calls, used, prov

    # ------------------------------------------------------- path anchor ----
    FILE_PATH_ARGS = {
        "write_file": ["path"], "read_file": ["path"], "list_files": ["path"],
        "find_files": ["path"], "run_file": ["path"], "make_csv": ["path"],
        "make_json": ["path"], "send_email": ["attach"],
    }

    def _anchor_paths(self, tool, clean: dict) -> None:
        from pathlib import Path
        keys = self.FILE_PATH_ARGS.get(tool.name, [])
        for k in keys:
            v = clean.get(k)
            if not v or not isinstance(v, str):
                continue
            p = Path(v).expanduser()
            if not p.is_absolute() and not v.startswith("~"):
                p = self.ctx.workspace / p
            clean[k] = str(p.resolve())

    # ----------------------------------------------------------- dispatch ---
    def _dispatch_all(self, calls) -> bool:
        """Run each requested tool call. Returns False when the model must
        be re-prompted with results (i.e. always)."""
        for name, args in calls:
            if not name:
                continue
            result = self._execute_tool(name, args)
            self.messages.append({"role": "assistant", "content": "",
                                  "tool_calls": [{"id": name, "type": "function",
                                                  "function": {"name": name,
                                                               "arguments": json.dumps(args, default=str)}}]})
            self.messages.append({"role": "tool", "tool_call_id": name,
                                  "name": name, "content": result[:int(config.get("max_tool_output", 8000))]})
        return True

    def _execute_tool(self, name: str, args: dict) -> str:
        t = get(name)
        t0 = time.time()
        if t is None:
            return f"error: unknown tool '{name}'. Available: {', '.join(sorted(get_tool_names()))}"
        # filter args to declared properties (models invent extras)
        props = (t.parameters or {}).get("properties", {})
        clean = {k: v for k, v in args.items() if k in props}
        # anchor file paths into the OMNI workspace
        self._anchor_paths(t, clean)
        # pull in ctx if the tool wants it
        risk, why = t.risk, ""
        if t.escalate is not None:
            try:
                risk, why = t.escalate(self.ctx, clean) or (t.risk, "")
            except Exception as e:
                log.warning("escalate failed for %s: %s", name, e)

        # permissions gate -------------------------------------------------
        gateable = t.category in ("system", "browser")
        if gateable:
            # these tools ask INSIDE themselves via ctx.interactive_gate;
            # only hard-deny matters here
            verdict = permissions.decision(t, self.level, why)
            if verdict == "deny":
                return "blocked: you denied this tool earlier (permissions.json). Use /unblock to allow."
        else:
            verdict = permissions.decision(t, self.level, why)
            if verdict == "deny":
                return "blocked: you denied this tool earlier. Use /unblock to allow."
            if verdict == "ask":
                from omni.tools import pretty_args
                shown = pretty_args(clean)
                ok, remember = self.ui.confirm_tool(t, shown, risk, why)
                if remember == "always":
                    permissions.remember_always(name, True)
                elif remember == "never":
                    permissions.remember_always(name, False)
                if not ok:
                    self.ctx.log_event(f"DENIED tool={name} args={shown}")
                    return "user DENIED permission — do not retry; explain what you wanted to do and ask how to proceed"
        try:
            res = t.fn(self.ctx, **clean)
        except Exception as e:  # noqa: BLE001
            import traceback
            log.debug("tool %s traceback:\n%s", name, traceback.format_exc())
            res = f"error in {name}: {type(e).__name__}: {e}"
        ms = int((time.time() - t0) * 1000)
        self.ctx.log_event(f"TOOL name={name} risk={risk} ms={ms} args={json.dumps(clean, default=str)[:400]}")
        self.ui.tool_done(name, res, ms)
        return res

    def _prune(self) -> None:
        total = sum(len(str(m.get("content", ""))) for m in self.messages) + \
                sum(len(json.dumps(tc, default=str)) for m in self.messages for tc in m.get("tool_calls", []))
        while total > self.history_limit and len(self.messages) > 8:
            dropped = self.messages.pop(1)
            total -= len(str(dropped.get("content", "")))
        # keep tool result pairing sane: drop orphan tool rows
        while self.messages and self.messages[0].get("role") == "tool":
            self.messages.pop(0)


def get_tool_names():
    from omni.tools import tools as _t
    return list(_t().keys())
