# CodeMode Desktop Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the documented CodeMode desktop app actually work again — selectable model, persistent chat, a layout that does not freeze, and every documented button wired to its real action.

**Architecture:** Repair `app/ui.py` incrementally. The backend (`app/server.py`, `app/agent.py`, `app/tools.py`, `app/memory.py`) is intact; the Tk front end was half-rewritten into a "Freebuff-style" three-pane layout on 2026-11-03 19:52 and left in a state where it cannot send a message and stops draining its event queue after the first reply. Two small, testable helpers (`pick_model` in `server.py`, session load/save in `ui.py`) are added so the failure modes are covered by headless tests instead of by clicking.

**Tech Stack:** Python 3.11 stdlib only (tkinter 8.6, urllib, json, threading, unittest). No pip, no Node, no new dependency.

**Spec:** `README.md` and `PLAN.md` (the feature contract written at the end of the last session; sections 1–9 of README) plus the safety constraints in `scripts/`.

## Global Constraints

- Python 3.11 standard library only; do not add packages or a `requirements.txt`.
- The desktop window is the default surface (`start-codemode.cmd` → `pythonw app\ui.py`). The browser UI (`app/server.py` + `app/index.html`) stays as the fallback and keeps using the same `MODES` table.
- Chat state lives in `%LOCALAPPDATA%\CodeMode\chat-session.json`; Code Mode session state stays in `code-mode-session.json`. The two must never be written by the same function.
- `CODEMODE_STATE` must redirect `app/memory.py` (archive + handoff) away from the real `state/` folder for tests and demos.
- Never change `scripts/code-mode.ps1`, `scripts/gpu-mode.ps1`, `scripts/debloat.ps1` protection lists or touch Xbox/Game Bar/Armoury Crate/ASUS/AMD services or the power plan.
- The Tk main loop must never block: every long operation runs in a thread and reports through `self.q`, and every queue-drain callback reschedules even when it raises.
- Streaming stays abortable (`stop()`), and `run_command` stays gated by the shell toggle and workspace boundary in `app/tools.py`.
- **This folder is not a git repository** (`git log` → `fatal: not a git repository`). Every commit step below is conditional on Task 0; skip it if the owner declines a repo.
- Test runner: each test file starts with `sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))` so `import ui` / `import server` / `import memory` resolve; run with `python -m unittest discover -s tests -v` from the project root.

## Review Focus

- An exception inside a Tk `after()` callback silently stops that callback chain forever — the app must keep draining after any single bad message.
- Widget ownership on a 7-inch handheld: the composer must sit under the transcript and stay reachable at 1000×720, the sidebar must collapse without leaving a dead strip, and the free-RAM readout must be visible, not printed to a `pythonw` stdout nobody sees.
- A legacy or corrupt `chat-session.json` already exists on this machine (`{"mode": "code", "messages": []}`); boot must tolerate it and any future truncation without a traceback.
- "Ollama is not running" and "no model is installed" are different states on this machine (two models are pulled, the portable server is simply stopped); the UI must not tell the user to install a model it already has.
- Compaction mid-run replaces `self.messages` while a reply is streaming; the visible transcript and the saved session must not diverge or double-save the answer.

---

### Task 0: Optional safety net before touching anything

**Files:** none (repository metadata only)

- [ ] **Step 1: Decide whether to initialise git**

There is no version control here, which is why the half-finished rewrite could not be rolled back. If the owner wants the per-task commits, run:

```bash
printf 'state/\ntools/ollama/\ntools/ollama.zip\n__pycache__/\n*%%DESKTOP%%/\n*%%USERPROFILE%%/\n' > .gitignore
git init && git add -A && git commit -m "chore: snapshot before CodeMode recovery"
```

- [ ] **Step 2: If declined, mark every commit step below as skipped in the final report.**

---

### Task 1: Model selection (the app cannot send at all today)

**Files:**
- Modify: `app/ui.py` (`_build` header, `refresh_backends`, `_select`, `send` empty state)
- Modify: `app/server.py` (new `pick_model`, optional `start_ollama`)
- Test: `tests/test_ui_state.py`

**Interfaces:**
- Produces: `server.pick_model(backends: list, preferred: str = "") -> tuple[dict | None, str]` — returns `(backend, model_name)`; prefers an exact `preferred`, then the first name matching `coder`, then the first model; `(None, "")` when no backend has models.
- Produces: `server.start_ollama() -> str` — starts `tools/ollama/ollama.exe serve` detached without a console window, polls `/api/tags` for up to 20 s, returns a human-readable status line.
- Consumes: `server.list_backends()` (unchanged).

