"""Superpowers skills: discovery, prompt index, on-demand loading.

The upstream repo is cloned into skills/superpowers. Every SKILL.md with YAML
frontmatter becomes available. The model gets a compact index in *every* system
prompt and loads a full skill only when it needs one, so the context budget goes
to code rather than to instructions it will not use this turn.
"""

from __future__ import annotations

import os
import re

SKILLS_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills")

# On a 3B model the old preamble cost a whole round trip per task: it replied
# "Using writing-plans to plan the game of Snake." and burned 40-90 seconds
# before touching a tool. Skills are now opt-in and silent. The only rule kept
# mandatory is the one that matters: check before claiming.
RULES = """OPTIONAL SKILLS: an index follows. If one clearly matches the task, load it
with read_skill and follow it. Do not announce skills and do not narrate process;
skip them for a small single-file change. Always: never claim something works
without checking it, and report a failure as a failure."""


def _frontmatter(text: str):
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not match:
        return {}, text
    meta = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip("\"'")
    return meta, text[match.end():]


def discover(root: str = SKILLS_ROOT) -> list:
    found = []
    if not os.path.isdir(root):
        return found
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.lower() != "skill.md":
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as fh:
                    meta, body = _frontmatter(fh.read())
            except OSError:
                continue
            found.append({
                "name": meta.get("name") or os.path.basename(dirpath),
                "description": meta.get("description", ""),
                "path": path,
                "dir": dirpath,
                "body": body,
            })
    found.sort(key=lambda item: item["name"].lower())
    return found


def index_text(root: str = SKILLS_ROOT) -> str:
    skills = discover(root)
    if not skills:
        return ""
    lines = ["Skill index (load one with read_skill before a matching task):"]
    for skill in skills:
        lines.append("- %s: %s" % (skill["name"], skill["description"] or "(no description)"))
    return "\n".join(lines)


def preamble(root: str = SKILLS_ROOT) -> str:
    text = RULES
    index = index_text(root)
    if index:
        text += "\n\n" + index
    return text


def read_skill(name: str, resource: str | None = None, root: str = SKILLS_ROOT) -> str:
    for skill in discover(root):
        if skill["name"].lower() != str(name).strip().lower():
            continue
        if resource:
            base = os.path.normpath(skill["dir"])
            target = os.path.normpath(os.path.join(base, resource))
            if not (target == base or target.startswith(base + os.sep)):
                return "refused: %s escapes the skill folder" % resource
            if not os.path.isfile(target):
                return "not found: %s" % resource
            with open(target, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read()
        return skill["body"]
    return "no skill named %s (try the names in the skill index)" % name
