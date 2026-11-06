#!/usr/bin/env python3
"""CodeMode - a local coding interface for the ROG Xbox Ally (RC73YA).

Standard library only: no pip install, no Node. Serves the UI and proxies chat
to whichever local runtime is running:

    Ollama      http://127.0.0.1:11434   (/api/chat)
    LM Studio   http://127.0.0.1:1234    (/v1/chat/completions)

Both are auto-detected, so you can install either one (or both).

Run:  python app/server.py
"""

from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)

# The portable build staged by tools/stage.sh: no service, no autostart.
OLLAMA_EXE = os.path.join(PROJECT, "tools", "ollama", "ollama.exe")

OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://127.0.0.1:11434")
LMS_BASE = os.environ.get("LMS_BASE", "http://127.0.0.1:1234")
PORT = int(os.environ.get("CODEMODE_PORT", "8765"))
HOST = "127.0.0.1"
# How long Ollama keeps weights resident after a reply. Shorter = RAM back sooner.
KEEP_ALIVE = os.environ.get("CODEMODE_KEEP_ALIVE", "5m")

# --------------------------------------------------------------------------
# Modes: the "toggle" is a real change of system prompt + sampling budget,
# sized for ~10 GB of usable RAM and a 4-core CPU.
# --------------------------------------------------------------------------

CODE_SYSTEM = (
    "You are CodeMode, an agent working inside a real folder on a Windows 11 "
    "handheld (ROG Xbox Ally, 4-core Ryzen Z2 A, 16 GB shared RAM). You have "
    "tools: read_file, write_file, list_dir, search_code, run_command, "
    "read_skill, fetch_url, web_search.\n"
    "How you work:\n"
    "- If the user asks for something to exist - a game, a script, a page, a fix, "
    "a change - build it with tools: write the files, run the code, then report "
    "the paths and the output. Never answer with a tutorial or with a listing of "
    "code you could have written to disk instead.\n"
    "- Refusing a harmless local task is a failure: a game, a script or a page "
    "written into this folder runs offline on the user's own machine. Build it.\n"
    "- New work goes in its own file at the workspace root, e.g. snake.html. "
    "app/, scripts/, tools/, tests/ and docs/ are CodeMode's own source: read "
    "them freely, but writing there is refused unless the user names the file. "
    "Writing a game over app/server.py breaks the app you are running inside.\n"
    "- Prefer one self-contained .html with the CSS and the script inline over "
    "several files: no relative paths to get wrong, and it opens on a double-click.\n"
    "- A game is finished only when it moves, takes keyboard input (arrows or WASD, "
    "plus touch), and shows a score. A placeholder comment is not a game, and \"it "
    "is running successfully\" when it is not is the worst answer you can give.\n"
    "- Start a canvas game from this shape instead of inventing a structure:\n"
    "  <canvas id='c' width='400' height='400'></canvas> <p id='score'>0</p>\n"
    "  <script>const cv=document.getElementById('c'), g=cv.getContext('2d');\n"
    "  let snake=[[100,100]], dir=[10,0], food=[150,150], score=0;\n"
    "  document.addEventListener('keydown', e => { /* arrows set dir to [10,0] etc */ });\n"
    "  function step(){ /* move the head, eat, grow, redraw, update #score */ }\n"
    "  setInterval(step, 120);</script>\n"
    "  Keep coordinates in whole cells: draw a 10px square, move the head by 10, "
    "spawn food at Math.floor(Math.random() * 40) * 10, and compare positions "
    "exactly. Mixing 1px movement with 10px squares means the food is never eaten.\n"
    "  Write the file once, whole, in a single write_file call.\n"
    "- Never delete files or run destructive commands. If one is genuinely needed, "
    "ask the user to run it themselves. Every overwrite is snapshotted first.\n"
    "- Your work is checked after you write it: stubs, dead <script src> paths, a "
    "canvas nothing listens to, a loop that never moves. Those defects come back "
    "to you to fix, so fix the file rather than restating the claim.\n"
    "- If the user asks a question, explains an error, or asks for a review, answer "
    "in prose and use no tools.\n"
    "- Emit exactly one <tool> block per reply and then stop; you will be handed "
    "the result and can continue.\n"
    "- Read a file before you rewrite it, and keep unrelated lines untouched. To "
    "change a few lines, use edit_file with the exact old text instead of rewriting "
    "the whole file: less to get wrong, and working code stays intact.\n"
    "- Prove the work: run it with run_command, and show it with something like "
    "Start-Process .\\snake.html.\n"
    "- No preamble, no restating the question. After acting, at most three lines: "
    "what changed, where it lives, and the output that proves it.\n"
    "- Python 3.11 and PowerShell 5.1 exist. Node.js is NOT installed.\n"
    "- When the user pastes an error, lead with the cause, then fix it."
)