- [ ] **Step 1: Write the failing test**

```python
def test_pick_model_prefers_requested_then_coder():
    b1 = {"kind": "ollama", "label": "Ollama", "models": ["llama3:8b", "qwen2.5-coder:3b"]}
    b2 = {"kind": "lmstudio", "label": "LM Studio", "models": ["deepseek-coder:6.7b"]}
    assert pick_model([b1, b2], "llama3:8b") == (b1, "llama3:8b")
    assert pick_model([b1, b2], "") == (b1, "qwen2.5-coder:3b")
    assert pick_model([{"models": []}], "x") == (None, "")
```

- [ ] **Step 2: Run it to see it fail**

Run: `python -m unittest discover -s tests -v`
Expected: FAIL — `pick_model` does not exist.

- [ ] **Step 3: Implement `pick_model` in `app/server.py` next to `pick_backend`**

- [ ] **Step 4: Add the picker to the header**

`_build` adds `self.model_var = tk.StringVar(value="detecting…")` and `self.model_menu = tk.OptionMenu(top, self.model_var, "detecting…", command=self._select)` styled with `PANEL2`/`TEXT`, placed right of the mode buttons. `refresh_backends()` calls a new `_populate_models()` that rebuilds the menu items from `self.backends`, then auto-selects with `pick_model(self.backends, self.model or os.environ.get("CODEMODE_MODEL", ""))`. `_select(name)` must look up the backend by membership (existing body is correct) and call `self._save_session()` (Task 2).

- [ ] **Step 5: Make the empty state honest**

In `send()`, replace the single "No local model yet" block with two branches:
- no backends at all and `tools\ollama\ollama.exe` exists → "Ollama is installed but not running" plus a `Start Ollama` button that runs `core.start_ollama()` in a thread and then `refresh_backends()`;
- a backend with zero models → the existing `ollama pull qwen2.5-coder:3b` guidance.

- [ ] **Step 6: Re-run tests, then check selection against the real machine**

Run: `python -m unittest discover -s tests -v` → PASS.
With `tools\ollama\ollama.exe serve` running, run `python app/ui.py --selftest` and confirm `"model"` is non-empty in the JSON.

- [ ] **Step 7: Commit**

```bash
git add app/ui.py app/server.py tests/test_ui_state.py
git commit -m "feat: select a model in the desktop app instead of refusing to send"
```

---

### Task 2: Session persistence (already called, never implemented)

**Files:**
- Modify: `app/ui.py` (module-level `load_session`/`save_session`, `_load_session`, `_render_history`, `_save_session`)
- Test: `tests/test_ui_state.py`

**Interfaces:**
- Produces: `ui.load_session(path: str = SESSION_FILE) -> dict` → always `{"mode", "model", "messages"}`; ignores corrupt JSON, non-list `messages`, and entries whose role/content are not strings; caps at 200 messages.
- Produces: `ui.save_session(data: dict, path: str = SESSION_FILE) -> bool` → atomic (`tmp` + `os.replace`), creates `%LOCALAPPDATA%\CodeMode`, never raises.
- Consumes: `core.MODES` for validating `mode`.

- [ ] **Step 1: Write the failing test**

```python
def test_session_round_trip_and_corrupt_file(tmp_path):
    p = str(tmp_path / "chat-session.json")
    assert load_session(p) == {"mode": "code", "model": "", "messages": []}
    save_session({"mode": "chat", "model": "m", "messages": [{"role": "user", "content": "hi"}]}, p)
    assert load_session(p)["messages"] == [{"role": "user", "content": "hi"}]
    open(p, "w").write("{not json")
    assert load_session(p)["messages"] == []
```

- [ ] **Step 2: Run it → FAIL** (`ImportError: cannot import name 'load_session'`)

- [ ] **Step 3: Implement both functions and the three methods**

`__init__`: after `_build()`, call `self._load_session()`, then `self._populate_models()` (Task 1), then `self._render_history()`, then `self._resume_handoff()`. `_load_session` sets `self.state_mode`, `self.messages`, and a `self.model_pref` string. `_render_history` writes each message with the `user`/`assistant` tags and calls `_highlight_code` per assistant block. `_save_session` writes `{"mode": self.state_mode, "model": self.model, "messages": self.messages}` and is called from `_finish` (replacing the current undefined call), `new_chat`, `_apply_mode`, `_select`, and the `"compact"` drain branch.

- [ ] **Step 4: Re-run tests → PASS**, then `python app/ui.py --selftest` and confirm `restored_messages` reflects the file.

- [ ] **Step 5: Commit**

