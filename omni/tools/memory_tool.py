"""MEMORY POWER TOOL — persistent long-term memory across sessions
(~/.omni/memory.json): facts, preferences, project state, learned tricks.
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from omni import config

_MAX_ENTRIES = 500


def _load() -> list[dict]:
    f = config.home_dir() / "memory.json"
    try:
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _save(items: list[dict]) -> None:
    config.home_dir().joinpath("memory.json").write_text(
        json.dumps(items[-_MAX_ENTRIES:], indent=2, ensure_ascii=False), encoding="utf-8")


def memory_entries() -> list[dict]:
    return _load()


def remember_text(ctx, text: str, tag: str = "fact") -> str:
    items = _load()
    items.append({"text": text.strip(), "tag": tag,
                  "at": datetime.now().isoformat(timespec="seconds")})
    _save(items)
    return "remembered ✓ (long-term memory)"


def recall_text(ctx, query: str = "", tag: str = "", limit: int = 10) -> str:
    items = _load()
    q = (query or "").lower()
    if q or tag:
        items = [i for i in items
                 if (not q or q in i.get("text", "").lower() or q in i.get("tag", "").lower())
                 and (not tag or tag == i.get("tag"))]
    if not items:
        return "(memory is empty / nothing matches)"
    out = []
    for i in items[-int(limit):]:
        out.append(f"[{i.get('at', '?')}] ({i.get('tag', 'fact')}) {i.get('text', '')[:300]}")
    return "\n".join(out)


def forget_text(ctx, query: str) -> str:
    items = _load()
    q = query.lower()
    kept = [i for i in items if q not in i.get("text", "").lower()]
    if len(kept) == len(items):
        return f"nothing matching '{query}' in memory"
    _save(kept)
    return f"forgot {len(items) - len(kept)} memory item(s)"


from omni.tools import register  # noqa: E402

register("remember", "Save a fact/preference to long-term memory (survives restarts, loaded next session). Use for user info, decisions, project notes.",
         {"type": "object", "properties": {"text": {"type": "string"}, "tag": {"type": "string", "description": "optional category: fact|preference|project|trick"}},
          "required": ["text"]}, risk="changes", category="memory")(remember_text)

register("recall", "Search long-term memory.",
         {"type": "object", "properties": {"query": {"type": "string"}, "tag": {"type": "string"}, "limit": {"type": "integer"}},
          "required": []}, risk="safe", category="memory")(recall_text)

register("forget", "Delete memory items matching text.",
         {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
         risk="changes", category="memory")(forget_text)
