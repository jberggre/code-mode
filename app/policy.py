"""The rules the agent works under - this app's equivalent of Freebuff's contract.

Freebuff is safe partly because of its instructions and partly because the tools
themselves refuse things. Instructions alone are not enough with a 3B model: on
this machine it read `app/server.py` for reference, wrote a Snake loop over it,
and reported success. The loop is still running inside that file. So the rules
live here, in code, and `tools` asks this module before it touches anything.

Three layers, in the order they apply:

1. Boundary. Every path resolves inside the workspace, or it is refused. The
   agent's idea of a path never widens what it can reach.
2. Ownership. The app's own source (`app/`, `scripts/`, `tools/`, `tests/`) is
   readable but not writable unless the user's own message names that file. A
   game belongs in `snake.html`, not in `app/server.py`; a real request to fix
   `app/ui.py` says so, and is allowed.
3. Reversibility. Any overwrite snapshots the old bytes under `.codemode/undo/`
   first, and dangerous shell commands are refused with a reason the model can
   read, instead of being "probably fine".
"""

from __future__ import annotations

import os
import re
import time

# Folders that belong to the app rather than to whatever the agent was asked to
# build. Writing here without being asked by name is the failure this prevents.
OWNED_DIRS = ("app", "scripts", "tools", "tests", "docs")

# Never writable, even when named: version control and the undo store itself.
SEALED_DIRS = (".git", ".codemode")

MAX_WRITE_BYTES = 2_000_000


def _abs(workspace: str, path: str) -> str:
    return os.path.abspath(os.path.join(os.path.abspath(workspace), str(path or ".")))


def _inside(root: str, target: str) -> bool:
    root = os.path.abspath(root)
    return target == root or target.startswith(root + os.sep)


def relative(workspace: str, target: str) -> str:
    return os.path.relpath(target, os.path.abspath(workspace)).replace(os.sep, "/")


def names_target(request: str, workspace: str, target: str) -> bool:
    """Does the user's own message mention this file?

    Matched on the relative path and on the bare file name, so both "fix
    app/ui.py" and "the composer in ui.py is cut off" count. Anything vaguer -
    "make me a snake game" - does not.
    """
    text = str(request or "").replace("\\", "/").lower()
    if not text:
        return False
    rel = relative(workspace, target).lower()
    base = os.path.basename(target).lower()
    if rel and rel in text:
        return True
    # A bare name only counts with a word boundary: "ui.py" not "myui.py".
    return bool(re.search(r"(?<![\w./-])%s(?![\w-])" % re.escape(base), text))


