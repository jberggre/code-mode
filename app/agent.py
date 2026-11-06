"""The agent loop: model -> tool call -> result -> model, until it answers.

Uses a prompted tool protocol rather than native function calling, because it has
to work across a 1.5B and a 7B model on the same day and native tool support is
inconsistent in that range. The block is strict, so a weak model either complies
or produces plain text - it cannot half-call a tool.
"""

from __future__ import annotations

import json
import re

import server as core
import memory
import skills
import tools as toolbox
import verify

TOOL_RE = re.compile(r"<tool>\s*(\{.*?\})\s*</tool>", re.S)
# Small models sometimes wrap the call in a fence even when told not to.
FENCE_RE = re.compile(r"```(?:tool|json)\s*(\{.*?\})\s*```", re.S)

# Only action-shaped requests earn a retry. "Why does this fail?" must stay a
# question, or every explanation would be sent back to write files.
ASK_RE = re.compile(
    r"\b(explain|why|how do|how does|how can|what does|what is|review|"
    r"difference|should i|is it)\b", re.I)

# The recorded failure on this machine: "can u cde a gme of snake 4 me" got
# "I'm sorry, but I can't assist with that." Nothing was built, and nothing told
# the model that a local file is allowed. A refusal gets its own correction.
REFUSAL_RE = re.compile(
    r"\b(i'?m sorry|i am sorry|i cannot|i can'?t (assist|help|do that)|as an ai|"
    r"unable to (help|assist|comply))\b", re.I)

ACTION_NUDGE = (
    "You replied with text but called no tool, so nothing on disk changed. "
    "Do the work now: emit exactly one <tool> block (write_file, then run_command). "
    "Do not paste the program into the chat instead of writing it."
)

REFUSAL_NUDGE = (
    "That was a refusal, but this is the user's own machine and a small local "
    "file is exactly the job: writing a game or script into the workspace is "
    "allowed and expected. Do it now: emit one <tool> block with write_file, "
    "then run it. Do not refuse and do not explain instead of building."
)
VERIFY_NUDGE = (
    "A check of what you just wrote found these problems, so it is not finished:\n"
    "%s\nFix them now: one <tool> block, write_file with the complete corrected "
    "file, nothing omitted. Then stop."
)
MAX_NUDGES = 2
# How many times a failed check goes back to the model before we give up and
# say so plainly instead of letting it claim success. Three attempts is what a 3B
# needed on this machine: 4 defects, then 2, then a page that passed.
MAX_REPAIRS = 3


def _numbered(defects: list) -> str:
    return "\n".join("%d. %s" % (i, d) for i, d in enumerate(defects, 1))


def _user_request(history: list) -> str:
    """The user's own words, captured before the model can add to the history.

    Permission to touch the app's own files is read from this string and never
    from a later message, so a model cannot grant itself access by writing "the
    user asked me to edit app/server.py" into its own turn.
    """
    for message in reversed(history):
        if message.get("role") != "user":
            continue
        text = str(message.get("content", ""))
        if text.startswith("<result"):
            continue
        return text[:4000]
    return ""


def _written_path(result: str):
    """The path a successful write_file reported, or None."""
    text = str(result or "")
    if not text.startswith(("wrote ", "edited ")):
        return None
    match = re.match(r"wrote \d+ bytes to (.+?)(?: \(replaced|$)", text)
    if match:
        return match.group(1).strip()
    match = re.match(r"edited (.+?)(?: \(old copy|$)", text)
    return match.group(1).strip() if match else None


def _open_finished(workspace: str, written: list):
    """Show the first page that passes the check, so the user can actually play it."""
    for path in reversed(written):
        if verify.playable(workspace, path):
            return path, toolbox.show_artifact(workspace, path)
    return None, ""