```bash
git add app/ui.py tests/test_ui_state.py
git commit -m "fix: persist and restore the desktop chat session"
```

---

### Task 3: Layout and event-loop repair

**Files:**
- Modify: `app/ui.py` (`__init__`, `_build`, `_rebalance_layout` removed, `_toggle_sidebar`, `_update_ram`, `_drain`, `selftest`)

**Interfaces:**
- Produces: attributes `self.body`, `self.main`, `self.sidebar`, `self.ram_lbl`, `self.stat_lbl`, `self.terminal`, `self.sidebar_visible: bool`, `self.terminal_visible: bool`.
- Removes: `self.main_pane`, `_rebalance_layout`, `_is_sidebar`/`_is_main_area`/`_is_ram_lbl` tag lookups.

- [ ] **Step 1: Add the layout assertions to `--selftest` first**

Extend the selftest report with `input_below_transcript` (`self.input.winfo_rooty() > self.txt.winfo_rooty()`), `sidebar_mapped` (`bool(self.sidebar.winfo_ismapped())`), `ram_visible` (`bool(self.ram_lbl.winfo_ismapped())`). Run it: all three are `False` today.

- [ ] **Step 2: Rebuild the root layout**

Root packs `top` with `side="top", fill="x"`; then `self.body = tk.Frame(self, bg=BG)` packed `side="top", fill="both", expand=True`; inside `body`, `self.sidebar.pack(side="left", fill="y")` **before** `self.main.pack(side="left", fill="both", expand=True)`; inside `main`, the transcript frame packs `fill="both", expand=True` and the input frame packs `side="bottom", fill="x"`. Delete the PanedWindow and every `pack_configure(width=…)` call — they operate on frames that ignore `width` because `pack_propagate` is on.

- [ ] **Step 3: One visible readout per fact**

Create `self.ram_lbl` in the header (`app 37 MB · free 6.9 of 13.7 GB`) and `self.stat_lbl` in the footer (`N chars · N s · ~N tok/s`). `_update_ram` writes only `self.ram_lbl`; the `"stat"` drain branch writes only `self.stat_lbl`. Remove the `print("RAM:", text)` fallback.

- [ ] **Step 4: Make `_drain` unkillable**

```python
def _drain(self) -> None:
    try:
        while True:
            ...existing event handling...
    except queue.Empty:
        pass
    except Exception as exc:
        self._write("\ninternal: %s: %s\n" % (type(exc).__name__, exc), "err")
    finally:
        self.after(50, self._drain)
```

- [ ] **Step 5: Verify**

Run `python app/ui.py --selftest` → `input_below_transcript`, `sidebar_mapped`, `ram_visible` all `true`. Resize to 1000×720 manually or via `self.geometry` in the selftest and confirm no `TclError` in stderr.

- [ ] **Step 6: Commit**

```bash
git add app/ui.py
git commit -m "fix: keep the desktop layout usable and the event loop alive"
```

---

### Task 4: Wire the documented controls, delete the decorative ones

**Files:**
- Modify: `app/ui.py` (`__init__`, `_build` sidebar, `_detect_session`, `toggle_session`, `toggle_terminal`)

**Interfaces:**
- Produces: `self.session_on: bool` initialised from `os.path.exists(CODE_MODE_STATE)` before any use; `self.session_btn`; `toggle_terminal()` (visibility only).
- Consumes: existing `trim_system`, `unload`, `open_updates`, `open_profile`, `compact_now`, `show_handoff`, `toggle_agent`, `toggle_shell`, `toggle_session`, `dictate`.

- [ ] **Step 1: Prove the gap statically**

Run: `grep -n "session_btn\|session_on\|_detect_session" app/ui.py`
Expected today: one assignment inside `_detect_session` (`self.session_on = …`), one use in `toggle_session` (`self.session_btn.configure`), and calls to `_detect_session` — but **no** `self.session_btn = tk.Button(...)` and no `_detect_session()` call in `__init__`. So `toggle_session(None)` raises `AttributeError: session_btn`, and `session_on` is undefined at boot.

- [ ] **Step 2: Initialise state and create the button**

In `__init__`, set `self.session_on = os.path.exists(CODE_MODE_STATE)` before `_apply_mode`. In `_build`, create `self.session_btn` as the sidebar's first action (`"Code Mode session"`), `command=lambda: self.toggle_session(None)`, and make `_detect_session()` update its text (`"☰ Code Mode (suspended)"` / `"☰ Code Mode"`) and colour.

- [ ] **Step 3: Replace the sidebar contents with the real action list**

