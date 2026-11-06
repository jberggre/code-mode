"""Context survival: compaction, archiving, and cross-session handoff.

An 8192-token window on a 7B model is small. Read three files through tools and
the early conversation is gone - and worse, it was gone *silently*, because
server.trim_messages just drops the oldest turns.

Two layers here:

1. **Compaction.** When history passes ~72% of the context budget, the oldest
   turns are summarised by the model itself into a dense note, the summary is
   spliced back in as the first turn, and the full transcript is archived to
   state/transcripts/ first, so nothing is actually lost.
2. **Handoff.** Every compaction (and the menu item) writes state/handoff.md with
   goal / done / in progress / next step. Every session's system prompt includes
   that file, so a new window continues the work instead of starting over.

No model call is required for the fallback path: if summarising fails, a
mechanical digest of the last turns is used, because losing the reply is worse
than losing the polish.
"""

from __future__ import annotations

import os
import time
from datetime import datetime

import server as core

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
STATE = os.path.join(PROJECT, "state")
TRANSCRIPTS = os.path.join(STATE, "transcripts")
HANDOFF = os.path.join(STATE, "handoff.md")

# Context budget: keep the reply room and a safety margin, same maths as
# server.trim_messages so the two cannot disagree about "full".
MARGIN = 250
COMPACT_AT = 0.65
HANDOFF_TTL_DAYS = 7

SUMMARISE_SYSTEM = (
    "You are compacting a coding session because its context window is full. "
    "Write a handoff note for the next session, in markdown, with exactly these "
    "headings and no preamble:\n"
    "## Goal\n## Done\n## In progress\n## Next step\n## Files and commands\n## Gotchas\n"
    "Facts only: paths, commands, decisions, errors still open, what was tried and "
    "failed. Under 220 words. Do not greet. Do not restate these instructions."
)


def _ensure() -> None:
    os.makedirs(TRANSCRIPTS, exist_ok=True)


def tokens(text: str) -> int:
    return core.est_tokens(str(text or ""))


def budget(cfg: dict) -> int:
    return max(512, cfg["num_ctx"] - cfg["num_predict"] - MARGIN)


def history_tokens(messages: list, cfg: dict) -> int:
    used = tokens(cfg.get("system", ""))
    for msg in messages:
        used += tokens(msg.get("content", "")) + 4
    return used


def needs_compaction(messages: list, cfg: dict, at: float = COMPACT_AT) -> bool:
    if len(messages) < 3:
        return False
    return history_tokens(messages, cfg) > budget(cfg) * at


# --------------------------------------------------------------------------
# Archiving
# --------------------------------------------------------------------------

def archive(messages: list, reason: str = "compaction") -> str:
    """Write the full transcript out before anything is summarised away."""
    if not messages:
        return ""
    _ensure()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(TRANSCRIPTS, "%s-%s.md" % (stamp, reason))
    lines = ["# CodeMode transcript", "", "_archived %s (%s), %d messages_" %
             (datetime.now().strftime("%Y-%m-%d %H:%M"), reason, len(messages)), ""]
    for msg in messages:
        role = str(msg.get("role", "user"))
        body = str(msg.get("content", ""))
        lines.append("## %s" % role)
        lines.append(body if body else "_(empty)_")
        lines.append("")
    try:
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines))
    except OSError:
        return ""
    return path


# --------------------------------------------------------------------------
# Summarising
# --------------------------------------------------------------------------

def _digest(messages: list, cfg: dict) -> str:
    """The transcript as plain text, tail-first, sized to fit the context."""
    parts = []
    for msg in messages:
        if str(msg.get("role")) == "system":
            continue
        parts.append("%s: %s" % (msg.get("role", "user"), str(msg.get("content", ""))))
    text = "\n\n".join(parts)
    limit = int(budget(cfg) * 3.2)  # chars, using the same ~3.6 chars/token guess
    return text[-limit:]


