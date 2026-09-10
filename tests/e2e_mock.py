"""End-to-end test with a MOCK AI brain (local fake OpenAI-compatible server).

Proves the full loop works: user goal -> LLM call -> tool_calls parsed ->
permission gate -> real tool execution -> results fed back -> final answer.

Run:  python tests/e2e_mock.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["OMNI_HOME"] = tempfile.mkdtemp(prefix="omni_e2e_")
os.environ["OMNI_AUTO_YES"] = "1"


class Brain:
    """Scripted brain: first turn requests tools, then answers."""

    def __init__(self):
        self.turns = 0
        self.last_messages = None

    def respond(self, messages, has_tools):
        self.turns += 1
        self.last_messages = messages
        # find the last tool result content
        tool_results = [m for m in messages if m.get("role") == "tool"]
        if not tool_results:
            content = None
            calls = [
                {"function": {"name": "web_search",
                              "arguments": json.dumps({"query": "omni test query"})}},
                {"function": {"name": "make_csv",
                              "arguments": json.dumps({"path": "e2e.csv", "headers": "a,b",
                                                       "rows": "1,2"})}},
            ]
        else:
            content = ("E2E OK. I searched the web and created the CSV file. "
                       "Tool results received: " + str(len(tool_results)) + ".")
            calls = None
        return content, calls


class Handler(BaseHTTPRequestHandler):
    brain = Brain()

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("content-length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        msgs = payload.get("messages", [])
        tools = payload.get("tools")
        content, calls = Handler.brain.respond(msgs, bool(tools))
        msg = {"role": "assistant", "content": content}
        if calls:
            msg["tool_calls"] = [{
                "id": f"call_{i}", "type": "function",
                "function": {"name": c["function"]["name"],
                             "arguments": c["function"]["arguments"]}}
                for i, c in enumerate(calls)]
        body = json.dumps({"choices": [{"message": msg, "index": 0,
                                        "finish_reason": "tool_calls" if calls else "stop"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # silence
        pass


def main():
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    from omni import config
    config.save_secret("CUSTOM_ENDPOINT", f"http://127.0.0.1:{port}/v1/chat/completions")
    config.save_secret("CUSTOM_API_KEY", "test-key")
    config.set_config("brain", {"provider": "custom", "model": "mock-model"})
    config.set_config("permission_level", "trusted")
    config.set_config("workspace", tempfile.mkdtemp(prefix="omni_e2e_ws_"))

    from omni.context import Context
    from omni.repl import ReplUI
    from omni.ui import RichUI
    from omni.agent import Agent
    from omni import providers

    ctx = Context(config.workspace_dir(), config.home_dir() / "sessions")
    ctx.workspace.mkdir(parents=True, exist_ok=True)
    ui = ReplUI(RichUI.__new__(RichUI))  # thin shell w/o terminal
    ui.tty = False

    class AutoUI:
        tty = False
        def status(self, m): pass
        def info(self, m): print(m)
        def tool_done(self, n, r, ms=0): print(f"  [tool {n}]: {r[:80]}")
        def answer(self, t): print(f"ANSWER: {t}")
        def confirm(self, p, d="y"): return True
        def confirm_tool(self, t, a, r, w): return True, ""

    ui = AutoUI()
    ag = Agent(ctx, ui, provider="custom", model="mock-model", level="trusted",
               workspace=str(ctx.workspace), shell="bash")
    reply = ag.run("create a csv file and search the web")
    assert "E2E OK" in reply, reply
    assert (ctx.workspace / "e2e.csv").exists(), "csv not created!"
    txt = (ctx.workspace / "e2e.csv").read_text()
    assert "1,2" in txt, txt
    print(f"\nE2E PASS ✓  (brain turns={Handler.brain.turns}, csv={txt!r})")
    print("final answer:", reply[:120])
    server.shutdown()


if __name__ == "__main__":
    main()
