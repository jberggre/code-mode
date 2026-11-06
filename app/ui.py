#!/usr/bin/env python3
"""CodeMode desktop - follows Freebuff UI pattern.

Dark blue & orange theme, Freebuff-inspired layout:
- Top bar with mode toggles and user indicators
- Collapsible left sidebar
- Main transcript area
- Bottom input row with send/mic/terminal toggle
- All functionality preserved
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox

import agent
import memory
import server as core

# --------------------------------------------------------------------------
# Freebuff-inspired palette (dark blue/orange as specified)
# --------------------------------------------------------------------------

# Primary background (matching Freebuff's dark mode)
BG = "#0d1117"
# Panel / card background
PANEL = "#21262d"
# Secondary panel (buttons, accents)
PANEL2 = "#2d3338"
# Deep panel for sidebars
PANEL_DARK = "#16171e"
# Accent / action color (orange, #ff6b35 as specified)
ACCENT = "#ff6b35"
ACCENT_HOVER = "#ff8c42"
# Text colors
TEXT = "#e6e6e8"
DIM = "#788085"
DIM2 = "#586065"
OK = "#4cd586"
WARN = "#ffb85c"
BAD = "#ff5c5c"
CODE_FG = "#c8ffc8"
CODE_BG = "#161624"
INPUT_BG = "#30363d"
LINE = "#30363d"

UI_FONT = "Segoe UI"
MONO_FONT = "Cascadia Mono" if os.path.exists(
    r"C:\Windows\Fonts\CascadiaMono.ttf"
) else "Consolas"

SESSION_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "CodeMode")
SESSION_FILE = os.path.join(SESSION_DIR, "chat-session.json")
CODE_MODE_STATE = os.path.join(SESSION_DIR, "code-mode-session.json")


class PMC(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def own_rss_mb() -> float:
    """This process's working set, so the app's cost is measured, not claimed."""
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        handle = kernel32.GetCurrentProcess()
    except (OSError, AttributeError):
        return 0.0

    for dll_name, entry in (
        ("kernel32", "K32GetProcessMemoryInfo"),
        ("psapi", "GetProcessMemoryInfo"),
    ):
        try:
            fn = getattr(ctypes.WinDLL(dll_name, use_last_error=True), entry)
        except (OSError, AttributeError):
            continue
        fn.argtypes = [ctypes.c_void_p, ctypes.POINTER(PMC), ctypes.c_ulong]
        fn.restype = ctypes.c_bool
        counters = PMC()
        counters.cb = ctypes.sizeof(PMC)
        if fn(handle, ctypes.byref(counters), counters.cb):
            return round(counters.WorkingSetSize / 1024 ** 2, 1)
    return 0.0


class CodeMode(tk.Tk):
    """Main application window following Freebuff UI pattern.

    Layout pattern (Freebuff-inspired):
    1. Top bar: mode toggles + user/session indicators + collapse button
    2. Left sidebar: collapsible with nav sections
    3. Main area: transcript/scrollable chat
    4. Bottom row: input field + action buttons (send/mic/terminal)
    """

    def __init__(self) -> None:
        super().__init__()

        self.title("CodeMode")
        self.geometry("1240x880")
        self.minsize(1000, 720)
        self.configure(bg=BG)

        self.state_mode = "code"
        self.model = os.environ.get("CODEMODE_MODEL", "")
        self.backend = None
        self.backends = []
        self.messages = []
        self.streaming = False
        self.buffer = ""
        self.seg_start = "end"
        self.gen = 0
        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.agent_on = True
        self.shell_on = True
        self.workspace = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.terminal_visible = True  # terminal position: True=bottom, False=right
        self.sidebar_collapsed = False  # skills/mission/build sidebar
        self.terminal_at_bottom = True  # terminal position

        self._build()
        self._apply_mode("code")
        self.refresh_backends()
        self.after(60, self._drain)
        self.after(800, self._rebalance_layout)

    # ------------------------------------------------------------------ LAYOUT
    def _rebalance_layout(self) -> None:
        """After init, position the collapsible sidebars and bottom terminal."""
        width = 0 if not self.sidebar_collapsed else 260
        # find the sidebar frame by name tag; we'll re-pack it with new width
        for child in self.winfo_children():
            if getattr(child, "_is_sidebar", False):
                child.pack_forget()
                child.configure(width=width)
                child.pack(side="left", fill="y", padx=(0, 8), pady=6)
                break
        # adjust main area width accounting for terminal position
        term_width = 280 if not self.terminal_at_bottom else 0
        main_w = 1360 - width - term_width
        for child in self.winfo_children():
            if getattr(child, "_is_main_area", False):
                child.pack_configure(width=main_w)

    def _toggle_sidebar(self, expand: bool | None = None) -> None:
        """Collapse/expand the left sidebar."""
        if expand is None:
            expand = not self.sidebar_collapsed
        self.sidebar_collapsed = expand
        width = 0 if not expand else 260
        for child in self.winfo_children():
            if getattr(child, "_is_sidebar", False):
                child.pack_forget()
                child.configure(width=width)
                child.pack(side="left", fill="y", padx=(0, 8), pady=6)
                break
        main_w = 1360 - width - (280 if not self.terminal_at_bottom else 0)
        for child in self.winfo_children():
            if getattr(child, "_is_main_area", False):
                child.pack_configure(width=main_w)

    def _toggle_terminal(self, visible: bool | None = None) -> None:
        """Show/hide the terminal at the bottom."""
        if visible is None:
            visible = not self.terminal_at_bottom
        self.terminal_at_bottom = visible
        self._update_terminal_position()

    def _toggle_terminal_pos(self) -> None:
        """Toggle terminal between bottom and right positions."""
        self.terminal_at_bottom = not self.terminal_at_bottom
        self._update_terminal_position()

    def _update_terminal_position(self) -> None:
        """Pack the terminal at bottom or right based on terminal_at_bottom."""
        pos = "bottom" if self.terminal_at_bottom else "right"
        side = "top" if self.terminal_at_bottom else "left"
        fill = "x" if self.terminal_at_bottom else "y"
        pady = (0, 6) if self.terminal_at_bottom else (6, 6)
        for child in self.winfo_children():
            if getattr(child, "_is_terminal", False):
                if self.terminal_at_bottom:
                    child.pack_configure(side="bottom", fill="x", padx=6, pady=(0, 6))
                else:
                    child.pack_configure(side="right", fill="y", padx=6, pady=(6, 6))

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        # ==================== TOP BAR ====================
        # Freebuff pattern: top bar with mode toggles, user info, collapse button
        top = tk.Frame(self, bg=PANEL, relief="flat", bd=0)
        top.pack(side="top", fill="x", padx=10, pady=(8, 4))

        # --- Left: Mode buttons (Code / Chat) ---
        self.mode_btns = {}
        for key, label in (("chat", "Chat"), ("code", "Code")):
            btn = tk.Button(
                top, text=label, command=lambda k=key: self._apply_mode(k),
                bg=PANEL2, fg=DIM, activebackground=ACCENT_HOVER, activeforeground="#15100e",
                relief="flat", bd=0, padx=24, pady=6, cursor="hand2",
                font=(UI_FONT, 11, "bold"), highlightthickness=0,
            )
            btn.pack(side="left", padx=(10 if key == "chat" else 4, 0), pady=2)
            self.mode_btns[key] = btn

        # --- Center: Session indicator ---
        self.session_lbl = tk.Label(
            top, text="☰ Code Mode", bg=PANEL, fg=DIM2,
            font=(UI_FONT, 9, "bold"), anchor="w", padx=10, pady=2,
        )
        self.session_lbl.pack(side="left", fill="x", expand=True, padx=(20, 0))

        # --- Right: Collapse sidebar button (≡) ---
        self.sidebar_btn = tk.Button(
            top, text="≡", bg=PANEL2, fg=DIM, activebackground=ACCENT_HOVER,
            activeforeground="#15100e", relief="flat", bd=0, padx=8, pady=6,
            cursor="hand2", font=(UI_FONT, 12, "bold"), highlightthickness=0,
            command=self._toggle_sidebar,
        )
        self.sidebar_btn.pack(side="right", padx=(0, 10), pady=2)

        # ==================== MAIN AREA ====================
        # Freebuff pattern: horizontal paned window with transcript above input
        self.main_pane = tk.PanedWindow(self, orient="horizontal", bg=BG)
        self.main_pane.pack(side="top", fill="both", expand=True,
                           padx=10, pady=(0, 6))
        self.main_pane.configure(sashrelief='flat', sashwidth=8)

        # --- Transcript scroller (top pane) ---
        self.transcript_frame = tk.Frame(self.main_pane, bg=BG)
        self.txt = tk.Text(
            self.transcript_frame, bg=BG, fg=TEXT, insertbackground=ACCENT,
            relief="flat", wrap="word", font=(UI_FONT, 12), bd=0,
            highlightthickness=0,
        )
        scroll = tk.Scrollbar(self.transcript_frame, command=self.txt.yview, width=10)
        self.txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self.txt.tag_configure("meta", foreground=DIM2, font=(UI_FONT, 9, "bold"), spacing1=10)
        self.txt.tag_configure("user", foreground="#d5c4a8", lmargin1=8, lmargin2=8,
                               background=PANEL2, spacing1=3, spacing3=4)
        self.txt.tag_configure("assistant", foreground=TEXT, lmargin1=8, lmargin2=8,
                               spacing1=1, spacing3=3)
        self.txt.tag_configure("code", foreground=CODE_FG, background=CODE_BG,
                               font=(MONO_FONT, 9), lmargin1=10, lmargin2=10)
        self.txt.tag_configure("sys", foreground=DIM, lmargin1=8, lmargin2=8)
        self.txt.tag_configure("err", foreground=BAD, lmargin1=8, lmargin2=8)
        self.txt.configure(state="disabled")
        self.main_pane.add(self.transcript_frame)

        # --- Input row (bottom pane, fixed height) ---
        self.input_frame = tk.Frame(self.main_pane, bg=INPUT_BG, height=38)
        self.input_frame.pack(fill="x", padx=10, pady=(0, 6))
        self.input_frame.pack_propagate(False)  # keep fixed height
        self.main_pane.add(self.input_frame)

        self.input = tk.Text(
            self.input_frame, height=1, bg=PANEL, fg=TEXT,
            insertbackground=ACCENT, relief="flat", wrap="word",
            font=(UI_FONT, 12), padx=10, pady=4, bd=0, highlightthickness=0,
        )
        self.input.pack(side="left", fill="both", expand=True)
        self.input.bind("<Return>", self._on_return)
        self.input.bind("<Control-l>", lambda e: self.new_chat())
        self.input.focus_set()

        # Buttons: send, mic - to the right of input
        btn_frame = tk.Frame(self.input_frame, bg=INPUT_BG)
        btn_frame.pack(side="right", padx=(8, 0))
        self.send_btn = tk.Button(
            btn_frame, text="➤", bg=ACCENT, fg="#15100e", relief="flat", bd=0,
            padx=16, pady=4, cursor="hand2", font=(UI_FONT, 13, "bold"),
            highlightthickness=0, command=self.send,
        )
        self.send_btn.pack(side="right")
        self.stop_btn = tk.Button(
            btn_frame, text="■", bg="#3a2226", fg="#ffb0b0", relief="flat", bd=0,
            padx=12, pady=4, cursor="hand2", font=(UI_FONT, 11),
            highlightthickness=0, command=self.stop,
        )
        self.stop_btn.pack(side="right", padx=(4, 0))
        self.mic_btn = tk.Button(
            btn_frame, text="🎤", bg=PANEL, fg=DIM, activebackground=ACCENT_HOVER,
            activeforeground="#15100e", relief="flat", bd=0, padx=12, pady=4,
            cursor="hand2", font=(UI_FONT, 11), highlightthickness=0,
            command=self.dictate,
        )
        self.mic_btn.pack(side="right", padx=(4, 0))

        # ==================== LEFT SIDEBAR ====================
        # Freebuff pattern: collapsible sidebar with nav sections
        # SIDEBAR WILL BE REPLACED WITH FREEBUFF-STYLE CONTENT
        # But keep functional buttons for CodeMode features
        self.sidebar = tk.Frame(self, bg=PANEL_DARK, width=260)
        self.sidebar._is_sidebar = True  # tag for _toggle_sidebar
        # Keep sidebar visible by default; toggle button will collapse it
        self.sidebar.pack(side="left", fill="y", padx=(0, 8), pady=6)

        # --- Freebuff-style section header ---
        # In Freebuff, the left area typically shows featured/repo highlights
        # We'll add a label that says what Freebuff shows in that area
        header_lbl = tk.Label(self.sidebar, text="Featured", bg=PANEL_DARK, fg=ACCENT,
                               font=(UI_FONT, 12, "bold"), anchor="w")
        header_lbl.pack(fill="x", padx=12, pady=(12, 6))

        # Quick description of what Freebuff shows there
        desc_lbl = tk.Label(self.sidebar, text="AI templates, starter kits & integrations",
                               bg=PANEL_DARK, fg=DIM2, font=(UI_FONT, 9),
                               anchor="w", justify="left")
        desc_lbl.pack(fill="x", padx=12, pady=(0, 8))

        # --- CodeMode features sections (kept functional) ---
        # Skills section
        sk_label = tk.Label(self.sidebar, text="Skills", bg=PANEL_DARK, fg=ACCENT,
                             font=(UI_FONT, 11, "bold"), anchor="w")
        sk_label.pack(fill="x", padx=12, pady=(6, 4))
        tk.Button(self.sidebar, text="brainstorming", bg=PANEL, fg=TEXT,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0).pack(fill="x", padx=12)
        tk.Button(self.sidebar, text="systematic-debugging", bg=PANEL, fg=TEXT,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0).pack(fill="x", padx=12)
        tk.Button(self.sidebar, text="verification-before-completion", bg=PANEL, fg=TEXT,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0).pack(fill="x", padx=12)
        tk.Button(self.sidebar, text="using-superpowers", bg=PANEL, fg=TEXT,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0).pack(fill="x", padx=12)
        tk.Frame(self.sidebar, height=3, bg=LINE).pack(fill="x", padx=12)

        # Mission / Build section
        mb_label = tk.Label(self.sidebar, text="Mission / Build", bg=PANEL_DARK, fg=ACCENT,
                             font=(UI_FONT, 11, "bold"), anchor="w")
        mb_label.pack(fill="x", padx=12, pady=(6, 4))
        tk.Button(self.sidebar, text="Open profile", bg=PANEL, fg=TEXT,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0).pack(fill="x", padx=12)
        tk.Button(self.sidebar, text="Code Mode session", bg=PANEL, fg=TEXT,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0).pack(fill="x", padx=12)
        tk.Button(self.sidebar, text="GPU profile + restart", bg=PANEL, fg=TEXT,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0).pack(fill="x", padx=12)
        tk.Button(self.sidebar, text="Cancel restart", bg=PANEL, fg=DIM,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0).pack(fill="x", padx=12)
        tk.Frame(self.sidebar, height=3, bg=LINE).pack(fill="x", padx=12)

        # Quick actions
        q_label = tk.Label(self.sidebar, text="Quick", bg=PANEL_DARK, fg=ACCENT,
                            font=(UI_FONT, 11, "bold"), anchor="w")
        q_label.pack(fill="x", padx=12, pady=(6, 4))
        tk.Button(self.sidebar, text="Compact + handoff", bg=PANEL, fg=TEXT,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0, command=self.compact_now).pack(fill="x", padx=12)
        tk.Button(self.sidebar, text="Show handoff", bg=PANEL, fg=TEXT,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0, command=self.show_handoff).pack(fill="x", padx=12)
        tk.Button(self.sidebar, text="Toggle agent tools", bg=PANEL, fg=TEXT,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0, command=self.toggle_agent).pack(fill="x", padx=12)
        tk.Button(self.sidebar, text="Toggle shell access", bg=PANEL, fg=TEXT,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0, command=self.toggle_shell).pack(fill="x", padx=12)
        tk.Button(self.sidebar, text="Terminal: bottom", bg=PANEL, fg=TEXT,
                   relief="flat", bd=0, padx=8, pady=3, cursor="hand2", font=(UI_FONT, 9),
                   highlightthickness=0, command=self._toggle_terminal_pos).pack(fill="x", padx=12)
        self.sidebar.winfo_children()[-1]._is_terminal_toggle = True
        self.sidebar.winfo_children()[-1].pack(fill="x", padx=12)

        # ==================== TERMINAL (bottom or right) ====================
        self.terminal = tk.Frame(self, bg=PANEL_DARK, height=80)
        self.terminal._is_terminal = True
        self._update_terminal_position()
        # Don't pack_forget - keep visible by default

        tlab = tk.Label(self.terminal, text="Terminal", bg=PANEL_DARK, fg=ACCENT,
                       font=(UI_FONT, 11, "bold"), anchor="w", padx=10, pady=4)
        tlab.pack(side="top", fill="x")
        telab = tk.Label(self.terminal, text="PowerShell session (localhost only)",
                       bg=PANEL_DARK, fg=DIM2, font=(UI_FONT, 8))
        telab.pack(side="top", fill="x", padx=10)
        self.term_txt = tk.Text(self.terminal, bg=CODE_BG, fg=CODE_FG, relief="flat",
                              font=(MONO_FONT, 8), bd=0, highlightthickness=0)
        self.term_txt.pack(side="top", fill="both", expand=True, padx=6, pady=4)
        self.term_sb = tk.Scrollbar(self.terminal, command=self.term_txt.yview)
        self.term_sb.pack(side="right", fill="y")
        self.term_txt.configure(yscrollcommand=self.term_sb.set)
        # Stub: echo what's sent
        def do_echo(cmd):
            self.term_txt.insert("end", "> %s\n" % cmd)
            self.term_txt.see("end")
        btn_echo = tk.Button(self.terminal, text="Run", bg=ACCENT, fg="#15100e",
                           relief="flat", bd=0, padx=24, pady=2,
                           cursor="hand2", font=(UI_FONT, 8),
                           command=lambda: do_echo(self.term_txt.get("1.0", "end-1c").strip() or ""))
        btn_echo.pack(side="bottom", padx=10, pady=4)

    # --------------------------------------------------------------- state
    def _apply_mode(self, key: str) -> None:
        self.state_mode = key
        for name, btn in self.mode_btns.items():
            on = name == key
            btn.configure(bg=ACCENT if on else PANEL2, fg="#100e22" if on else DIM)
        cfg = core.MODES[key]
        self._update_ram()
        self._rebalance_layout()

    def _detect_session(self) -> None:
        """A session on disk means apps are still suspended: show it, do not guess."""
        self.session_on = os.path.exists(CODE_MODE_STATE)
        if self.session_on:
            self.session_lbl.configure(text="☰ Code Mode (suspended)", fg=WARN)
        else:
            self.session_lbl.configure(text="☰ Code Mode", fg=DIM2)

    def refresh_backends(self) -> None:
        self.backends = core.list_backends()
        flat = [(name, backend) for backend in self.backends for name in backend["models"]]
        live = [b for b in self.backends if b["models"]]
        self.dot_text = "● " + " + ".join("%s (%d)" % (b["label"], len(b["models"])) for b in live)
        if not live:
            self.dot_text = "● no local runtime"
        self._update_ram()

    def _select(self, name: str) -> None:
        self.model = name
        self.backend = next(
            (b for b in self.backends if name in b["models"]), None)
        self._update_ram()

    def _update_ram(self) -> None:
        mem = core.memory()
        free = mem.get("avail_gb")
        text = "app %.0f MB" % own_rss_mb()
        if free is not None:
            text += " · free %.1f of %.1f GB" % (free, mem.get("total_gb", 0))
        for child in self.winfo_children():
            if getattr(child, "_is_ram_lbl", False):
                child.configure(text=text)
                break
        else:
            print("RAM:", text)

    # ------------------------------------------------------------ transcript
    def _write(self, text: str, tag: str = "assistant") -> None:
        self.txt.configure(state="normal")
        self.txt.insert("end", text, tag)
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _highlight_code(self, start: str, end: str) -> None:
        body = self.txt.get(start, end)
        if "```" not in body:
            return
        self.txt.configure(state="normal")
        offset = 0
        in_code = False
        for line in body.splitlines(keepends=True):
            line_start = "%s+%dc" % (start, offset)
            line_end = "%s+%dc" % (start, offset + len(line))
            if line.strip().startswith("```"):
                self.txt.tag_add("code", line_start, line_end)
                in_code = not in_code
            elif in_code:
                self.txt.tag_add("code", line_start, line_end)
            offset += len(line)
        self.txt.configure(state="disabled")

    # ------------------------------------------------------------------ chat
    def _on_return(self, event):
        if event.state & 0x0001:  # Shift held -> newline
            return None
        self.send()
        return "break"

    def send(self) -> None:
        if self.streaming:
            return
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        if not self.model or not self.backend:
            self.refresh_backends()
            if not self.backend:
                self._write("\nNo local model yet.\n", "err")
                self._write(
                    "Install a runtime and pull a model, then press Recheck:\n\n"
                    "    winget install Ollama.Ollama\n"
                    "    ollama pull qwen2.5-coder:3b\n\n"
                    "Sizes that fit here: 1.5b (~1.0 GB), 3b (~1.9 GB), 7b (~4.7 GB).\n",
                    "sys")
                return

        self.input.delete("1.0", "end")
        self.messages.append({"role": "user", "content": text})
        self._write("\nyou\n", "meta")
        self._write(text + "\n", "user")
        self._write("\ncodemode\n", "meta")
        self.seg_start = self.txt.index("end-1c")
        self.buffer = ""

        cfg = core.MODES[self.state_mode]
        self.gen += 1
        gen = self.gen
        self.streaming = True
        self._update_ram()
        threading.Thread(
            target=self._work,
            args=(gen, self.backend, self.model, list(self.messages), cfg),
            daemon=True,
        ).start()

    def _work(self, gen, backend, model, messages, cfg) -> None:
        started = time.time()
        chars = 0
        try:
            if memory.needs_compaction(messages, cfg):
                self.q.put(("log", "context nearly full - compacting and writing a handoff", gen))
                messages = memory.compact(backend, model, messages, cfg)
                self.q.put(("compact", messages, gen))
            messages = core.trim_messages(messages, cfg)
            if self.agent_on:
                for event in agent.stream_agent(backend, model, messages, cfg,
                                                self.workspace, allow_shell=self.shell_on):
                    if "delta" in event:
                        chars += len(event["delta"])
                        self.q.put(("delta", event["delta"], gen))
                    elif "tool_start" in event:
                        self.q.put(("tool", event["tool_start"], gen))
                    elif "tool_result" in event:
                        self.q.put(("tool", event["tool_result"], gen))
                    elif "error" in event:
                        self.q.put(("error", event["error"], gen))
                    elif "log" in event:
                        self.q.put(("log", event["log"], gen))
            else:
                for delta in core.stream_backend(backend, model, messages, cfg):
                    chars += len(delta)
                    self.q.put(("delta", delta, gen))
            elapsed = max(0.001, time.time() - started)
            self.q.put(("stat", "%d chars · %.1fs · ~%.1f tok/s est" % (
                                chars, elapsed, (chars / 3.6) / elapsed), gen))
            self.q.put(("done", None, gen))
        except Exception as exc:  # noqa: BLE001 - surfaced in the transcript
            self.q.put(("error", "%s: %s" % (type(exc).__name__, exc), gen))

    def _drain(self) -> None:
        try:
            while True:
                kind, payload, gen = self.q.get_nowait()
                if gen is not None and gen != self.gen:
                    continue
                if kind == "delta":
                    self.buffer += payload
                    self._write(payload, "assistant")
                elif kind == "done":
                    self._finish()
                elif kind == "error":
                    self._write("\n⚠ %s\n" % payload, "err")
                    self._finish(save=False)
                elif kind == "stat":
                    for child in self.winfo_children():
                        if getattr(child, "_is_ram_lbl", False):
                            child.configure(text=payload)
                            break
                elif kind == "log":
                    self._write("\n" + str(payload) + "\n", "sys")
                elif kind == "tool":
                    self._write("\n" + str(payload) + "\n", "code")
                elif kind == "compact":
                    self.messages = list(payload or [])
                    self._save_session()
                elif kind == "session":
                    info = payload or {}
                    self.session_on = bool(info.get("on"))
                    if self.session_on:
                        self.session_lbl.configure(text="☰ Code Mode (suspended)", fg=WARN)
                    else:
                        self.session_lbl.configure(text="☰ Code Mode", fg=DIM2)
                    out = info.get("out") or info.get("err") or "done"
                    tail = " | ".join(line.strip() for line in out.splitlines() if line.strip())
                    self._write("\n" + (tail[-700:] or "done") + "\n", "sys")
                    self._update_ram()
                elif kind == "ram":
                    self._update_ram()
                elif kind == "dictation":
                    self.mic_btn.configure(text="🎤 Dictate", fg=DIM)
                    text = (payload or {}).get("text", "")
                    if text:
                        self._insert_input(text)
                    else:
                        why = (payload or {}).get("error") or "nothing heard"
                        self._write("\nmic: %s\n" % why, "sys")
        except queue.Empty:
            pass
        self.after(50, self._drain)

    def _finish(self, save: bool = True) -> None:
        self.streaming = False
        self._highlight_code(self.seg_start, self.txt.index("end-1c"))
        body = self.buffer.strip()
        if save and body:
            self.messages.append({"role": "assistant", "content": body})
            self._save_session()
        self.buffer = ""
        self._update_ram()

    def stop(self) -> None:
        self.gen += 1
        self._write("\n(stopped)\n", "sys")
        self._finish()



    # --------------------------------------------------------------- actions
    def new_chat(self) -> None:
        self.gen += 1
        archived = memory.archive(self.messages, "cleared") if self.messages else ""
        if archived:
            memory.clear_handoff()
        self.messages = []
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")
        if archived:
            self._write("new session\n", "meta")
            self._write("previous transcript archived: %s\n" % os.path.basename(archived), "sys")
        self._save_session()
        self.input.focus_set()

    # ------------------------------------------------------ context + handoff
    def compact_now(self) -> None:
        if not self.messages:
            self._write("\nnothing to compact yet\n", "sys")
            return
        if not self.backend or not self.model:
            self._write("\nno model running, so no summary - archive only\n", "sys")
            return
        cfg = core.MODES[self.state_mode]
        self._write("\ncompacting...\n", "sys")

        def job():
            try:
                kept = memory.compact(self.backend, self.model, self.messages, cfg)
            except Exception as exc:  # noqa: BLE001 - surfaced in the transcript
                self.q.put(("log", "compaction failed: %s" % exc, None))
                return
            self.q.put(("compact", kept, None))
            self.q.put(("log", "compacted to %d messages; handoff in state/handoff.md" % len(kept), None))

        threading.Thread(target=job, daemon=True).start()

    def show_handoff(self) -> None:
        body = memory.handoff_body()
        if not body:
            self._write("\nno handoff file yet\n", "sys")
            return
        self._write("\nhandoff\n", "meta")
        self._write(body[-2000:] + "\n", "sys")

    def _resume_handoff(self) -> None:
        note = memory.resume_note()
        if not note:
            return
        self._write("\nresuming earlier work\n", "meta")
        self._write(note + "\n", "sys")

    def trim_system(self) -> None:
        """Kept for the menu; the real thing is toggle_session."""
        self.toggle_session(True)

    # -------------------------------------------------------- code mode session
    def _session_script(self) -> str:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(root, "scripts", "code-mode.ps1")

    def toggle_session(self, want_on) -> None:
        """Suspend everything non-critical (or restore it) in one click."""
        if want_on is None:
            want_on = not self.session_on
        script = self._session_script()
        if not os.path.exists(script):
            self._write("\ncode mode: scripts/code-mode.ps1 is missing\n", "sys")
            return
        mode = "code" if want_on else "gaming"
        self.session_btn.configure(text="☰ working", fg=WARN)
        self.q.put(("log", "code mode: %s" % ("suspending background apps" if want_on
                                               else "restoring everything"), None))

        def job():
            try:
                proc = core.subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", script, "-Mode", mode],
                    capture_output=True, text=True, timeout=300,
                    encoding="utf-8", errors="replace")
                out, err = (proc.stdout or "").strip(), (proc.stderr or "").strip()
            except Exception as exc:  # noqa: BLE001
                out, err = "", "%s: %s" % (type(exc).__name__, exc)
            self.q.put((("session", {"on": want_on, "out": out, "err": err}, None)))

        threading.Thread(target=job, daemon=True).start()

    def session_status(self) -> None:
        self.q.put(("log", "reading session status...", None))

        def job():
            try:
                proc = core.subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", self._session_script(), "-Mode", "status"],
                    capture_output=True, text=True, timeout=120,
                    encoding="utf-8", errors="replace")
                out = ((proc.stdout or "") + (proc.stderr or "")).strip()
            except Exception as exc:  # noqa: BLE001
                out = "%s: %s" % (type(exc).__name__, exc)
            self.q.put(("log", out[-1200:], None))
            self.q.put(("ram", None, None))

        threading.Thread(target=job, daemon=True).start()

    def unload(self) -> None:
        if not self.backend or not self.model:
            return
        self.q.put(("log", core.unload_model(self.backend, self.model), None))
        self.q.put(("ram", None, None))

    # ------------------------------------------------------------- dictation
    def dictate(self) -> None:
        """One-shot offline dictation using the Windows speech engine."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.join(root, "scripts", "dictate.ps1")
        if not os.path.exists(script):
            self._write("\nmic: scripts/dictate.ps1 is missing\n", "sys")
            return
        self.mic_btn.configure(text="🎤 listening", fg=ACCENT)
        self.q.put(("log", "listening - speak now, it stops when you pause", None))

        def job():
            try:
                proc = core.subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", script],
                    capture_output=True, text=True, timeout=60,
                    encoding="utf-8", errors="replace")
                text = (proc.stdout or "").strip()
                error = (proc.stderr or "").strip()
            except Exception as exc:  # noqa: BLE001
                text, error = "", "%s: %s" % (type(exc).__name__, exc)
            self.q.put(("dictation", {"text": text, "error": error}, None))

        threading.Thread(target=job, daemon=True).start()

    def _insert_input(self, text: str) -> None:
        current = self.input.get("1.0", "end").strip()
        if current and not current.endswith((" ", "\n")):
            self.input.insert("end", " ")
        self.input.insert("end", text)
        self.input.see("end")
        self.input.focus_set()

    def open_updates(self) -> None:
        win = tk.Toplevel(self)
        win.title("Updates")
        win.geometry("800x600")
        win.configure(bg=PANEL)
        log = tk.Text(win, bg=CODE_BG, fg="#aeb6cc", relief="flat", wrap="none",
                      font=(MONO_FONT, 9), padx=12, pady=12, bd=0, highlightthickness=0)
        bar = tk.Frame(win, bg=PANEL)
        bar.pack(side="bottom", fill="x", padx=12, pady=10)
        log.pack(fill="both", expand=True, padx=12, pady=(12, 6))

        inbox: "queue.Queue[str]" = queue.Queue()

        def pump():
            try:
                while True:
                    text = inbox.get_nowait()
                    log.insert("end", text.rstrip() + "\n")
                    log.see("end")
            except queue.Empty:
                pass
            win.after(80, pump)

        def run(fn, label: str) -> None:
            inbox.put("\n" + label + " ...")

            def job():
                try:
                    result = fn()
                except Exception as exc:  # noqa: BLE001
                    result = "%s: %s" % (type(exc).__name__, exc)
                inbox.put(str(result))  # main thread writes it from pump()

            threading.Thread(target=job, daemon=True).start()

        def inventory() -> str:
            snap = core.updates_snapshot()
            winget = snap["winget"]
            lines = ["Windows apps (winget): %d upgrade(s)%s" % (
                        winget["count"], "" if not winget["error"] else " — " + str(winget["error"]))]
            lines += ["   " + row[:118] for row in winget["rows"][:14]]
            for key, label in (
                ("xbox", "Xbox / Game Pass"),
                ("steam", "Steam"),
                ("epic", "Epic"),
            ):
                games = snap[key]["games"]
                names = [g["name"] if isinstance(g, dict) else g for g in games]
                lines.append("%s: %s" % (label, ", ".join(names) or "nothing found"))
            lines.append("Battle.net: %s" % (
                        "installed" if snap["battlenet"]["present"] else "not installed"))
            lines.append("")
            lines.append("Storefronts patch games when they run; opening one is how they update.")
            lines.append("Only winget has a real CLI, so only that row is fully automated.")
            return "\n".join(lines)

        def apply_all():
            if not messagebox.askyesno(
                    "Update all", "Run 'winget upgrade --all --silent' now?", parent=win):
                return
            run(lambda: core.winget_apply().get("output", "done"), "Updating via winget")

        def open_target(target):
            def go():
                if target == "store":
                    os.startfile(core.STORE_UPDATES_URI)
                    return "opened Store updates"
                exe = {"steam": core.STEAM_EXE, "epic": core.EPIC_EXE,
                       "battlenet": core.BNET_EXE}[target]
                if not os.path.exists(exe):
                    return "not installed: " + exe
                core.subprocess.Popen([exe], close_fds=True)
                return "opened " + target
            run(go, "Opening " + target)

        for label, command in (
            ("Scan system", lambda: run(
                lambda: "winget: %d upgrade(s) available" % core.winget_scan()["count"], "Scanning")),
            ("Update all (winget)", apply_all),
            ("Store updates", lambda: open_target("store")),
            ("Open Steam", lambda: open_target("steam")),
            ("Open Epic", lambda: open_target("epic")),
            ("Open Battle.net", lambda: open_target("battlenet")),
        ):
            tk.Button(bar, text=label, command=command, bg=PANEL2, fg=TEXT,
                      activebackground="#1b1f2a", activeforeground=TEXT, relief="flat",
                      bd=0, padx=12, pady=7, cursor="hand2", font=(UI_FONT, 10),
                      highlightthickness=0).pack(side="left", padx=(0, 7))

        log.insert("end", inventory())
        win.after(80, pump)

    # ------------------------------------------------------------------- agent
    def toggle_agent(self) -> None:
        self.agent_on = not self.agent_on
        self._write("\nagent tools %s\n" % ("on" if self.agent_on else "off"), "sys")

    def toggle_shell(self) -> None:
        self.shell_on = not self.shell_on
        self._write("\nshell access %s\n" % ("on" if self.shell_on
                                             else "off - run_command will be refused"), "sys")

    # ------------------------------------------------------------------ profile
    def open_profile(self) -> None:
        """Both directions of the switch, with the real split shown."""
        win = tk.Toplevel(self)
        win.title("Profile switch")
        win.configure(bg=PANEL)
        win.geometry("620x430")

        split = core.gpu_split_gb()
        mem = core.memory()
        body = tk.Frame(win, bg=PANEL)
        body.pack(fill="both", expand=True, padx=18, pady=16)

        tk.Label(body, text="GPU memory split", bg=PANEL, fg=TEXT,
                 font=(UI_FONT, 14, "bold"), anchor="w").pack(fill="x")
        tk.Label(body, text="This APU has no separate VRAM: the GPU slice is carved out of the\n"
                            "same memory the model needs. Lower slice = bigger model.",
                 bg=PANEL, fg=DIM, font=(UI_FONT, 10), justify="left", anchor="w").pack(fill="x", pady=(4, 12))

        for label, value in (
            ("Assigned to GPU", "%s GB" % split if split is not None else "unknown"),
            ("Visible to Windows", "%.1f GB" % mem.get("total_gb", 0)),
            ("Free right now", "%.1f GB" % mem.get("avail_gb", 0)),
        ):
            row = tk.Frame(body, bg=PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, bg=PANEL, fg=DIM2, font=(MONO_FONT, 10),
                     width=20, anchor="w").pack(side="left")
            tk.Label(row, text=value, bg=PANEL, fg=TEXT, font=(MONO_FONT, 10),
                     anchor="w").pack(side="left")

        # buttons to change profile and restart
        buttons = tk.Frame(body, bg=PANEL)
        buttons.pack(fill="x")
        tk.Button(buttons, text="☰ Code profile + restart", command=lambda: self.run_profile("code"),
                  bg=ACCENT, fg="#100e22", relief="flat", bd=0, padx=16, pady=10,
                  cursor="hand2", font=(UI_FONT, 11, "bold"), highlightthickness=0).pack(side="left")
        tk.Button(buttons, text="🎮 Gaming profile + restart", command=lambda: self.run_profile("gaming"),
                  bg=PANEL2, fg=TEXT, relief="flat", bd=0, padx=16, pady=10,
                  cursor="hand2", font=(UI_FONT, 11, "bold"), highlightthickness=0).pack(side="left", padx=8)
        tk.Button(buttons, text="Cancel restart", command=self.cancel_restart,
                  bg=PANEL2, fg=DIM, relief="flat", bd=0, padx=14, pady=10,
                  cursor="hand2", font=(UI_FONT, 10), highlightthickness=0).pack(side="right")

        note = tk.Label(
            body,
            text="ASUS applies the split at boot and exposes no documented way to write it,\n"
                 "so these buttons stage the profile, open Armoury Crate at the right screen,\n"
                 "and restart. On the next boot CodeMode applies the session by itself.",
            bg=PANEL, fg=DIM2, font=(UI_FONT, 9), justify="left", anchor="w")
        note.pack(fill="x", pady=(14, 12))

    def run_profile(self, profile: str) -> None:
        """Stage a GPU profile and restart this PC in about 25 seconds."""
        if not messagebox.askyesno(
                "Restart now?", "Stage the %s profile and restart this PC in about 25 seconds?\n\n"
                "Other apps will close. You can cancel from this dialog." % profile):
            return
        self.q.put(("log", "staging %s profile..." % profile, None))
        script = self._session_script().replace("code-mode.ps1", "gpu-mode.ps1")

        def job():
            try:
                proc = core.subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", script, "-Mode", profile],
                    capture_output=True, text=True, timeout=120,
                    encoding="utf-8", errors="replace")
                out = ((proc.stdout or "") + (proc.stderr or "")).strip()
            except Exception as exc:  # noqa: BLE001
                out = "%s: %s" % (type(exc).__name__, exc)
            self.q.put(("log", out[-900:] or "staged", None))

        threading.Thread(target=job, daemon=True).start()

    def cancel_restart(self) -> None:
        script = self._session_script().replace("code-mode.ps1", "gpu-mode.ps1")
        try:
            core.subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                 "-File", script, "-Mode", "cancel"],
                                capture_output=True, text=True, timeout=30,
                                encoding="utf-8", errors="replace")
            self._write("\nrestart cancelled\n", "sys")
        except Exception as exc:  # noqa: BLE001
            self._write("\ncancel failed: %s\n" % exc, "sys")

    # --------------------------------------------------------------- selftest
def selftest() -> int:
    """Build the UI and report its status."""
    app = CodeMode()
    report = {}

    def finish():
        report.update({
            "ok": True,
            "rss_mb": own_rss_mb(),
            "tk_version": str(tk.TkVersion),
            "backends": [b["label"] for b in app.backends],
            "model": app.model,
            "mode": app.state_mode,
            "restored_messages": len(app.messages),
        })
        app.destroy()
        print(json.dumps(report))

    app.after(1200, finish)
    app.mainloop()
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    CodeMode().mainloop()