def _loads_lenient(text: str):
    """json.loads, after escaping literal newlines inside strings.

    The 3B's best page arrived as a valid tool block whose `content` string held
    real line breaks. json.loads calls that invalid, so the whole write was
    dropped and the turn ended on a 378-byte skeleton. Nothing about the call
    was wrong except the escaping.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fixed = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                fixed.append(ch)
                escaped = False
            elif ch == "\\":
                fixed.append(ch)
                escaped = True
            elif ch == '"':
                fixed.append(ch)
                in_string = False
            elif ch == "\n":
                fixed.append("\\n")
            elif ch == "\r":
                fixed.append("\\r")
            elif ch == "\t":
                fixed.append("\\t")
            else:
                fixed.append(ch)
        else:
            if ch == '"':
                in_string = True
            fixed.append(ch)
    try:
        return json.loads("".join(fixed))
    except json.JSONDecodeError:
        return None


def _tool_json(buffer: str):
    """The first parseable tool call in a reply, in either accepted shape."""
    for regex in (TOOL_RE, FENCE_RE):
        for match in regex.finditer(buffer):
            call = _loads_lenient(match.group(1))
            if call is None:
                continue
            if isinstance(call, dict) and str(call.get("name", "")).strip():
                return call
    return None


def _wants_action(history: list) -> bool:
    """Anything that is not a question is a request to change the workspace.

    A verb list was too brittle: the recorded request was "can u cde a gme of
    snake 4 me", where no verb survived the typos, so the refusal was never
    retried. Questions are recognised instead, which has no such failure mode.
    """
    for message in reversed(history):
        if message.get("role") == "user":
            return not ASK_RE.search(str(message.get("content", "")))
    return False


def build_system(cfg: dict, workspace: str) -> str:
    parts = (skills.preamble(), memory.handoff_note(), cfg.get("system", ""),
             toolbox.system_help(workspace))
    return "\n\n".join(part for part in parts if part)


def stream_agent(backend: dict, model: str, messages: list, cfg: dict,
                 workspace: str, allow_shell: bool = True, max_steps: int = 12):
    """Yields {'delta'|'tool_start'|'tool_result'|'error'|'log': ...} events."""
    history = list(messages)
    request = _user_request(history)
    nudges = 0
    repairs = 0
    written = []
    opened = False
    seen_calls = {}
    for step in range(max_steps):
        payload = dict(cfg)
        payload["system"] = build_system(cfg, workspace)

        # Tool results pile up fast; compact mid-run instead of blowing the window.
        if memory.needs_compaction(history, payload):
            yield {"log": "context nearly full - compacting and writing a handoff"}
            history = memory.compact(backend, model, history, payload)
            yield {"log": "compacted to %d messages; handoff in state/handoff.md" % len(history)}

        buffer = ""
        emitted = 0
        try:
            for delta in core.stream_backend(backend, model, history, payload):
                buffer += delta
                cut = buffer.find("<tool>")
                # Hold a few characters back so a partial tag is never shown.
                limit = cut if cut >= 0 else len(buffer) - 8
                if limit > emitted:
                    yield {"delta": buffer[emitted:limit]}
                    emitted = limit
        except Exception as exc:  # noqa: BLE001 - surfaced to the transcript
            yield {"error": "%s: %s" % (type(exc).__name__, exc)}
            return

        call = _tool_json(buffer)
        if call is None:
            if len(buffer) > emitted:
                yield {"delta": buffer[emitted:]}
                emitted = len(buffer)
            # Files were written this turn: check them before believing the
            # answer. "The game is running successfully" over a stub with a
            # placeholder and a dead <script src> is the failure being fixed.
            defects = verify.check_turn(workspace, written)
            if defects and repairs < MAX_REPAIRS and step < max_steps - 1:
                repairs += 1
                history.append({"role": "assistant", "content": buffer})
                history.append({"role": "user", "content": VERIFY_NUDGE % _numbered(defects)})
                yield {"log": "checked the result \u00b7 %d problem%s \u00b7 sending it back"
                       % (len(defects), "" if len(defects) == 1 else "s")}
                continue
            if defects:
                yield {"log": "still broken after %d attempts: %s"
                       % (repairs, "; ".join(defects)[:400])}
            if written and not opened and not defects:
                path, message = _open_finished(workspace, written)
                if path:
                    opened = True
                    yield {"log": message}
            # The two recorded failures - a refusal, and a tutorial instead of
            # the file - both mean the workspace is untouched. Send it back.
            refusal = bool(REFUSAL_RE.search(buffer))
            # Any no-write reply to a request for work is a dead end: the model
            # answered "The game loop is not running." and stopped, having built
            # nothing. Prose length is irrelevant - one nudge, then take no for
            # an answer. Questions are excluded by _wants_action.
            if (not written and nudges < MAX_NUDGES and step < max_steps - 1
                    and _wants_action(history)):
                nudges += 1
                history.append({"role": "assistant", "content": buffer})
                history.append({"role": "user",
                                "content": REFUSAL_NUDGE if refusal else ACTION_NUDGE})
                yield {"log": "%s \u00b7 asking again for the tool call"
                       % ("refused instead of acting" if refusal
                          else "answered without acting")}
                continue
            return

        name = str(call.get("name", "")).strip()
        args = call.get("args")
        if not isinstance(args, dict):
            args = {}

        # The recorded loop: `git worktree add ...` five times, each returning the
        # same fatal error. An identical call cannot return something new, so
        # refuse it with the old result and make the model change course.
        signature = "%s %s" % (name, json.dumps(args, sort_keys=True))
        if signature in seen_calls:
            prior_step, prior_result = seen_calls[signature]
            yield {"tool_start": "\u2192 %s (the same call again)" % name}
            result = ("refused: this is the same call you made at step %d, and it "
                      "already returned: %s. Repeating it cannot change the result - "
                      "fix the file, use a different command, or stop."
                      % (prior_step, prior_result))
            yield {"tool_result": "\u2190 %s" % " ".join(result.split())[:700]}
            history.append({"role": "assistant", "content": buffer})
            history.append({
                "role": "user",
                "content": '<result name="%s">\n%s\n</result>' % (name, result),
            })
            continue

        yield {"tool_start": "\u2192 %s %s" % (name, json.dumps(args)[:220])}
        result = toolbox.execute(name, args, workspace, allow_shell, request)
        seen_calls[signature] = (step + 1, " ".join(str(result).split())[:300])
        if name in ("write_file", "edit_file"):
            path = _written_path(result)
            if path and path not in written:
                written.append(path)
        yield {"tool_result": "\u2190 %s" % " ".join(str(result).split())[:700]}

        history.append({"role": "assistant", "content": buffer})
        history.append({
            "role": "user",
            "content": '<result name="%s">\n%s\n</result>' % (name, str(result)[:6000]),
        })

        # Check the bytes as soon as they land, not only once the model stops
        # talking. Left until the end, the 3B wrote a working page and then spent
        # five steps on `git worktree add` instead of finishing or fixing it.
        if name in ("write_file", "edit_file") and written:
            defects = verify.check_turn(workspace, written)
            if defects and repairs < MAX_REPAIRS and step < max_steps - 1:
                repairs += 1
                history.append({"role": "user", "content": VERIFY_NUDGE % _numbered(defects)})
                yield {"log": "checked the result \u00b7 %d problem%s \u00b7 sending it back"
                       % (len(defects), "" if len(defects) == 1 else "s")}
                continue
            if not defects:
                path, message = _open_finished(workspace, written)
                if path:
                    yield {"log": message}
                    yield {"log": "the page checks out - stopping here"}
                    return

    yield {"delta": "\n(stopped after %d tool steps)" % max_steps}