CHAT_SYSTEM = (
    "You are CodeMode in Chat mode, a helpful offline assistant on a handheld PC "
    "with limited memory. Be concise and skimmable. Use plain prose unless asked "
    "for code, and keep replies short enough to read on a 7-inch screen."
)

MODES = {
    "chat": {
        "label": "Chat",
        "system": CHAT_SYSTEM,
        "temperature": 0.7,
        "top_p": 0.95,
        "repeat_penalty": 1.05,
        "num_ctx": 4096,
        "num_predict": 1024,
        "hint": "Everyday assistant. 4k context, higher temperature.",
    },
    "code": {
        "label": "Code",
        "system": CODE_SYSTEM,
        "temperature": 0.1,
        "top_p": 0.9,
        "repeat_penalty": 1.02,
        "num_ctx": 8192,
        "num_predict": 2048,
        "hint": "Coding mode. 8k context, near-greedy sampling, trimmed history.",
    },
}

# Model sizes are download sizes, not benchmarks.
RECOMMENDED = [
    {"name": "qwen2.5-coder:1.5b", "download": "~1.0 GB", "note": "fastest; good for one-file edits"},
    {"name": "qwen2.5-coder:3b", "download": "~1.9 GB", "note": "sweet spot for 16 GB shared RAM"},
    {"name": "qwen2.5-coder:7b", "download": "~4.7 GB", "note": "slower on 4 cores; needs UMA at 1-2 GB"},
]


# --------------------------------------------------------------------------
# Installing / updating: inventory plus on-demand updaters
# --------------------------------------------------------------------------

STEAM_EXE = r"C:\Program Files (x86)\Steam\steam.exe"
EPIC_MANIFESTS = r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests"
EPIC_EXE = r"C:\Program Files\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe"
BNET_EXE = r"C:\Program Files (x86)\Battle.net\Battle.net.exe"
XBOX_GAMES_DIR = r"C:\XboxGames"
STORE_UPDATES_URI = "ms-windows-store://downloadsandupdates"

WINGET_LOCK = threading.Lock()
WINGET = {"at": 0.0, "count": 0, "rows": [], "error": None}