def summarise(backend: dict, model: str, messages: list, cfg: dict) -> str:
    call = dict(cfg)
    call["system"] = SUMMARISE_SYSTEM
    call["temperature"] = 0.2
    call["num_predict"] = 480
    prompt = [{
        "role": "user",
        "content": "Session transcript to compact:\n\n" + _digest(messages, cfg),
    }]
    chunks = []
    try:
        for delta in core.stream_backend(backend, model, prompt, call):
            chunks.append(delta)
    except Exception:  # noqa: BLE001 - fall back to the mechanical digest
        return ""
    text = "".join(chunks).strip()
    return text if len(text) > 40 else ""


def mechanical_summary(messages: list, turns: int = 6) -> str:
    """No model needed: the last asks and the last thing that happened."""
    recent = [m for m in messages if str(m.get("role")) != "system"][-turns:]
    lines = ["## Goal", "(not summarised - the model was unavailable or too small)", "", "## Recent turns"]
    for msg in recent:
        body = " ".join(str(msg.get("content", "")).split())[:240]
        lines.append("- **%s**: %s" % (msg.get("role", "user"), body or "(empty)"))
    lines += ["", "## Next step", "Re-read the transcript in state/transcripts and continue."]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Handoff file
# --------------------------------------------------------------------------

def write_handoff(text: str, source: str = "manual") -> str:
    _ensure()
    body = (
        "# CodeMode handoff\n\n"
        "_written %s by %s_\n\n"
        "%s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M"), source, str(text).strip())
    )
    tmp = HANDOFF + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(body)
        os.replace(tmp, HANDOFF)
    except OSError:
        return ""
    return HANDOFF


def read_handoff() -> str:
    try:
        with open(HANDOFF, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def handoff_age_days() -> float:
    try:
        return (time.time() - os.path.getmtime(HANDOFF)) / 86400.0
    except OSError:
        return -1.0


def clear_handoff() -> None:
    try:
        os.remove(HANDOFF)
    except OSError:
        pass


def handoff_body() -> str:
    """The note without the file header, for display in the transcript."""
    text = read_handoff()
    if not text:
        return ""
    marker = text.find("_\n\n")
    return text[marker + 3:].strip() if marker > 0 else text


def handoff_note(max_chars: int = 1800, ttl_days: float = HANDOFF_TTL_DAYS) -> str:
    """Injected into every system prompt while it is still fresh."""
    body = handoff_body()
    if not body:
        return ""
    age = handoff_age_days()
    if age > ttl_days:
        return ""
    when = "this session" if age < 0.02 else (
        "%.0f hours ago" % (age * 24) if age < 1 else "%.0f days ago" % age)
    return (
        "UNFINISHED WORK FROM AN EARLIER SESSION (handoff written %s).\n"
        "Continue it rather than starting over, unless the user asks otherwise or "
        "the work is already complete - in that case say so and clear the handoff.\n\n"
        "%s" % (when, body[:max_chars])
    )


def resume_note(max_chars: int = 900) -> str:
    """Short version for the transcript banner."""
    body = handoff_body()
    if not body:
        return ""
    age = handoff_age_days()
    head = "handoff from %s" % ("this session" if age < 0.02 else
                                "%.0f h ago" % (age * 24) if age < 1 else "%.0f days ago" % age)
    flat = "\n".join(line for line in body.splitlines() if line.strip())
    return "%s\n%s" % (head, flat[:max_chars])


# --------------------------------------------------------------------------
# The whole operation
# --------------------------------------------------------------------------

def compact(backend: dict, model: str, messages: list, cfg: dict,
            keep: int = 2, source: str = "auto-compaction") -> list:
    """Archive, summarise, write the handoff, and return the shrunken history."""
    messages = [m for m in messages if isinstance(m, dict)]
    if not messages:
        return messages
    archive(messages, "compaction")
    summary = summarise(backend, model, messages, cfg) if backend and model else ""
    if not summary:
        summary = mechanical_summary(messages)
    write_handoff(summary, source)
    note = {
        "role": "user",
        "content": "[summary of earlier turns, compacted to save context]\n" + summary,
    }
    tail = messages[-keep:] if keep > 0 else []
    return [note] + tail
