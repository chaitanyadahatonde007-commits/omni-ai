"""AI PROVIDER LAYER — every free brain OMNI can use.

  gemini     Google Gemini Flash (free API key @ aistudio.google.com)
             candidate models: gemini-2.0-flash, gemini-2.5-flash,
             gemini-1.5-flash, gemini-2.5-flash-lite, gemini-2.0-flash-lite
  groq       Groq free tier (console.groq.com) — llama-3.3-70b / deepseek…
  openrouter OpenRouter free models (openrouter.ai, model ends in ":free")
  github     GitHub Models free tier (github.com/settings/tokens) — gpt-4o-mini
  ollama     fully LOCAL (ollama.com) — no key, private, offline
  custom     any OpenAI-compatible endpoint

OMNI walks the provider list and uses the first one that has a key AND works.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from omni import config

log = logging.getLogger("omni.providers")

FREE_CANDIDATES = {
    "gemini": ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-flash",
               "gemini-2.5-flash-lite", "gemini-2.0-flash-lite"],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant",
             "deepseek-r1-distill-llama-70b", "qwen-2.5-32b"],
    "openrouter": ["deepseek/deepseek-chat-v3-0324:free", "google/gemini-2.0-flash-001:free",
                   "meta-llama/llama-3.3-70b-instruct:free", "qwen/qwen-2.5-72b-instruct:free",
                   "mistralai/mistral-small-3.1-24b-instruct:free"],
    "github": ["gpt-4o-mini", "gpt-4.1-mini", "o4-mini"],
    "ollama": ["qwen3:4b", "qwen3:8b", "llama3.2:3b", "llama3.1:8b"],
    "custom": [],
}

KEY_ENV = {
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "github": "GITHUB_TOKEN",
    "ollama": None,
    "custom": "CUSTOM_API_KEY",
}

ENDPOINT = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "github": "https://models.inference.ai.azure.com/chat/completions",
    "custom": None,  # from config secrets CUSTOM_ENDPOINT
    "ollama": "http://localhost:11434/v1/chat/completions",
}


class ProviderError(Exception):
    pass


def configured_providers() -> list[str]:
    """Providers that have credentials present (ollama always 'configured')."""
    secrets = config.load_secrets()
    order = [p for p in config.get("provider_order", []) if p in FREE_CANDIDATES]
    return [p for p in order if KEY_ENV[p] is None or secrets.get(KEY_ENV[p])]


def provider_label(p: str, model: str = "") -> str:
    base = {"gemini": "Google Gemini", "groq": "Groq", "openrouter": "OpenRouter",
            "github": "GitHub Models", "ollama": "Ollama (local)", "custom": "Custom"}.get(p, p)
    return f"{base} · {model}" if model else base


def _candidate_models(provider: str, secrets: dict) -> list[str]:
    over = (config.get("model_candidates", {}) or {}).get(provider)
    if over:
        return over
    return FREE_CANDIDATES.get(provider, [])


def _ollama_model_fallback() -> list[str]:
    """Ask a running local Ollama what models it has (only first few)."""
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as r:
            data = json.loads(r.read().decode())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def list_providers_status() -> str:
    secrets = config.load_secrets()
    lines = []
    for p in FREE_CANDIDATES:
        if p == "ollama":
            try:
                models = _ollama_model_fallback()
                st = f"✓ ready ({', '.join(models[:3]) or 'run `ollama pull qwen3:8b`'})"
            except Exception:
                st = "not running (install Ollama + pull a model)"
        elif p == "custom":
            st = "✓ ready" if secrets.get("CUSTOM_ENDPOINT") else "no CUSTOM_ENDPOINT set"
        else:
            env = KEY_ENV[p]
            st = "✓ key found" if secrets.get(env) else "no key (see /setup)"
        lines.append(f"  {p:<11} {st}")
    return "\n".join(lines)


# ------------------------------------------------------------------ call ----
def chat(provider: str, model: str, messages: list[dict], tools: list | None = None,
         temperature: float = 0.4, max_tokens: int = 4096) -> tuple[str, list | None, str, str]:
    """Returns (text, tool_calls, used_model, used_provider). tool_calls is a
    list of (name, json_args)."""
    secrets = config.load_secrets()
    if provider == "gemini":
        return _gemini_chat(model, messages, tools, temperature, max_tokens, secrets)
    return _oai_chat(provider, model, messages, tools, temperature, max_tokens, secrets)


def _post_json(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode("utf-8", "replace")
    return json.loads(body)


def _oai_chat(provider, model, messages, tools, temperature, max_tokens, secrets) -> tuple:
    key = secrets.get(KEY_ENV[provider], "") if KEY_ENV[provider] else ""
    if provider == "ollama":
        url = ENDPOINT["ollama"]
        headers = {"Content-Type": "application/json"}
    else:
        url = secrets.get("CUSTOM_ENDPOINT") if provider == "custom" else ENDPOINT[provider]
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://github.com/omni-agent"
            headers["X-Title"] = "OMNI agent"
    payload: dict = {"model": model, "messages": messages,
                     "temperature": temperature, "max_tokens": max_tokens}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    try:
        resp = _post_json(url, payload, headers)
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        raise ProviderError(f"HTTP {e.code} from {provider}: {detail}")
    except urllib.error.URLError as e:
        raise ProviderError(f"network error ({e.reason}) for {provider}")
    if "error" in resp:
        raise ProviderError(f"API error: {json.dumps(resp['error'])[:400]}")
    msg = resp["choices"][0]["message"]
    text = msg.get("content") or ""
    calls = []
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except Exception:
            args = {"_raw": fn.get("arguments", "")}
        calls.append((fn.get("name", ""), args))
    used = resp.get("model") or model
    return text, calls, used, provider


def _gemini_chat(model, messages, tools, temperature, max_tokens, secrets) -> tuple:
    key = secrets.get("GEMINI_API_KEY", "")
    # drop system role into first user preamble (Gemini REST has no 'system')
    sys_texts = [m["content"] for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    contents = []
    for m in rest:
        role = "model" if m["role"] == "assistant" else "user"
        if m.get("role") == "tool":
            # tool result -> user part
            contents.append({"role": "user", "parts": [{"text": "[tool result] " + str(m.get("content", ""))[:8000]}]})
            continue
        parts = [{"text": str(m.get("content", ""))}]
        contents.append({"role": role, "parts": parts})
    if sys_texts:
        joined = "\n\n".join(sys_texts)
        # gemini tool mode ignores systemInstruction? include anyway via config
    body: dict = {"contents": contents,
                  "generationConfig": {"temperature": temperature,
                                       "maxOutputTokens": max_tokens}}
    if sys_texts:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(sys_texts)}]}
    if tools:
        decls = []
        for t in tools:
            if t.get("type") == "function":
                f = t["function"]
                decls.append({"name": f["name"], "description": f["description"],
                              "parameters": f.get("parameters", {})})
        body["tools"] = [{"functionDeclarations": decls}]
        body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
           f":generateContent?key={key}")
    try:
        resp = _post_json(url, body, {"Content-Type": "application/json"})
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            pass
        code = e.code
        raise ProviderError(f"HTTP {code} from Gemini ({model}): {detail}")
    except urllib.error.URLError as e:
        raise ProviderError(f"network error ({e.reason}) for Gemini")
    cand = (resp.get("candidates") or [{}])[0]
    if not cand:
        fb = resp.get("promptFeedback", {})
        raise ProviderError(f"no candidate returned: {json.dumps(fb)[:300]}")
    parts = cand.get("content", {}).get("parts", [])
    text_parts, calls = [], []
    for p in parts:
        if "text" in p:
            text_parts.append(p["text"])
        elif "functionCall" in p:
            fc = p["functionCall"]
            calls.append((fc.get("name", ""), fc.get("args", {})))
    used = resp.get("modelVersion") or model
    return "".join(text_parts), calls, used, "gemini"


def pick_first_working(provider: str | None = None, max_models: int = 4) -> tuple | None:
    """Try providers in configured order until a chat call succeeds on
    'ping' (no tools). Returns (provider, model) or None."""
    secrets = config.load_secrets()
    providers = [provider] if provider else configured_providers()
    # always try ollama when explicitly requested or nothing else configured
    for p in providers:
        models = _candidate_models(p, secrets)
        if p == "ollama" and not models:
            models = _ollama_model_fallback()[:max_models]
        if not models:
            continue
        for m in models[:max_models]:
            try:
                text, _, used, _ = chat(p, m,
                    [{"role": "user", "content": "Reply with exactly: OK"}],
                    tools=None, max_tokens=20)
                if "ok" in text.lower() or text.strip():
                    log.info("brain online: %s via %s (reported model %s)", m, p, used)
                    return p, m
            except Exception as e:  # noqa: BLE001
                log.info("model %s via %s failed: %s", m, p, str(e)[:160])
                time.sleep(0.4)
    return None
