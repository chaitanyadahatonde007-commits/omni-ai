# OMNI — your everything agent for the Command Prompt

**OMNI** turns your laptop into an AI agent that can do real tasks on the
internet and on your machine — **searches & verifies information, reads any
website, writes and runs code, builds automations, remembers things across
sessions** — using **100% free AI models and 100% free web tools** … and it
only acts with **your permission**.

```
  ___  __  __ _ _   _ ___
 / _ \|  \/  (_) | | |_ _|
| | | | |\/| | | | | || |
| |_| | |  | | | |_| || |
 \___/|_|  |_|_|\___/|___|
```

---

## 1. Install on Windows (2 minutes, everything free)

1. **Install Python** (if you don't have it): https://www.python.org/downloads/
   — during setup **tick “Add python.exe to PATH”**, then open a **new** Command Prompt.
2. **Download this project** into a folder (e.g. `C:\omni-ai`).
3. In that folder, **double-click `install.bat`** (or run it from cmd).
   It installs the free libraries and puts the `omni` command on your PATH.
4. Open a **new** Command Prompt and type:

```bat
omni
```

5. On first run OMNI asks you to connect **one free brain**. Easiest option:
   **Google Gemini** — get a free key at https://aistudio.google.com/apikey
   (takes 20 seconds, free tier ≈ hundreds of requests/day).
   Other free options: Groq, OpenRouter free models, GitHub Models, or a
   **100% local Ollama** (no key, private).

> Linux/macOS: run `./omni.sh` (or `python3 -m omni`).
> Nothing here costs money. No credit card anywhere.

### Optional power add-ons
```bat
pip install selenium        :: lets OMNI drive a real Chrome/Edge window
```
Works automatically if you have Chrome/Edge installed (for sites that need
real-browser interaction: dashboards, maps, social feeds, login flows).

---

## 2. What OMNI can do

| Power | What happens |
|---|---|
| 🌐 `web_search` | Live internet search (DuckDuckGo + Mojeek + Startpage, keyless, multi-engine fallback) |
| 📄 `web_fetch` | Reads any article/doc/JSON page as clean text |
| ✅ `web_verify` | Fact-checks claims against the live web with sources |
| 🧠 Free AI brain | Gemini Flash / Groq / OpenRouter `:free` / GitHub Models / local Ollama — OMNI picks the first that works |
| 💻 `run_python` | Runs Python live: math, data, APIs, scraping, file processing |
| 📝 `write_file` / `read_file` | Works with any file, code or document |
| ⚡ `run_shell` | Real shell commands on your PC (cmd / PowerShell / bash) |
| 🌍 `browse` | Drives a real browser: click, type, fill forms, screenshot (needs optional selenium) |
| 📊 `make_csv` / `make_json` | Reports & data files you can open in Excel |
| ⏰ `remind_me` / `schedule_task` | “remind me in 10 minutes…”, “at 14:30…” |
| 🧠 memory | `/memory` long-term facts; OMNI recalls them next session |
| 🔔 `notify` | Windows toast notifications |
| 📧 `send_email` | Emails via your free Gmail app-password (optional one-time setup) |

**Example things to type:**
```
omni> search the web: what are the best free AI tools right now? make a report file
omni> verify this claim: "Python is the most popular language in 2026"
omni> write a python script that downloads the top 10 trending GitHub repos today, and run it
omni> make a csv of the current top 5 movies from IMDb
omni> remind me in 20 minutes to take a break
omni> research scholarship deadlines this month for Indian students and save a summary
```

---

## 3. Permissions — OMNI asks before it acts

OMNI never acts silently. Every action carries a risk label and goes through
a permission gate.

| Level | What runs without asking |
|---|---|
| `guarded` *(default)* | safe read-only things: searches, reading pages/files. **Everything else asks you** |
| `cautious` | **every** action asks — even searches |
| `trusted` (`/trust`) | powerful actions auto-run (code, shell, writes) — but **destructive/irreversible ones still ask** |

When OMNI asks, reply:
- **`y`** — allow once
- **`n`** — deny
- **`a`** — *always allow* this tool (saved in `~\.omni\permissions.json`)
- **`x`** — *never* allow this tool (deny is remembered)

**Safety rails that always apply, even in trusted mode:**
- destructive commands (`del`, `rm -rf`, `format`, `git push`, `shutdown`…) → always ask
- writing **outside** your OMNI workspace (e.g. `C:\Windows`, other user files) → always ask
- anything touching `.env` / SSH keys / credentials → always ask
- code runs in a sandboxed temp folder; nothing runs when no terminal is watching
- everything is logged to `~\.omni\logs\session_*.log`
- switch level any time: `/trust`, `/guard`, `/cautious`

---

## 4. Commands inside OMNI

```
help                 this help
/trust /guard /cautious   permission level
/brain               show connected brain + all free options
/setup               connect / switch a free AI key
/model <provider>    switch brain provider (gemini, groq, openrouter, github, ollama)
/workspace <folder>  change where OMNI creates files
/memory <text>       save a fact          /forget <text>
/schedules           list reminders       /cancel <id>
/doctor              diagnose problems (network, keys, Chrome…)
/logs                session log location
/status              what's running
```

One-shot mode (great for Task Scheduler automations):
```bat
omni "search what time it is in Tokyo and email me the answer"
```

---

## 5. Where things live

| What | Where |
|---|---|
| OMNI files (repo) | the folder you cloned |
| OMNI workspace (created files) | `C:\Users\you\omni-workspace` (change with `/workspace`) |
| API keys | `~\.omni\.env` — never inside the repo |
| Permissions & config | `~\.omni\config.json`, `~\.omni\permissions.json` |
| Long-term memory | `~\.omni\memory.json` |
| Reminders/schedules | `~\.omni\automations.json` |
| Session logs | `~\.omni\logs\` |

---

## 6. Privacy & honesty notes

- Keys stay in your `~\.omni\.env` (never committed, never sent anywhere except the provider you chose).
- Searches go to public search engines; no telemetry is built in (`telemetry` config is off).
- With Ollama as the brain, **nothing leaves your laptop at all** for thinking — only the web tools you trigger use the internet.
- OMNI will **not** spend money, change accounts, or impersonate you — it says so and asks for human steps instead.

---

## 7. Uninstall / reset

- Remove the `omni` command: delete `%USERPROFILE%\.omni-bin` and remove that entry from your PATH (System Settings → Environment Variables).
- Reset OMNI fully: delete the project folder + `~\.omni` + `~\.omni-bin`.

---

## 8. For developers

```
omni/__init__.py       package
omni/cli.py            entry point (python -m omni)
omni/repl.py           REPL, commands, scheduler
omni/agent.py          the reasoning loop + permission gating
omni/tools/            every power = one registered tool
  web.py               search / fetch / verify
  code.py              files + python/script runner
  system.py            shell, machine control
  browser.py           selenium browser automation (optional)
  automation.py        reminders, schedules, csv/json, email, notify
  memory_tool.py       long-term memory
omni/providers.py      free AI providers (gemini/groq/openrouter/github/ollama/custom)
omni/permissions.py    risk engine (guarded/trusted/cautious + always/never rules)
```

**Add a new power** — register a function:
```python
from omni.tools import register

@register("my_tool", "what it does", {"type": "object", "properties": {...}},
          risk="changes", category="general")
def my_tool(ctx, arg):   # ctx gives workspace, state, log…
    return "result"
```

**Tests** (offline, no keys needed):
```bat
python tests\smoke.py        :: 61 checks: registry, permissions, tools
python tests\e2e_mock.py     :: full loop vs a fake local brain
```

> ⚠ OMNI is powerful by design — it executes real code and real commands on
> your PC with your approval. Use the permission levels and review what it
> asks. That's the deal: **all powers, your permission.**
