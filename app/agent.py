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


def build_system(cfg: dict, workspace: str) -> str:
    parts = (skills.preamble(), memory.handoff_note(), cfg.get("system", ""),
             toolbox.system_help(workspace))
    return "\n\n".join(part for part in parts if part)


def stream_agent(backend: dict, model: str, messages: list, cfg: dict,
                 workspace: str, allow_shell: bool = True, max_steps: int = 5):
    """Yields {'delta'|'tool_start'|'tool_result'|'error': ...} events."""
    history = list(messages)
    for _step in range(max_steps):
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

        match = TOOL_RE.search(buffer)
        if not match:
            if len(buffer) > emitted:
                yield {"delta": buffer[emitted:]}
            return

        try:
            call = json.loads(match.group(1))
        except json.JSONDecodeError:
            yield {"tool_result": "bad tool JSON, ignored: %s" % match.group(1)[:200]}
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