Keep exactly these buttons, each with its command: Code Mode session, Trim system, Unload model, Updates, GPU profile + restart, Compact + write handoff, Show handoff, Toggle agent tools, Toggle shell access, Terminal. Delete the four skill buttons and the "Featured / AI templates, starter kits & integrations" filler — they have no command and duplicate what the model does via `read_skill`. Sidebar header shows the workspace path and the selected model.

- [ ] **Step 4: Verify every button resolves**

Add a selftest check `dead_buttons`: iterate the sidebar's `tk.Button` children and fail if `str(btn["command"]) in ("", "None")`. Run `--selftest`; expect `dead_buttons: 0`.

- [ ] **Step 5: Commit**

```bash
git add app/ui.py
git commit -m "fix: wire the sidebar controls and remove decorative dead buttons"
```

---

### Task 5: Honest terminal panel

**Files:**
- Modify: `app/ui.py` (`_build` terminal, `_drain` new `"term"` event, `toggle_terminal`)

**Interfaces:**
- Produces: `self.term_out` (read-only `tk.Text`), `self.cmd_var`/`self.cmd_entry`, `run_terminal_command()`.
- Consumes: `tools.run_command(workspace, command, timeout=60)` and `self.shell_on`.

- [ ] **Step 1: Delete the fake**

The current "Run" button re-inserts the whole `term_txt` buffer into itself — it never executes anything. Replace `term_txt` with a read-only output widget (`state="disabled"`), a single-line `Entry`, and Run.

- [ ] **Step 2: Implement the real command**

`run_terminal_command()` refuses with a visible line when `self.shell_on` is false; otherwise it clears the entry, writes `> cmd`, runs `tools.run_command` in a daemon thread, and puts `("term", "exit N\n…output…", None)` on the queue. The drain branch appends it read-only and scrolls.

- [ ] **Step 3: Collapse by default**

The panel is packed `side="bottom", fill="x"` inside `self.main` and hidden at boot; the Terminal button toggles it (and re-packs after the composer so the composer stays above it). Selftest gains `terminal_hidden: true`.

- [ ] **Step 4: Verify**

In the running app, with shell on, run `python --version` and confirm the panel shows `exit 0` and the version; with shell off, confirm the refusal line. Then `--selftest`.

- [ ] **Step 5: Commit**

```bash
git add app/ui.py
git commit -m "fix: make the terminal panel run commands instead of echoing itself"
```

---

### Task 6: Stop tests from poisoning real state, and resume at boot

**Files:**
- Modify: `app/memory.py` (`STATE` from `CODEMODE_STATE`)
- Modify: `app/ui.py` (boot calls `_resume_handoff`)
- Delete: `state/handoff.md` (contains `Test handoff content - …` from `test_overflow.py`)
- Create: `tests/test_memory.py` (replaces the deleted `test_overflow.py`)
- Delete: `test_overflow.py`, `demo_overflow.py`, `demo_overflow2.py`

**Interfaces:**
- Produces: `memory.STATE = os.environ.get("CODEMODE_STATE") or os.path.join(PROJECT, "state")`, with `TRANSCRIPTS`/`HANDOFF` derived from it.

- [ ] **Step 1: Write the failing test**

```python
def test_state_dir_is_redirectable(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEMODE_STATE", str(tmp_path))
    import importlib, memory
    importlib.reload(memory)
    path = memory.write_handoff("a real note " * 5)
    assert path.startswith(str(tmp_path))
    assert memory.read_handoff().rstrip().endswith("a real note")
    assert os.path.isdir(os.path.join(str(tmp_path), "transcripts"))
```

- [ ] **Step 2: Run → FAIL** (the module-level paths ignore the environment)

- [ ] **Step 3: Implement the redirect, delete the junk handoff, and call `_resume_handoff()` at boot**

The handoff file currently injected into every system prompt says the unfinished work is a test sentence; removing it is part of the fix, not cleanup. `_resume_handoff()` writes the banner as today.

- [ ] **Step 4: Verify**

`python -m unittest discover -s tests -v` → PASS. Then `ls state/` shows `transcripts/` only, and `python app/ui.py --selftest` boots without a handoff banner.

- [ ] **Step 5: Commit**

```bash
git add app/memory.py app/ui.py tests/test_memory.py state/
git commit -m "fix: keep test writes out of real state and drop the test handoff"
```

---

### Task 7: Workspace hygiene and one working shortcut script

**Files:**
- Delete: `create_shortcut.py`, `create_desktop_shortcut.ps1`, `update_shortcut.ps1`, `make_shortcut.py`, `test_cli.py`
- Create: `scripts/make-shortcut.ps1`
- Modify: `app/ui.py` (`--no-shell`)

