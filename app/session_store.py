"""Chat session persistence.

Deliberately separate from the Code Mode session file: one is conversation
history, the other is a record of suspended processes. They collided once, and
the collision is why this lives in its own module now.

Every function is pure enough to test without a window: `load_session` always
returns the same three keys, whatever is on disk.
"""

from __future__ import annotations

import json
import os

ROLES = ("user", "assistant")
MODES = ("chat", "code")
MAX_MESSAGES = 200
DEFAULT = {"mode": "code", "model": "", "messages": []}


def base_dir() -> str:
    root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(root, "CodeMode")


def session_path() -> str:
    return os.path.join(base_dir(), "chat-session.json")


def clean_messages(raw) -> list:
    """Keep only what the UI can render: user/assistant turns with real text."""
    cleaned = []
    if not isinstance(raw, list):
        return cleaned
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        role = entry.get("role")
        content = entry.get("content")
        if role not in ROLES:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        cleaned.append({"role": role, "content": content})
    return cleaned[-MAX_MESSAGES:]


def load_session(path: str | None = None) -> dict:
    """Never raises: a missing or corrupt file is an empty session, not a crash."""
    data = {"mode": DEFAULT["mode"], "model": DEFAULT["model"], "messages": []}
    try:
        with open(path or session_path(), "r", encoding="utf-8", errors="replace") as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return data
    if not isinstance(raw, dict):
        return data
    mode = raw.get("mode")
    if mode in MODES:
        data["mode"] = mode
    model = raw.get("model")
    if isinstance(model, str):
        data["model"] = model
    data["messages"] = clean_messages(raw.get("messages"))
    return data


def save_session(data: dict, path: str | None = None) -> bool:
    """Atomic write: a half-written session file would be indistinguishable from
    a corrupt one on the next boot."""
    target = path or session_path()
    payload = {
        "mode": data.get("mode") if data.get("mode") in MODES else DEFAULT["mode"],
        "model": str(data.get("model") or ""),
        "messages": clean_messages(data.get("messages")),
    }
    try:
        folder = os.path.dirname(target)
        if folder:
            os.makedirs(folder, exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, target)
        return True
    except OSError:
        return False
