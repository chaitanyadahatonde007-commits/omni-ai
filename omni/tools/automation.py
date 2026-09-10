"""AUTOMATION POWER TOOLS — reminders & scheduled actions, data files, notices.

Reminders/schedules live in ~/.omni/automations.json and fire while OMNI is
running (its scheduler thread watches them every 20s).
"""
from __future__ import annotations

import csv
import io
import json
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from omni import config
from omni.tools import register

SCHED_LOCK = threading.Lock()


def _load_schedules() -> list[dict]:
    f = config.data_dir() / "automations.json"
    try:
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_schedules(items: list[dict]) -> None:
    f = config.data_dir() / "automations.json"
    f.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _parse_when(when: str) -> datetime | None:
    """Accept: 'in 5 minutes', 'in 2 hours', 'at 14:30', 'tomorrow 9am'."""
    w = when.strip().lower()
    now = datetime.now()
    if w.startswith("in "):
        rest = w[3:].strip()
        parts = rest.split()
        if len(parts) >= 2 and parts[1].startswith(("minute", "min")):
            return now + timedelta(minutes=int(parts[0]))
        if len(parts) >= 2 and parts[1].startswith(("hour", "hr")):
            return now + timedelta(hours=int(parts[0]))
        if len(parts) >= 2 and parts[1].startswith(("day",)):
            return now + timedelta(days=int(parts[0]))
        try:
            return now + timedelta(minutes=int(rest))
        except Exception:
            return None
    if w.startswith("at "):
        try:
            hh, mm = w[3:].split(":")[:2]
            t = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            if t < now:
                t += timedelta(days=1)
            return t
        except Exception:
            return None
    if w.startswith("tomorrow"):
        t = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        return t
    return None


def _remind(ctx, when: str, message: str) -> str:
    target = _parse_when(when)
    if not target:
        return f"could not parse when='{when}'. Try: 'in 10 minutes', 'at 14:30', 'tomorrow 9am'"
    item = {"id": uuid.uuid4().hex[:8], "type": "reminder", "at": target.isoformat(),
            "message": message, "created": datetime.now().isoformat()}
    with SCHED_LOCK:
        items = _load_schedules()
        items.append(item)
        _save_schedules(items)
    return f"✓ reminder set for {target.strftime('%Y-%m-%d %H:%M')} — I'll pop it on screen"


def _schedule_task(ctx, when: str, task: str) -> str:
    target = _parse_when(when)
    if not target:
        return f"could not parse when='{when}'."
    item = {"id": uuid.uuid4().hex[:8], "type": "task", "at": target.isoformat(),
            "task": task, "created": datetime.now().isoformat()}
    with SCHED_LOCK:
        items = _load_schedules()
        items.append(item)
        _save_schedules(items)
    return (f"✓ scheduled for {target.strftime('%Y-%m-%d %H:%M')}.\n"
            "Note: tasks fire while this OMNI session is open. For 24/7 unattended "
            "scheduling, later run OMNI via Task Scheduler (see docs).")


def _list_schedules(ctx) -> str:
    items = _load_schedules()
    if not items:
        return "no reminders/schedules set"
    now = datetime.now()
    lines = []
    for it in sorted(items, key=lambda x: x.get("at", "")):
        try:
            at = datetime.fromisoformat(it["at"])
        except Exception:
            at = None
        status = "⏰ due" if at and at <= now else ("🕒 " + at.strftime("%d %b %H:%M") if at else "?")
        what = it.get("message") or it.get("task") or ""
        lines.append(f"[{status}] ({it.get('id')}) {what[:120]}")
    return "\n".join(lines)


def _cancel_schedule(ctx, id_or_text: str) -> str:
    items = _load_schedules()
    remaining = [it for it in items if it.get("id") != id_or_text and id_or_text.lower() not in (it.get("message") or it.get("task") or "").lower()]
    if len(remaining) == len(items):
        return f"no schedule matches '{id_or_text}'"
    with SCHED_LOCK:
        _save_schedules(remaining)
    return f"cancelled {len(items) - len(remaining)} schedule(s)"


def due_items() -> list[dict]:
    """Return due items and REMOVE them from the store (fire once)."""
    now = datetime.now()
    out = []
    with SCHED_LOCK:
        items = _load_schedules()
        due = []
        for it in items:
            try:
                at = datetime.fromisoformat(it["at"]) if isinstance(it.get("at"), str) else now
            except Exception:
                at = now
            if it.get("fired") is not True and at <= now:
                it["fired"] = True
                due.append(it)
        if due:
            remaining = [it for it in items
                         if it not in due and it.get("fired") is not True]
            _save_schedules(remaining)
    return due


