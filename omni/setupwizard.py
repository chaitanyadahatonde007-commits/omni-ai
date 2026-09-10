"""Interactive one-time setup wizard — connect a free brain in ~1 minute."""
from __future__ import annotations

import json

from omni import config, providers

OPTIONS = {
    "gemini": ("Google Gemini", "free key at https://aistudio.google.com/apikey  (paste the key)"),
    "groq": ("Groq (fast free tier)", "free key at https://console.groq.com/keys"),
    "openrouter": ("OpenRouter (many free models)", "free key at https://openrouter.ai/keys"),
    "github": ("GitHub Models (free GPT-4o-mini)", "free token: https://github.com/settings/tokens  (classic token, no scopes needed, then paste it)"),
    "ollama": ("Ollama — 100% local & private", "no key! install https://ollama.com then:  ollama pull qwen3:8b"),
    "custom": ("Custom OpenAI-compatible endpoint", "needs CUSTOM_ENDPOINT + CUSTOM_API_KEY"),
}


def run(ui) -> None:
    c = ui.console
    c.print("[bold cyan]OMNI setup — pick a free brain[/bold cyan]")
    c.print("[dim]One key gives you the whole power grid. (You can add more later.)[/dim]\n")
    keys = list(OPTIONS)
    for i, k in enumerate(keys, 1):
        name, how = OPTIONS[k]
        print(f"  {i}) {name}")
        print(f"     {how}")
    while True:
        raw = ui._read("> choose 1-6 (or 0 to skip): ").strip()
        if raw in ("0", ""):
            return "skip"
        if raw.isdigit() and 1 <= int(raw) <= len(keys):
            break
    provider = keys[int(raw) - 1]
    if provider == "ollama":
        print("\n→ install Ollama from https://ollama.com, then in a terminal run:")
        print("   ollama pull qwen3:8b")
        print("→ restart this session and OMNI will find it automatically.\n")
        config.set_config("provider_order", ["ollama"] + [k for k in keys if k != "ollama"])
        return "ollama"
    env = providers.KEY_ENV[provider]
    c.print(f"\n[bold]{OPTIONS[provider][0]}[/bold] — {OPTIONS[provider][1]}")
    if provider == "custom":
        ep = ui._read("CUSTOM_ENDPOINT (full https URL of /chat/completions): ").strip()
        if ep:
            config.save_secret("CUSTOM_ENDPOINT", ep)
    else:
        ep = None
    while True:
        val = ui._read(f"{env}= ").strip()
        if val:
            break
    config.save_secret(env, val)
    config.set_config("provider_order", [provider] + [k for k in keys if k != provider])
    c.print("[dim]testing connection…[/dim]")
    got = providers.pick_first_working(provider=provider, max_models=3)
    if got:
        c.print(f"[bold green]✓ Connected! Brain online:[/bold green] {providers.provider_label(*got)}")
        config.set_config("brain", {"provider": got[0], "model": got[1]})
    else:
        c.print("[bold red]✗ Could not reach the API with that key.[/bold red] "
                "Check it, re-run /setup, or see /doctor.")
    return provider
