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
MAX_NUDGES = 2


def _tool_json(buffer: str):
    """The first parseable tool call in a reply, in either accepted shape."""
    for regex in (TOOL_RE, FENCE_RE):
        for match in regex.finditer(buffer):
            try:
                call = json.loads(match.group(1))
            except json.JSONDecodeError:
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


def _looks_like_prose(buffer: str) -> bool:
    """A tutorial or a code listing, not a one-line acknowledgement."""
    return "```" in buffer or len(buffer.strip()) > 300


def build_system(cfg: dict, workspace: str) -> str:
    parts = (skills.preamble(), memory.handoff_note(), cfg.get("system", ""),
             toolbox.system_help(workspace))
    return "\n\n".join(part for part in parts if part)


def stream_agent(backend: dict, model: str, messages: list, cfg: dict,
                 workspace: str, allow_shell: bool = True, max_steps: int = 12):
    """Yields {'delta'|'tool_start'|'tool_result'|'error'|'log': ...} events."""
    history = list(messages)
    nudges = 0
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
            # The two recorded failures - a refusal, and a tutorial instead of
            # the file - both mean the workspace is untouched. Send it back.
            refusal = bool(REFUSAL_RE.search(buffer))
            if (nudges < MAX_NUDGES and step < max_steps - 1 and _wants_action(history)
                    and (refusal or _looks_like_prose(buffer))):
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

        yield {"tool_start": "\u2192 %s %s" % (name, json.dumps(args)[:220])}
        result = toolbox.execute(name, args, workspace, allow_shell)
        yield {"tool_result": "\u2190 %s" % " ".join(str(result).split())[:700]}

        history.append({"role": "assistant", "content": buffer})
        history.append({
            "role": "user",
            "content": '<result name="%s">\n%s\n</result>' % (name, str(result)[:6000]),
        })

    yield {"delta": "\n(stopped after %d tool steps)" % max_steps}