**Interfaces:**
- Produces: `scripts/make-shortcut.ps1 [-NoShell]` creating `CodeMode.lnk` on the Desktop pointing at the **current** interpreter's `pythonw.exe` with argument `app\ui.py` (plus `--no-shell` for the second shortcut).
- Produces: `ui.py --no-shell` sets `self.shell_on = False` at startup.

- [ ] **Step 1: Delete the broken one-offs**

`create_shortcut.py` cannot run (`NameError: at_echo_off`, `cd_d`, `pythonw` are undefined); `update_shortcut.ps1` creates the first shortcut and then overwrites it with `--no-shell`, which `ui.py` does not parse; `test_cli.py` exercises `app/ui.py --cli` and `~/CodeMode`, neither of which exists. Nothing imports them.

- [ ] **Step 2: Write `scripts/make-shortcut.ps1`**

Resolve `pythonw.exe` from `(python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))")`; `$ErrorActionPreference='Stop'`; refuse with a clear message if it is missing; set `WorkingDirectory` to the project root (the script's parent's parent), not a hard-coded `C:\Program Files\Python311`.

- [ ] **Step 3: Add `--no-shell` to `ui.py`** and verify both shortcuts launch; the shell-off one reports `shell access off` in the transcript.

- [ ] **Step 4: Remove the stray directories**

`%DESKTOP%` and `%USERPROFILE%` in the project root were created literally by an unexpanded variable; both are empty. `rm -rf '%DESKTOP%' '%USERPROFILE%'` (quoted, they are literal names).

- [ ] **Step 5: Commit**

```bash
git add -A scripts app/ui.py
git commit -m "chore: replace broken shortcut scripts and drop stale test artifacts"
```

---

### Task 8: `--smoke` end-to-end check (proof it can answer)

**Files:**
- Modify: `app/ui.py` (`main` argument handling, `smoke()`)

**Interfaces:**
- Produces: `ui.smoke() -> int` — prints JSON `{"backend", "model", "chars", "seconds"}` and returns 0 only when the reply is non-empty; no Tk window.

- [ ] **Step 1: Add the mode**

`smoke()` calls `core.list_backends()`, `core.pick_model(...)`, then streams `[{"role": "user", "content": "Reply with exactly: ok"}]` through `core.stream_backend(backend, model, msgs, core.MODES["code"])` with a 300-character cap, and returns 0/1.

- [ ] **Step 2: Run it against the real runtime**

```bash
tools/ollama/ollama.exe serve &   # if not already running
python app/ui.py --smoke
```

Expected: non-empty `chars`, exit 0. A 3B model on this CPU should answer within tens of seconds; if it times out, report that as a limitation rather than claiming success.

- [ ] **Step 3: Commit**

```bash
git add app/ui.py
git commit -m "test: add a scriptable end-to-end check for model, stream and reply"
```

---

### Task 9: Documentation truth pass

**Files:**
- Modify: `README.md`, `PLAN.md`

- [ ] **Step 1: Correct the documented surface**

README: document `--smoke`, `--no-shell`, `CODEMODE_STATE`; state that the desktop app shows a model picker in the header and a free-RAM readout; replace "Install a model runtime" first-step with "start the portable server that is already staged" (`tools\ollama\ollama.exe serve`) and note that `qwen2.5-coder:3b`/`7b` are already pulled here.

- [ ] **Step 2: Record the repair in PLAN.md**

Under "Phases", add a "Recovered" paragraph naming what was broken and what the `--selftest`/`--smoke` checks now cover. Do not add measurements that were not taken.

- [ ] **Step 3: Commit**

```bash
git add README.md PLAN.md
git commit -m "docs: describe the app that exists, including the recovery checks"
```

---

### Task 10: Final verification (run once, in this order)

- [ ] `python -m py_compile app/*.py` → exit 0
- [ ] `python -m unittest discover -s tests -v` → all pass
- [ ] `tools/ollama/ollama.exe serve` running; `curl -s http://127.0.0.1:11434/api/tags` lists two models
- [ ] `python app/ui.py --selftest` → `ok: true`, `model` non-empty, `input_below_transcript`, `sidebar_mapped`, `ram_visible`, `terminal_hidden`, `dead_buttons: 0`
- [ ] `python app/ui.py --smoke` → non-empty reply, exit 0
- [ ] Launch `start-codemode.cmd`; send one message, confirm it streams, `chat-session.json` grows, and reopening restores the transcript (user-confirmable; report as manual)
- [ ] Confirm `state/handoff.md` is absent until a real compaction writes one