def check_write(workspace: str, path: str, request: str = "") -> tuple:
    """(allowed, message). A refusal's message tells the model what to do instead."""
    root = os.path.abspath(workspace)
    target = _abs(workspace, path)
    if not _inside(root, target):
        return False, ("refused: %s is outside the workspace (%s). Everything you "
                       "create goes inside it." % (path, root))
    if target == root:
        return False, "refused: %s is the workspace folder, not a file." % path

    rel = relative(workspace, target)
    parts = rel.split("/")
    if parts and parts[0] in SEALED_DIRS:
        return False, ("refused: %s is inside %s/, which is sealed (version "
                       "control or the undo store)." % (rel, parts[0]))

    if parts and parts[0] in OWNED_DIRS and not names_target(request, workspace, target):
        return False, (
            "refused: %s belongs to CodeMode itself, and the user's request did not "
            "name it. Put what you are building in its own file at the workspace "
            "root instead (for example snake.html), with every asset inline. If the "
            "user did ask you to change this exact file, ask them to name it." % rel)

    if os.path.isfile(target) and os.path.getsize(target) > MAX_WRITE_BYTES:
        return False, ("refused: %s is %d MB; write a new file rather than "
                       "replacing one that big." % (rel, os.path.getsize(target) // 1_000_000))
    return True, ""


def snapshot(workspace: str, target: str):
    """Keep the previous bytes of a file about to be overwritten.

    Returns the workspace-relative copy path, or None when there was nothing to
    keep. This is the difference between "the agent broke the app" and "the
    agent broke the app and told you where the old file is".
    """
    if not os.path.isfile(target):
        return None
    try:
        with open(target, "rb") as fh:
            old = fh.read()
    except OSError:
        return None
    rel = relative(workspace, target)
    folder = os.path.join(os.path.abspath(workspace), ".codemode", "undo", rel)
    os.makedirs(os.path.dirname(folder), exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = "%s.%s.bak" % (folder, stamp)
    n = 1
    while os.path.exists(dest):
        dest = "%s.%s-%d.bak" % (folder, stamp, n)
        n += 1
    with open(dest, "wb") as fh:
        fh.write(old)
    return relative(workspace, dest)


# ---------------------------------------------------------------------------
# Shell commands. Not a sandbox, but the same rule Freebuff uses: a command that
# is destructive or hard to undo is refused, and the user is told to run it
# themselves. Ordered most specific first so the message names the real problem.
# ---------------------------------------------------------------------------

_PROTECTED_SERVICES = (
    "xbox", "gaming", "gamebar", "game bar", "xbl", "armoury", "asus", "amd",
    "razer", "msi", "store",
)

COMMAND_RULES = (
    (re.compile(r"\b(format|diskpart|bcdedit|clear-disk|initialize-disk)\b", re.I),
     "disk and boot configuration changes"),
    (re.compile(r"\b(shutdown|restart-computer|stop-computer|logoff)(\.exe)?\b", re.I),
     "shutting down or restarting the machine"),
    (re.compile(r"\bpowercfg\b.*(\s/setactive|\s/change|\s/restoredefaultschemes)\b", re.I),
     "changing the power plan (Armoury Crate owns TDP on this device)"),
    (re.compile(r"\bgit\b.*\b(reset\s+--hard|clean\s+-[a-z]*f|push\s+.*--force|rebase\s+--root)\b", re.I),
     "rewriting or discarding git history"),
    (re.compile(r"\bgit\s+worktree\b", re.I),
     "making a second checkout of this repository; this folder is the checkout"),
    (re.compile(r"\bRemove-AppxPackage\b|\bUninstall-Package\b", re.I),
     "uninstalling Windows apps"),
    (re.compile(r"\bSet-ExecutionPolicy\b", re.I),
     "changing the machine's execution policy"),
    (re.compile(r"\breg(\.exe)?\s+(delete|add)\b", re.I),
     "editing the registry"),
    (re.compile(r"\bRemove-Item\b[^|;]*-Recurse[^|;]*", re.I),
     "recursive deletion"),
    (re.compile(r"\b(rd|rmdir)\s+/s\b|\bdel\s+/[fsq]\b|\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", re.I),
     "recursive or forced deletion"),
    (re.compile(r"\btaskkill\b.*\b(/f|/im\s+python|/im\s+pythonw)", re.I),
     "killing processes"),
    (re.compile(r"\b(New-NetFirewallRule|Set-MpPreference|Add-MpPreference|netsh\s+advfirewall)\b", re.I),
     "changing firewall or antivirus settings"),
)


def check_command(command: str, workspace: str = "") -> str:
    """A refusal reason for this command, or "" when it is allowed."""
    text = str(command or "")
    if not text.strip():
        return "empty command"
    for pattern, reason in COMMAND_RULES:
        match = pattern.search(text)
        if not match:
            continue
        return ("refused: %r looks like %s. That is not mine to do - ask the user "
                "to run it themselves if it is really what they want."
                % (" ".join(match.group(0).split())[:80], reason))

    lowered = text.lower()
    if re.search(r"\b(stop-service|set-service|sc(\.exe)?\s+config)\b", lowered):
        for name in _PROTECTED_SERVICES:
            if name in lowered:
                return ("refused: that would stop or reconfigure a protected "
                        "service (%s). Xbox, Game Bar, the Store, Armoury Crate, "
                        "ASUS and AMD services stay untouched." % name)

    # A command that writes into another folder or a system location is out of
    # bounds for the same reason a path argument is.
    if workspace:
        root = os.path.abspath(workspace).lower()
        for match in re.finditer(r"[a-z]:\\\\?[^\s\"';|]*", lowered):
            path = match.group(0).rstrip("\\/")
            if not path.startswith(root):
                if re.search(r"\\(windows|program files|users|system32)\b", path) or ".." in path:
                    return ("refused: %r is outside the workspace. Work inside %s."
                            % (match.group(0), workspace))
    return ""