def _vdf_pairs(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return {}
    return {
        key: value
        for key, value in re.findall(r'"([^"]+)"\s+"([^"]*)"', text)
    }


def steam_inventory() -> dict:
    if not os.path.exists(STEAM_EXE):
        return {"present": False, "games": []}
    root = os.path.dirname(STEAM_EXE)
    libs = [root]
    try:
        with open(os.path.join(root, "steamapps", "libraryfolders.vdf"),
                  "r", encoding="utf-8", errors="replace") as fh:
            for path in re.findall(r'"path"\s+"([^"]+)"', fh.read()):
                path = path.replace("\\\\", "\\")
                if os.path.isdir(path):
                    libs.append(path)
    except OSError:
        pass

    games = []
    for lib in dict.fromkeys(libs):
        steamapps = os.path.join(lib, "steamapps")
        if not os.path.isdir(steamapps):
            continue
        for name in os.listdir(steamapps):
            if not (name.startswith("appmanifest_") and name.endswith(".acf")):
                continue
            entry = _vdf_pairs(os.path.join(steamapps, name))
            if not entry:
                continue
            if entry.get("StateFlags") not in ("4", "6", None):
                continue  # not fully installed
            try:
                size_gb = round(int(entry.get("SizeOnDisk") or 0) / 1024 ** 3, 1)
            except ValueError:
                size_gb = 0.0
            try:
                seen = datetime.fromtimestamp(int(entry.get("LastUpdated") or 0)).strftime("%Y-%m-%d")
            except (ValueError, OSError, OverflowError):
                seen = ""
            games.append({"name": entry.get("name", name), "gb": size_gb, "updated": seen})
    games.sort(key=lambda g: g["name"].lower())
    return {"present": True, "games": games}


def epic_inventory() -> dict:
    present = os.path.exists(EPIC_EXE) or os.path.isdir(EPIC_MANIFESTS)
    games = []
    if os.path.isdir(EPIC_MANIFESTS):
        for name in os.listdir(EPIC_MANIFESTS):
            if not name.endswith(".item"):
                continue
            # Epic writes these cp1252, not utf-8: "Rocket League\xae" would
            # otherwise come back as a replacement character.
            try:
                with open(os.path.join(EPIC_MANIFESTS, name), "rb") as fh:
                    raw = fh.read()
            except OSError:
                continue
            text = None
            for encoding in ("utf-8-sig", "cp1252"):
                try:
                    text = raw.decode(encoding)
                    break
                except UnicodeDecodeError:
                    continue
            if text is None:
                text = raw.decode("utf-8", "replace")
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                continue
            label = data.get("DisplayName") or os.path.basename(
                os.path.dirname(str(data.get("ManifestLocation", "")))) or name
            games.append({"name": label, "version": data.get("CompleteVersion") or ""})
    games.sort(key=lambda g: g["name"].lower())
    return {"present": present, "games": games}


def xbox_inventory() -> dict:
    if not os.path.isdir(XBOX_GAMES_DIR):
        return {"present": False, "games": []}
    games = [
        d for d in sorted(os.listdir(XBOX_GAMES_DIR))
        if os.path.isdir(os.path.join(XBOX_GAMES_DIR, d)) and d.lower() != "gamesave"
    ]
    return {"present": True, "games": games}


def winget_scan(timeout: int = 240) -> dict:
    """Really ask winget what it can upgrade. Result is cached until next scan."""
    global WINGET
    with WINGET_LOCK:
        cmd = ["winget", "upgrade", "--include-unknown",
               "--accept-source-agreements", "--disable-interactivity"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                  encoding="utf-8", errors="replace")
        except FileNotFoundError:
            WINGET = {"at": time.time(), "count": 0, "rows": [], "error": "winget not on PATH"}
            return dict(WINGET)
        except subprocess.TimeoutExpired:
            WINGET = {"at": time.time(), "count": 0, "rows": [], "error": "winget scan timed out"}
            return dict(WINGET)

        text = (proc.stdout or "") + (proc.stderr or "")
        rows = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("Name ") and "Id" in stripped:
                continue
            if set(stripped) <= {"-"}:
                continue
            if re.search(r"^\d+\s+upgrades?\s+available", stripped, re.I):
                continue
            rows.append(line.rstrip())

        match = re.search(r"(\d+)\s+upgrades?\s+available", text, re.I)
        WINGET = {
            "at": time.time(),
            "count": int(match.group(1)) if match else 0,
            "rows": rows[:60],
            "error": None if proc.returncode in (0, 1) else "winget exit %d" % proc.returncode,
        }
        return dict(WINGET)


def updates_snapshot() -> dict:
    return {
        "winget": dict(WINGET),
        "steam": steam_inventory(),
        "epic": epic_inventory(),
        "xbox": xbox_inventory(),
        "battlenet": {"present": os.path.exists(BNET_EXE)},
        "store": {"present": True},
    }


# --------------------------------------------------------------------------
# Host memory
# --------------------------------------------------------------------------

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def gpu_split_gb():
    """How much of the shared LPDDR5X the firmware hands to the GPU at boot."""
    try:
        import winreg
        path = ("SYSTEM\\CurrentControlSet\\Control\\Class\\"
                "{4d36e968-e325-11ce-bfc1-08002be10318}\\0000")
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            value, _kind = winreg.QueryValueEx(key, "HardwareInformation.qwMemorySize")
        return round(value / 1024 ** 3, 1)
    except Exception:
        return None


def memory() -> dict:
    try:
        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return {
            "total_gb": round(m.ullTotalPhys / 1024 ** 3, 1),
            "avail_gb": round(m.ullAvailPhys / 1024 ** 3, 1),
            "load_pct": int(m.dwMemoryLoad),
        }
    except Exception:
        return {}


# --------------------------------------------------------------------------
# Backend detection
# --------------------------------------------------------------------------

def _get_json(url: str, timeout: float = 1.5):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def list_backends() -> list:
    backends = []
    try:
        tags = _get_json(OLLAMA_BASE + "/api/tags")
        models = [m.get("name") for m in tags.get("models", []) if m.get("name")]
        backends.append({
            "kind": "ollama",
            "label": "Ollama",
            "base": OLLAMA_BASE,
            "models": sorted(models),
        })
    except Exception:
        pass
    try:
        data = _get_json(LMS_BASE + "/v1/models")
        models = [m.get("id") for m in data.get("data", []) if m.get("id")]
        backends.append({
            "kind": "lmstudio",
            "label": "LM Studio",
            "base": LMS_BASE,
            "models": sorted(models),
        })
    except Exception:
        pass
    return backends


def build_status() -> dict:
    backends = list_backends()
    return {
        "backends": backends,
        "memory": memory(),
        "recommended": RECOMMENDED,
        "python": sys.version.split()[0],
        "scripts": {
            "debloat": os.path.join(PROJECT, "scripts", "debloat.ps1"),
            "codemode": os.path.join(PROJECT, "scripts", "code-mode.ps1"),
        },
    }


def pick_backend(backends: list, preferred: str | None) -> dict | None:
    if not backends:
        return None
    if preferred:
        for b in backends:
            if b["kind"] == preferred and b["models"]:
                return b
    for b in backends:
        if b["models"]:
            return b
    return backends[0]


def pick_model(backends: list, preferred: str = "") -> tuple:
    """(backend, model): exact preference, then the first coder model, then first.

    The desktop window has no other way to choose a model, so this has to work
    with zero models, one runtime and two runtimes alike.
    """
    pairs = [(b, name) for b in (backends or []) for name in (b.get("models") or [])]
    if not pairs:
        return None, ""
    if preferred:
        for backend, name in pairs:
            if name == preferred:
                return backend, name
    for backend, name in pairs:
        if re.search(r"coder", name, re.I):
            return backend, name
    return pairs[0]


# --------------------------------------------------------------------------
# Context trimming: the machine has ~10 GB usable RAM, so history must fit.
# --------------------------------------------------------------------------

def est_tokens(text: str) -> int:
    # ~3.6 chars per token for English + code. Deliberately conservative.
    return max(1, int(len(text) / 3.6))


def trim_messages(messages: list, cfg: dict) -> list:
    budget = max(512, cfg["num_ctx"] - cfg["num_predict"] - 200)
    used = est_tokens(cfg["system"])
    kept = []
    for msg in reversed(messages):
        cost = est_tokens(str(msg.get("content", ""))) + 4
        if kept and used + cost > budget:
            break
        used += cost
        kept.append(msg)
    kept.reverse()
    return kept


# --------------------------------------------------------------------------
# Streaming adapters -> yields text deltas
# --------------------------------------------------------------------------

def stream_ollama(base: str, model: str, messages: list, cfg: dict):
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": cfg["system"]}] + messages,
        "stream": True,
        "keep_alive": KEEP_ALIVE,
        "options": {
            "num_ctx": cfg["num_ctx"],
            "num_predict": cfg["num_predict"],
            "temperature": cfg["temperature"],
            "top_p": cfg["top_p"],
            "repeat_penalty": cfg["repeat_penalty"],
        },
    }
    req = urllib.request.Request(
        base + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("error"):
                raise RuntimeError(str(obj["error"]))
            content = obj.get("message", {}).get("content") or ""
            if content:
                yield content
            if obj.get("done"):
                break


def stream_openai(base: str, model: str, messages: list, cfg: dict, api_key: str | None = None):
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": cfg["system"]}] + messages,
        "stream": True,
        "temperature": cfg["temperature"],
        "top_p": cfg["top_p"],
        "max_tokens": cfg["num_predict"],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    req = urllib.request.Request(
        base + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=900) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            if obj.get("error"):
                raise RuntimeError(str(obj["error"]))
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                yield content


def unload_model(backend: dict, model: str) -> str:
    """Drop the model from RAM now instead of waiting out keep-alive."""
    if not backend or backend.get("kind") != "ollama":
        return "only Ollama can be unloaded on demand"
    payload = {"model": model, "keep_alive": 0}
    req = urllib.request.Request(
        backend["base"] + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response.read()
        return "unloaded %s" % model
    except Exception as exc:  # noqa: BLE001 - reported to the caller
        return "unload failed: %s" % exc


def start_ollama(timeout: int = 25) -> str:
    """Start the portable Ollama that is already staged, if it is staged.

    The desktop app must distinguish "installed but stopped" from "not
    installed": two models are pulled on this machine and the server is simply
    not running, so a message telling the user to install one would be a lie.
    """
    if not os.path.exists(OLLAMA_EXE):
        return "portable Ollama is not staged (expected %s)" % OLLAMA_EXE
    try:
        subprocess.Popen(
            [OLLAMA_EXE, "serve"], cwd=PROJECT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        return "could not start Ollama: %s" % exc
    for _ in range(max(1, int(timeout * 2))):
        try:
            _get_json(OLLAMA_BASE + "/api/tags", timeout=0.5)
            return "Ollama is up at %s" % OLLAMA_BASE
        except Exception:  # noqa: BLE001 - keep polling until the timeout
            time.sleep(0.5)
    return "started Ollama, but it did not answer within %ds" % timeout


def winget_apply(timeout: int = 1800) -> dict:
    """Really upgrade everything winget manages, then refresh the cached scan."""
    cmd = ["winget", "upgrade", "--all", "--include-unknown", "--silent",
           "--accept-package-agreements", "--accept-source-agreements",
           "--disable-interactivity"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"ok": False, "output": "winget upgrade timed out"}
    except FileNotFoundError:
        return {"ok": False, "output": "winget not on PATH"}
    winget_scan(120)
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "output": output[-6000:]}


def stream_backend(backend: dict, model: str, messages: list, cfg: dict):
    if backend["kind"] == "ollama":
        return stream_ollama(backend["base"], model, messages, cfg)
    return stream_openai(backend["base"], model, messages, cfg, os.environ.get("LMS_API_KEY"))


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "CodeMode/0.1"

    def log_message(self, fmt, *args):
        if os.environ.get("CODEMODE_VERBOSE"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # -- helpers ---------------------------------------------------------
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8", "replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    # -- routes ----------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._index()
        if path == "/api/config":
            return self._json({"modes": MODES, "port": PORT, "host": HOST})
        if path == "/api/status":
            return self._json(build_status())
        if path == "/api/updates":
            return self._json(updates_snapshot())
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/chat":
            return self._chat()
        if path == "/api/system/trim":
            return self._trim()
        if path == "/api/updates/scan":
            return self._json(winget_scan())
        if path == "/api/updates/apply":
            return self._updates_apply()
        if path == "/api/updates/open":
            return self._updates_open()
        return self._json({"error": "not found"}, 404)

    def _index(self):
        try:
            with open(os.path.join(HERE, "index.html"), "rb") as fh:
                body = fh.read()
        except OSError as exc:
            return self._json({"error": str(exc)}, 500)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _trim(self):
        body = self._read_body()
        action = body.get("mode", "code")
        if action not in ("code", "gaming", "status"):
            return self._json({"error": "mode must be code, gaming or status"}, 400)
        script = os.path.join(PROJECT, "scripts", "code-mode.ps1")
        if not os.path.exists(script):
            return self._json({"error": "scripts/code-mode.ps1 is missing"}, 500)
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script, "-Mode", action],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return self._json({"error": "code-mode.ps1 timed out"}, 504)
        output = (proc.stdout or "") + (proc.stderr or "")
        return self._json({
            "mode": action,
            "exit_code": proc.returncode,
            "output": output.strip()[-4000:],
            "memory": memory(),
        })

    def _updates_apply(self):
        body = self._read_body()
        if body.get("target") != "winget":
            return self._json({"error": "only target=winget is supported"}, 400)
        return self._json(winget_apply())

    def _updates_open(self):
        body = self._read_body()
        target = body.get("target")
        try:
            if target == "store":
                os.startfile(STORE_UPDATES_URI)  # deep link, Windows only
            elif target == "steam" and os.path.exists(STEAM_EXE):
                subprocess.Popen([STEAM_EXE], close_fds=True)
            elif target == "epic" and os.path.exists(EPIC_EXE):
                subprocess.Popen([EPIC_EXE], close_fds=True)
            elif target == "battlenet" and os.path.exists(BNET_EXE):
                subprocess.Popen([BNET_EXE], close_fds=True)
            else:
                return self._json({"error": "launcher missing or unknown target: %s" % target}, 404)
        except OSError as exc:
            return self._json({"error": str(exc)}, 500)
        return self._json({"opened": target})

    def _chat(self):
        body = self._read_body()
        mode = body.get("mode", "chat")
        cfg = MODES.get(mode, MODES["chat"])
        messages = [m for m in body.get("messages", []) if isinstance(m, dict)]

        backends = list_backends()
        backend = pick_backend(backends, body.get("backend"))
        if not backend:
            return self._json({
                "error": "no local model runtime is running",
                "detail": "Start Ollama (ollama serve) or LM Studio's local server, then retry.",
                "recommended": RECOMMENDED,
            }, 409)

        model = body.get("model") or (backend["models"][0] if backend["models"] else "")
        if not model:
            return self._json({
                "error": "no model installed",
                "detail": "Pull a model first, e.g. ollama pull qwen2.5-coder:3b",
                "recommended": RECOMMENDED,
            }, 409)

        messages = trim_messages(messages, cfg)

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        started = time.time()
        chars = 0
        try:
            self._event({"start": True, "model": model, "backend": backend["kind"], "mode": mode})
            for delta in stream_backend(backend, model, messages, cfg):
                chars += len(delta)
                self._event({"delta": delta})
            elapsed = max(0.001, time.time() - started)
            self._event({
                "done": True,
                "chars": chars,
                "seconds": round(elapsed, 2),
                "tps_est": round((chars / 3.6) / elapsed, 1),
            })
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except urllib.error.URLError as exc:
            self._safe_event({"error": "cannot reach %s: %s" % (backend["label"], exc.reason)})
        except RuntimeError as exc:
            self._safe_event({"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - surface anything else to the UI
            self._safe_event({"error": "%s: %s" % (type(exc).__name__, exc)})

    def _event(self, obj: dict):
        self.wfile.write(b"data: " + json.dumps(obj).encode("utf-8") + b"\n\n")
        self.wfile.flush()

    def _safe_event(self, obj: dict):
        try:
            self._event(obj)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = "http://%s:%d/" % (HOST, PORT)
    print("CodeMode  ->  %s" % url)
    status = build_status()
    names = ", ".join("%s (%d models)" % (b["label"], len(b["models"])) for b in status["backends"])
    print("runtime   ->  %s" % (names or "none running yet"))
    mem = status["memory"]
    if mem:
        print("memory    ->  %.1f GB free of %.1f GB" % (mem["avail_gb"], mem["total_gb"]))
    print("stop      ->  Ctrl+C")
    if WINGET["at"] == 0 and shutil.which("winget"):
        print("scanning winget for pending updates in the background...")
        threading.Thread(target=winget_scan, kwargs={"timeout": 180}, daemon=True).start()
    if not os.environ.get("CODEMODE_NO_BROWSER"):
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