def _make_csv(ctx, path: str, headers: str, rows: str) -> str:
    import os
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    hdrs = [h.strip() for h in headers.split(",")]
    parsed = list(csv.reader(io.StringIO(rows)))
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(hdrs)
        w.writerows(parsed)
    return f"CSV saved: {p} ({len(parsed)} rows × {len(hdrs)} columns)"


register(
    "make_csv", "Create a spreadsheet-ready CSV file. headers = comma-separated column names; rows = one data row per line with commas (quote fields containing commas).",
    {"type": "object", "properties": {"path": {"type": "string", "description": "file path, e.g. data.csv"}, "headers": {"type": "string"}, "rows": {"type": "string"}}, "required": ["path", "headers", "rows"]},
    risk="changes", category="automation",
)(lambda ctx, path, headers, rows: _make_csv(ctx, path, headers, rows))


def _make_json(ctx, path: str, content: str) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(content)
    except Exception as e:
        return f"invalid JSON content: {e}"
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"JSON saved: {p}"


register(
    "make_json", "Save structured data as a JSON file from JSON text.",
    {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
    risk="changes", category="automation",
)(lambda ctx, path, content: _make_json(ctx, path, content))


def _send_email(ctx, to: str, subject: str, body: str, attach: str = "") -> str:
    """SMTP send — only when SMTP_* secrets are configured (see /setup)."""
    s = config.load_secrets()
    host, port = s.get("SMTP_HOST"), s.get("SMTP_PORT")
    user, pw = s.get("SMTP_USER"), s.get("SMTP_PASSWORD")
    if not (host and user and pw):
        return ("SMTP not configured. In OMNI type /setup and choose 'Gmail/email "
                "sending' (free app-password) — needs SMTP_HOST, SMTP_USER, SMTP_PASSWORD.")
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = user, to, subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if attach:
        ap = Path(attach).expanduser()
        if ap.exists():
            with open(ap, "rb") as f:
                msg.attach(MIMEApplication(f.read(), _subtype="octet-stream"))
            msg.attach.get_payload()[-1].add_header("Content-Disposition", "attachment", filename=ap.name)
    port = int(port or 587)
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        if port == 587:
            smtp.starttls()
        smtp.login(user, pw)
        smtp.sendmail(user, [to], msg.as_string())
    return f"email sent to {to} (subject: {subject})"


register(
    "send_email", "Send an email (requires one-time free SMTP setup via /setup). For notifications, reports, sharing results.",
    {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}, "attach": {"type": "string", "description": "optional file path to attach"}}, "required": ["to", "subject", "body"]},
    risk="danger", category="automation",
)(lambda ctx, to, subject, body, attach="": _send_email(ctx, to, subject, body, attach))


def _notify(ctx, message: str) -> str:
    """Desktop notification (Windows toast via PowerShell / notify-send)."""
    style = ctx.shell_style
    msg = message[:220].replace('"', "'")
    try:
        if style != "bash":
            import subprocess
            ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
                  "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                  "$textNodes = $template.GetElementsByTagName('text');"
                  f"$textNodes.Item(0).AppendChild($template.CreateTextNode('OMNI')) > $null;"
                  f"$textNodes.Item(1).AppendChild($template.CreateTextNode('{msg}')) > $null;"
                  "$toast = [Windows.UI.Notifications.ToastNotification]::new($template);"
                  "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('OMNI').Show($toast)")
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps],
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return "notification shown ✓"
        import subprocess
        subprocess.Popen(["notify-send", "OMNI", msg])
        return "notification shown ✓"
    except Exception as e:
        return f"could not notify: {e}"


register(
    "notify", "Pop a Windows notification toast on the user's screen (used for reminders & important updates).",
    {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
    risk="changes", category="automation",
)(lambda ctx, message: _notify(ctx, message))


register(
    "remind_me", "Set a reminder that pops on screen later. when: 'in 5 minutes', 'in 2 hours', 'at 14:30', 'tomorrow 9am'.",
    {"type": "object", "properties": {"when": {"type": "string"}, "message": {"type": "string"}}, "required": ["when", "message"]},
    risk="changes", category="automation",
)(_remind)


register(
    "schedule_task", "Schedule a task for later in THIS session (fires while OMNI is open, shows up in chat). when format like reminders.",
    {"type": "object", "properties": {"when": {"type": "string"}, "task": {"type": "string"}}, "required": ["when", "task"]},
    risk="changes", category="automation",
)(_schedule_task)


register(
    "list_schedules", "List current reminders and scheduled tasks.",
    {"type": "object", "properties": {}},
    risk="safe", category="automation",
)(lambda ctx: _list_schedules(ctx))


register(
    "cancel_schedule", "Cancel a reminder/schedule by its id or matching text.",
    {"type": "object", "properties": {"id_or_text": {"type": "string"}}, "required": ["id_or_text"]},
    risk="changes", category="automation",
)(_cancel_schedule)
