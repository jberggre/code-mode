#!/usr/bin/env python3
"""CodeMode desktop - a Freebuff-shaped shell for a local model.

Layout, left to right: the workspace rail, the transcript with the composer
under it, and the terminal/session rail. One orange accent on deep navy, 1px
hairlines instead of borders, and every control wired to the backend that the
browser UI already uses.

No HTTP server, no Chromium: this window IS the app. Python 3.11 stdlib only.
"""

from __future__ import annotations

import ctypes
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox

import agent
import memory
import panels
import server as core
import session_store
import theme

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE_MODE_STATE = os.path.join(session_store.base_dir(), "code-mode-session.json")


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
    for dll_name, entry in (("kernel32", "K32GetProcessMemoryInfo"),
                            ("psapi", "GetProcessMemoryInfo")):
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
    def __init__(self, no_shell: bool = False):
        super().__init__()

        self.title("CodeMode")
        # This panel is 1920x1080 at 150%: the logical work area is about
        # 1280x680, so anything taller pushes the composer off the screen.
        self.geometry("1264x680")
        self.minsize(1000, 620)
        self.configure(bg=theme.BG)
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self._dark_titlebar()

        session = session_store.load_session()
        self.workspace = ROOT
        self.messages = session["messages"]
        self.state_mode = session["mode"]
        self.model = session["model"]
        self.backend = None
        self.backends = []
        self.streaming = False
        self.buffer = ""
        self.seg_start = "end"
        self.gen = 0
        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.agent_on = True
        self.shell_on = not no_shell
        self.session_on = os.path.exists(CODE_MODE_STATE)
        self.sidebar_visible = True
        self.panel_visible = True
        self.last_rss = 0.0

        self._build()
        self._apply_mode(self.state_mode, save=False)
        self.refresh_backends(auto=True)
        self._render_history()
        self._resume_banner()
        self._update_ram()
        self.after(60, self._drain)
        self.after(20000, self._tick)

    # ==================================================================== UI
    def _build(self) -> None:
        self._build_topbar()

        self.body = tk.Frame(self, bg=theme.BG)
        self.body.pack(side="top", fill="both", expand=True)
        self.body.rowconfigure(0, weight=1)
        self.body.columnconfigure(1, weight=1)

        self._build_sidebar()
        self._build_main()

        self.panel = panels.RightPanel(self, self.body)
        self.panel.grid(row=0, column=2, sticky="nsew")
        self.panel.refresh(0.0)

    def _build_topbar(self) -> None:
        bar = tk.Frame(self, bg=theme.SURFACE, height=56)
        bar.pack(side="top", fill="x")
        bar.pack_propagate(False)

        brand = tk.Frame(bar, bg=theme.SURFACE)
        brand.pack(side="left", padx=(14, 0), pady=10)
        theme.label(brand, "\u25c6", tone="accent", size=13, weight="bold",
                    bg=theme.SURFACE).pack(side="left")
        theme.label(brand, "CodeMode", tone="text", size=12, weight="bold",
                    bg=theme.SURFACE).pack(side="left", padx=(8, 5))
        theme.label(brand, "offline", tone="dim2", size=8, bg=theme.SURFACE).pack(
            side="left", pady=(3, 0))

        self.mode_seg = theme.Segmented(bar, [("chat", "Chat"), ("code", "Code")],
                                        self.state_mode, on_change=self._apply_mode)
        self.mode_seg.pack(side="left", padx=(20, 10), pady=12)

        self.model_btn = tk.Menubutton(bar, text="detecting models\u2026",
                                       bg=theme.SURFACE_2, fg=theme.TEXT,
                                       activebackground=theme.SURFACE_3,
                                       activeforeground=theme.TEXT, relief="flat",
                                       bd=0, highlightthickness=1,
                                       highlightbackground=theme.HAIRLINE,
                                       highlightcolor=theme.ACCENT, font=theme.ui(9),
                                       padx=10, pady=5, cursor="hand2")
        self.model_menu = tk.Menu(self.model_btn, tearoff=0, bg=theme.SURFACE_2,
                                  fg=theme.TEXT, activebackground=theme.ACCENT,
                                  activeforeground=theme.ACCENT_INK, bd=0,
                                  font=theme.ui(9))
        self.model_btn.configure(menu=self.model_menu)
        self.model_btn.pack(side="left", pady=12)

        right = tk.Frame(bar, bg=theme.SURFACE)
        right.pack(side="right", padx=12, pady=10)
        theme.button(right, "\u2630", self.toggle_sidebar, kind="bare", size=11,
                     padx=8, pady=3).pack(side="right")
        theme.button(right, "\u25a4", self.toggle_panel, kind="bare", size=11,
                     padx=8, pady=3).pack(side="right", padx=(0, 2))
        self.status = theme.chip(right, "checking runtime", "warn")
        self.status["frame"].pack(side="right", padx=(0, 10))

        theme.hairline(self).pack(side="top", fill="x")

    def _build_sidebar(self) -> None:
        side = tk.Frame(self.body, bg=theme.SIDEBAR, width=260,
                        highlightbackground=theme.HAIRLINE, highlightthickness=1)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)
        side.pack_propagate(False)
        self.sidebar = side

        head = tk.Frame(side, bg=theme.SIDEBAR)
        head.pack(side="top", fill="x", padx=12, pady=(14, 8))
        theme.micro(head, "Workspace").pack(fill="x")
        theme.label(head, os.path.basename(self.workspace), tone="text", size=11,
                    weight="bold").pack(fill="x", pady=(2, 0))
        theme.label(head, self.workspace, tone="dim2", size=8, wraplength=226,
                    justify="left").pack(fill="x")

        theme.button(side, "+  New chat", self.new_chat, kind="primary",
                     size=10).pack(fill="x", padx=12, pady=(6, 12))

        theme.micro(side, "Session").pack(fill="x", padx=12)
        card = theme.card(side)
        card.pack(fill="x", padx=12, pady=(4, 12))
        self.sess_mode = theme.label(card, "", tone="text", size=9)
        self.sess_mode.pack(fill="x", padx=10, pady=(9, 0))
        self.sess_msgs = theme.label(card, "", tone="dim2", size=8)
        self.sess_msgs.pack(fill="x", padx=10, pady=(0, 9))

        # Only three here: everything else lives in the Session tab, and six
        # rows pushed the memory meter off a 680 px-tall screen.
        theme.micro(side, "Quick").pack(fill="x", padx=12)
        for text, command in (
            ("Compact + handoff", self.compact_now),
            ("Code Mode session", self.toggle_session_btn),
            ("GPU profile + restart", self.open_profile),
        ):
            theme.button(side, text, command, kind="bare", size=9, padx=8,
                         pady=4, anchor="w").pack(fill="x", padx=12)

        foot = tk.Frame(side, bg=theme.SIDEBAR)
        foot.pack(side="bottom", fill="x", padx=12, pady=12)
        theme.hairline(foot).pack(fill="x", pady=(0, 8))
        row = tk.Frame(foot, bg=theme.SIDEBAR)
        row.pack(fill="x")
        theme.micro(row, "Memory").pack(side="left")
        self.ram_pct = theme.label(row, "", tone="dim2", size=8)
        self.ram_pct.pack(side="right")
        self.ram_meter = theme.Meter(foot, width=232, height=5, fill=theme.ACCENT)
        self.ram_meter.pack(fill="x", pady=(4, 5))
        self.ram_text = theme.label(foot, "reading\u2026", tone="dim", size=8)
        self.ram_text.pack(fill="x")
        self.rss_text = theme.label(foot, "", tone="dim2", size=8)
        self.rss_text.pack(fill="x")

    def _build_main(self) -> None:
        main = tk.Frame(self.body, bg=theme.BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(1, weight=1)
        main.columnconfigure(0, weight=1)
        self.main = main

        self.banner = tk.Frame(main, bg=theme.SURFACE,
                               highlightbackground=theme.HAIRLINE, highlightthickness=1)
        inner = tk.Frame(self.banner, bg=theme.SURFACE)
        inner.pack(fill="x", padx=12, pady=8)
        self.banner_text = theme.label(inner, "", tone="dim", size=9,
                                       bg=theme.SURFACE)
        self.banner_text.pack(side="left", fill="x", expand=True)
        theme.button(inner, "Show", self.show_handoff, kind="ghost", size=8,
                     padx=8, pady=3).pack(side="left", padx=(8, 4))
        theme.button(inner, "Dismiss", self._dismiss_banner, kind="bare", size=8,
                     padx=6, pady=3).pack(side="left")

        wrap = tk.Frame(main, bg=theme.BG)
        wrap.grid(row=1, column=0, sticky="nsew")
        self.txt = tk.Text(wrap, bg=theme.BG, fg=theme.TEXT,
                           insertbackground=theme.ACCENT, relief="flat", bd=0,
                           highlightthickness=0, wrap="word", font=theme.ui(11),
                           padx=20, pady=16, spacing1=2, cursor="arrow")
        scroll = theme.scrollbar(wrap, self.txt.yview)
        self.txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        self._configure_tags()
        self.txt.configure(state="disabled")

        self._build_composer(main)

    def _build_composer(self, main) -> None:
        outer = tk.Frame(main, bg=theme.BG)
        outer.grid(row=2, column=0, sticky="ew", padx=16, pady=(4, 14))

        card = tk.Frame(outer, bg=theme.SURFACE,
                        highlightbackground=theme.HAIRLINE, highlightthickness=1)
        card.pack(fill="x")

        row = tk.Frame(card, bg=theme.SURFACE)
        row.pack(fill="x", padx=10, pady=(9, 5))
        self.input = tk.Text(row, width=20, height=1, bg=theme.SURFACE, fg=theme.TEXT,
                             insertbackground=theme.ACCENT, relief="flat", bd=0,
                             highlightthickness=0, wrap="word", font=theme.ui(11),
                             padx=0, pady=3, undo=True)
        self.input.pack(side="left", fill="both", expand=True)
        self.input.bind("<Return>", self._on_return)
        self.input.bind("<Control-l>", self._new_chat_key)
        self.input.bind("<Control-j>", self._panel_key)
        self.input.bind("<KeyRelease>", self._grow_input)

        self.send_btn = theme.button(row, "\u25b8", self.send, kind="primary",
                                     size=12, padx=14, pady=4)
        self.send_btn.pack(side="right", padx=(6, 0))
        self.stop_btn = theme.button(row, "\u25a0", self.stop, kind="danger",
                                     size=10, padx=10, pady=4)

        foot = tk.Frame(card, bg=theme.SURFACE)
        foot.pack(fill="x", padx=12, pady=(0, 8))
        self.stat_lbl = theme.label(
            foot, "Enter to send \u00b7 Shift+Enter for a new line \u00b7 Ctrl+L new chat",
            tone="dim2", size=8, bg=theme.SURFACE)
        self.stat_lbl.pack(side="left")
        self.ctx_lbl = theme.label(foot, "", tone="dim2", size=8, bg=theme.SURFACE)
        self.ctx_lbl.pack(side="right")
        self.ctx_meter = theme.Meter(foot, width=84, height=5, fill=theme.ACCENT)
        self.ctx_meter.pack(side="right", padx=(0, 8))

    def _configure_tags(self) -> None:
        t = self.txt
        t.tag_configure("who", foreground=theme.DIM2, font=theme.ui(8, "bold"),
                        spacing1=16, spacing3=5)
        t.tag_configure("user", foreground=theme.TEXT, background=theme.SURFACE_2,
                        lmargin1=14, lmargin2=14, rmargin=30, spacing1=8,
                        spacing3=8, relief="flat", borderwidth=1)
        t.tag_configure("assistant", foreground=theme.TEXT, lmargin1=4,
                        lmargin2=4, rmargin=22, spacing1=1, spacing3=8)
        t.tag_configure("code", foreground=theme.CODE_FG, background=theme.CODE_BG,
                        font=theme.mono(9), lmargin1=14, lmargin2=14, rmargin=22,
                        spacing1=2, spacing3=2)
        t.tag_configure("sys", foreground=theme.DIM, font=theme.ui(9), lmargin1=6,
                        lmargin2=6, spacing1=4, spacing3=4)
        t.tag_configure("err", foreground=theme.BAD, font=theme.ui(9), lmargin1=6,
                        lmargin2=6, spacing1=4, spacing3=4)
        t.tag_configure("tool", foreground=theme.DIM2, font=theme.mono(8),
                        lmargin1=10, lmargin2=10, spacing1=3)

    def _dark_titlebar(self) -> None:
        """Windows paints a light caption bar unless the window asks otherwise."""
        try:
            self.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            enabled = ctypes.c_int(1)
            for attribute in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled))
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

    # ================================================================ layout
    def toggle_sidebar(self) -> None:
        self.sidebar_visible = not self.sidebar_visible
        if self.sidebar_visible:
            self.sidebar.grid(row=0, column=0, sticky="nsew")
        else:
            self.sidebar.grid_remove()

    def toggle_panel(self) -> None:
        self.panel_visible = not self.panel_visible
        if self.panel_visible:
            self.panel.grid(row=0, column=2, sticky="nsew")
            self.panel.refresh(self.last_rss)
        else:
            self.panel.grid_remove()

    def _new_chat_key(self, _event=None):
        self.new_chat()
        return "break"

    def _panel_key(self, _event=None):
        self.toggle_panel()
        return "break"

    # ================================================================= state
    def _apply_mode(self, key: str, save: bool = True) -> None:
        if key not in core.MODES:
            key = "code"
        self.state_mode = key
        self.mode_seg.select(key)
        self._sync_session_card()
        self._update_ctx()
        if save:
            self._save_session()

    def _sync_session_card(self) -> None:
        cfg = core.MODES.get(self.state_mode, core.MODES["code"])
        count = len(self.messages)
        self.sess_mode.configure(text="%s \u00b7 %d token window" % (cfg["label"], cfg["num_ctx"]))
        self.sess_msgs.configure(text="%d message%s" % (count, "" if count == 1 else "s"))

    def refresh_backends(self, auto: bool = False) -> None:
        self.backends = core.list_backends()
        live = [b for b in self.backends if b.get("models")]
        if live:
            theme.set_chip(self.status, " + ".join(
                "%s %d" % (b["label"], len(b["models"])) for b in live), "ok")
        else:
            suffix = " \u00b7 portable server stopped" if os.path.exists(core.OLLAMA_EXE) else ""
            theme.set_chip(self.status, "no runtime" + suffix, "warn")
        self._populate_models()
        if auto:
            backend, name = core.pick_model(
                self.backends, self.model or os.environ.get("CODEMODE_MODEL", ""))
            if backend:
                self.backend = backend
                self.model = name
                self.model_btn.configure(text=name)
                self._save_session()
        elif not self.backend and live:
            self.backend, self.model = core.pick_model(self.backends, self.model)
            self.model_btn.configure(text=self.model or "select model")
        if hasattr(self, "panel"):
            self.panel.refresh(self.last_rss)
        self._sync_session_card()

    def _populate_models(self) -> None:
        self.model_menu.delete(0, "end")
        count = 0
        for backend in self.backends:
            for name in backend.get("models") or []:
                label = name if backend["kind"] == "ollama" else "%s  (%s)" % (
                    name, backend["label"])
                self.model_menu.add_command(label=label,
                                            command=lambda n=name: self._select(n))
                count += 1
        if not count:
            self.model_menu.add_command(label="no model found", state="disabled")
        if self.model:
            self.model_btn.configure(text=self.model)
        else:
            self.model_btn.configure(text="select model" if count else "no model")

    def _select(self, name: str) -> None:
        backend, _ = core.pick_model(self.backends, name)
        if not backend:
            return
        self.backend = backend
        self.model = name
        self.model_btn.configure(text=name)
        self._save_session()
        self._write("\nmodel: %s on %s\n" % (name, backend["label"]), "sys")
        if hasattr(self, "panel"):
            self.panel.refresh(self.last_rss)

    def _save_session(self) -> None:
        session_store.save_session({"mode": self.state_mode, "model": self.model,
                                    "messages": self.messages})

    def _update_ram(self) -> None:
        mem = core.memory()
        total = mem.get("total_gb") or 0
        free = mem.get("avail_gb") or 0
        used = 1 - (free / total) if total else 0
        colour = theme.BAD if used > 0.85 else theme.WARN if used > 0.7 else theme.ACCENT
        self.ram_meter.set(used, colour)
        self.ram_pct.configure(text="%d%% used" % int(used * 100))
        self.ram_text.configure(text="%.1f of %.1f GB free" % (free, total))
        self.last_rss = own_rss_mb()
        self.rss_text.configure(text="this window %.0f MB" % self.last_rss)
        if hasattr(self, "panel"):
            self.panel.refresh(self.last_rss)

    def _update_ctx(self) -> None:
        cfg = core.MODES.get(self.state_mode, core.MODES["code"])
        used = memory.history_tokens(self.messages, cfg)
        budget = memory.budget(cfg)
        ratio = (used / budget) if budget else 0
        colour = theme.BAD if ratio > 0.85 else theme.WARN if ratio > 0.65 else theme.ACCENT
        self.ctx_meter.set(ratio, colour)
        self.ctx_lbl.configure(text="ctx %d / %d" % (used, budget),
                               fg=colour if ratio > 0.65 else theme.DIM2)

    def _tick(self) -> None:
        try:
            if not self.streaming:
                self._update_ram()
            if not self.backend:
                self.refresh_backends()
        finally:
            self.after(20000, self._tick)

    # ============================================================ transcript
    def _write(self, text: str, tag: str = "assistant") -> None:
        self.txt.configure(state="normal")
        self.txt.insert("end", text, (tag,) if tag else ())
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _clear_transcript(self) -> None:
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

    def _append_message(self, role: str, content: str) -> None:
        self.txt.configure(state="normal")
        self.txt.insert("end", ("you" if role == "user" else "codemode") + "\n", "who")
        start = self.txt.index("end-1c")
        self.txt.insert("end", content.rstrip() + "\n",
                        "user" if role == "user" else "assistant")
        self._highlight(start, self.txt.index("end-1c"))
        self.txt.configure(state="disabled")
        self.txt.see("end")

    def _highlight(self, start: str, end: str) -> None:
        body = self.txt.get(start, end)
        if "```" not in body:
            return
        self.txt.configure(state="normal")
        offset = 0
        in_code = False
        for line in body.splitlines(keepends=True):
            line_start = self.txt.index("%s + %dc" % (start, offset))
            line_end = self.txt.index("%s + %dc" % (start, offset + len(line)))
            if line.strip().startswith("```"):
                self.txt.tag_add("code", line_start, line_end)
                in_code = not in_code
            elif in_code:
                self.txt.tag_add("code", line_start, line_end)
            offset += len(line)
        self.txt.configure(state="disabled")

    def _render_history(self) -> None:
        self._clear_transcript()
        if not self.messages:
            self._empty_state()
            return
        for message in self.messages:
            self._append_message(message["role"], message["content"])

    def _empty_state(self) -> None:
        cfg = core.MODES[self.state_mode]
        self.txt.configure(state="normal")
        self.txt.insert("end", "codemode\n", "who")
        self.txt.insert("end", "A local coding shell for this machine. %s\n" % cfg["hint"], "sys")
        self.txt.insert("end", "\n", "sys")
        if self.backend:
            self.txt.insert("end", "%s on %s.\n" % (self.model, self.backend["label"]), "sys")
        else:
            self.txt.insert("end", "No runtime is answering yet. Start it from the "
                                   "Session panel on the right.\n", "sys")
        self.txt.insert("end", "\nAsk for a change, paste an error, or type a path. "
                               "Enter sends.\n", "sys")
        self.txt.configure(state="disabled")

    # ================================================================== chat
    def _on_return(self, event):
        if event.state & 0x0001:  # Shift held: newline
            return None
        self.send()
        return "break"

    def _grow_input(self, _event=None) -> None:
        content = self.input.get("1.0", "end-1c")
        lines = min(7, max(1, content.count("\n") + 1))
        if int(self.input.cget("height")) != lines:
            self.input.configure(height=lines)

    def _show_busy(self, busy: bool) -> None:
        self.streaming = busy
        if busy:
            self.send_btn.pack_forget()
            self.stop_btn.pack(side="right", padx=(6, 0))
        else:
            self.stop_btn.pack_forget()
            self.send_btn.pack(side="right", padx=(6, 0))

    def send(self) -> None:
        if self.streaming:
            return
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        if not self.backend:
            self.refresh_backends()
            if not self.backend:
                self._runtime_help()
                return

        self.input.delete("1.0", "end")
        self.input.configure(height=1)
        self.messages.append({"role": "user", "content": text})
        self._write("\n")
        self._append_message("user", text)
        self._sync_session_card()
        self._save_session()

        self.seg_start = self.txt.index("end-1c")
        self.buffer = ""
        self._write("\ncodemode\n", "who")

        cfg = core.MODES[self.state_mode]
        self.gen += 1
        gen = self.gen
        self._show_busy(True)
        self.stat_lbl.configure(text="thinking\u2026")
        threading.Thread(target=self._work, daemon=True,
                         args=(gen, self.backend, self.model,
                               list(self.messages), cfg)).start()

    def _work(self, gen, backend, model, messages, cfg) -> None:
        started = time.time()
        chars = 0
        try:
            if memory.needs_compaction(messages, cfg):
                self.q.put(("log", "context nearly full \u00b7 compacting and writing a handoff", gen))
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
            self.q.put(("stat", "%d chars \u00b7 %.1fs \u00b7 ~%.1f tok/s est" % (
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
                    self._write("\n\u26a0 %s\n" % payload, "err")
                    self._finish(save=False)
                elif kind == "stat":
                    self.stat_lbl.configure(text=payload)
                elif kind == "log":
                    self._write("\n%s\n" % payload, "sys")
                elif kind == "tool":
                    self._write("\n%s\n" % payload, "tool")
                elif kind == "compact":
                    self.messages = list(payload or [])
                    self._save_session()
                    self._sync_session_card()
                    self._update_ctx()
                elif kind == "session":
                    self._session_result(payload or {})
                elif kind == "term":
                    self.panel.write(payload)
                elif kind == "note":
                    self._write("\n%s\n" % payload, "sys")
                elif kind == "refresh":
                    self.refresh_backends(auto=not self.backend)
                elif kind == "ram":
                    self._update_ram()
                elif kind == "dictation":
                    self._dictation_result(payload or {})
        except queue.Empty:
            pass
        except Exception as exc:  # noqa: BLE001 - one bad event must not stop the loop
            try:
                self._write("\ninternal: %s: %s\n" % (type(exc).__name__, exc), "err")
            except Exception:  # noqa: BLE001
                pass
        finally:
            self.after(60, self._drain)

    def _finish(self, save: bool = True) -> None:
        self._show_busy(False)
        self._highlight(self.seg_start, self.txt.index("end-1c"))
        body = self.buffer.strip()
        if save and body:
            self.messages.append({"role": "assistant", "content": body})
            self._save_session()
        self.buffer = ""
        self._sync_session_card()
        self._update_ram()
        self._update_ctx()

    def stop(self) -> None:
        if not self.streaming:
            return
        self.gen += 1
        self._write("\n(stopped)\n", "sys")
        self._finish()

    def _runtime_help(self) -> None:
        self._write("\nno local runtime is answering\n", "err")
        if os.path.exists(core.OLLAMA_EXE):
            self._write("The portable Ollama is staged but stopped. Start it from the "
                        "Session panel, or run:\n", "sys")
            self._write("    tools\\ollama\\ollama.exe serve\n", "tool")
            self._write("Then the model list fills in on its own.\n", "sys")
        else:
            self._write("Install one and pull a model:\n", "sys")
            self._write("    winget install Ollama.Ollama\n"
                        "    ollama pull qwen2.5-coder:3b\n", "tool")

    def new_chat(self) -> None:
        self.gen += 1
        archived = memory.archive(self.messages, "cleared") if self.messages else ""
        if archived:
            memory.clear_handoff()
        self.messages = []
        self._clear_transcript()
        self._empty_state()
        self._dismiss_banner()
        self._save_session()
        self._sync_session_card()
        self._update_ctx()
        self.stat_lbl.configure(text="new session")
        self.input.focus_set()

    # ============================================================== handoff
    def compact_now(self) -> None:
        if not self.messages:
            self._write("\nnothing to compact yet\n", "sys")
            return
        if not self.backend or not self.model:
            self._write("\nno model running, so no summary \u00b7 archive only\n", "sys")
            memory.archive(self.messages, "manual")
            return
        cfg = core.MODES[self.state_mode]
        self._write("\ncompacting\u2026\n", "sys")

        def job():
            try:
                kept = memory.compact(self.backend, self.model, self.messages, cfg)
            except Exception as exc:  # noqa: BLE001
                self.q.put(("log", "compaction failed: %s" % exc, None))
                return
            self.q.put(("compact", kept, None))
            self.q.put(("note", "compacted to %d messages \u00b7 handoff in state/handoff.md"
                        % len(kept), None))

        threading.Thread(target=job, daemon=True).start()

    def show_handoff(self) -> None:
        body = memory.handoff_body()
        if not body:
            self._write("\nno handoff file yet\n", "sys")
            return
        self._write("\nhandoff\n", "who")
        self._write(body[-2400:] + "\n", "sys")
        self._dismiss_banner()

    def _resume_banner(self) -> None:
        note = memory.resume_note(220)
        if not note:
            return
        lines = note.splitlines()
        first = lines[0] if lines else "earlier work"
        self.banner_text.configure(text="Unfinished work from an earlier session \u00b7 " + first)
        self.banner.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))

    def _dismiss_banner(self) -> None:
        self.banner.grid_remove()

    # ================================================================ system
    def toggle_session_btn(self) -> None:
        self.toggle_session(None)

    def toggle_session(self, want_on) -> None:
        if want_on is None:
            want_on = not self.session_on
        script = self._session_script()
        if not os.path.exists(script):
            self._write("\ncode mode: scripts/code-mode.ps1 is missing\n", "sys")
            return
        mode = "code" if want_on else "gaming"
        self._write("\ncode mode: %s\u2026\n" % (
            "suspending background apps" if want_on else "restoring everything"), "sys")

        def job():
            try:
                proc = core.subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", script, "-Mode", mode],
                    capture_output=True, text=True, timeout=300,
                    encoding="utf-8", errors="replace")
                out = ((proc.stdout or "") + (proc.stderr or "")).strip()
            except Exception as exc:  # noqa: BLE001
                out = "%s: %s" % (type(exc).__name__, exc)
            self.q.put(("session", {"on": want_on, "out": out}, None))

        threading.Thread(target=job, daemon=True).start()

    def _session_result(self, info: dict) -> None:
        self.session_on = bool(info.get("on"))
        out = (info.get("out") or "done").strip()
        tail = " | ".join(line.strip() for line in out.splitlines() if line.strip())
        self._write("\n" + (tail[-800:] or "done") + "\n", "sys")
        self._update_ram()

    def trim_system(self) -> None:
        self.toggle_session(True)

    def unload(self) -> None:
        if not self.backend or not self.model:
            self._write("\nnothing loaded to unload\n", "sys")
            return

        def job():
            message = core.unload_model(self.backend, self.model)
            self.q.put(("note", message, None))
            self.q.put(("ram", None, None))

        threading.Thread(target=job, daemon=True).start()

    def toggle_agent(self) -> None:
        self.agent_on = not self.agent_on
        self._write("\nagent tools %s\n" % ("on" if self.agent_on else "off"), "sys")

    def toggle_shell(self) -> None:
        self.shell_on = not self.shell_on
        self._write("\nshell access %s\n" % (
            "on" if self.shell_on else "off \u00b7 run_command and Run will refuse"), "sys")

    def dictate(self) -> None:
        script = os.path.join(ROOT, "scripts", "dictate.ps1")
        if not os.path.exists(script):
            self._write("\nmic: scripts/dictate.ps1 is missing\n", "sys")
            return
        self._write("\nlistening \u00b7 speak now, it stops when you pause\n", "sys")

        def job():
            try:
                proc = core.subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", script], capture_output=True, text=True, timeout=60,
                    encoding="utf-8", errors="replace")
                text = (proc.stdout or "").strip()
                error = (proc.stderr or "").strip()
            except Exception as exc:  # noqa: BLE001
                text, error = "", "%s: %s" % (type(exc).__name__, exc)
            self.q.put(("dictation", {"text": text, "error": error}, None))

        threading.Thread(target=job, daemon=True).start()

    def _dictation_result(self, info: dict) -> None:
        text = info.get("text") or ""
        if text:
            current = self.input.get("1.0", "end-1c")
            if current.strip() and not current.endswith((" ", "\n")):
                self.input.insert("end", " ")
            self.input.insert("end", text)
            self.input.focus_set()
            self._grow_input()
        else:
            self._write("\nmic: %s\n" % (info.get("error") or "nothing heard"), "sys")

    def _session_script(self) -> str:
        return os.path.join(ROOT, "scripts", "code-mode.ps1")

    def open_profile(self) -> None:
        win = tk.Toplevel(self)
        win.title("Profile switch")
        win.configure(bg=theme.SURFACE)
        win.geometry("640x440")
        body = tk.Frame(win, bg=theme.SURFACE)
        body.pack(fill="both", expand=True, padx=20, pady=18)

        theme.micro(body, "GPU memory split").pack(fill="x")
        theme.label(body, "This APU has no separate VRAM: the GPU slice comes out of the "
                          "same memory the model needs. Lower slice, bigger model.",
                    tone="dim", size=10, wraplength=560, justify="left").pack(
                        fill="x", pady=(4, 14))

        split = core.gpu_split_gb()
        mem = core.memory()
        for name, value in (("Assigned to GPU", "%s GB" % split if split is not None else "unknown"),
                            ("Visible to Windows", "%.1f GB" % mem.get("total_gb", 0)),
                            ("Free right now", "%.1f GB" % mem.get("avail_gb", 0))):
            row = tk.Frame(body, bg=theme.SURFACE)
            row.pack(fill="x", pady=1)
            theme.label(row, name, tone="dim2", size=9, width=20,
                        bg=theme.SURFACE).pack(side="left")
            theme.label(row, value, tone="text", size=9,
                        bg=theme.SURFACE).pack(side="left")

        buttons = tk.Frame(body, bg=theme.SURFACE)
        buttons.pack(fill="x", pady=(18, 0))
        theme.button(buttons, "Code profile + restart",
                     lambda: self.run_profile("code"), kind="primary",
                     size=10).pack(side="left")
        theme.button(buttons, "Gaming profile + restart",
                     lambda: self.run_profile("gaming"), kind="ghost",
                     size=10).pack(side="left", padx=8)
        theme.button(buttons, "Cancel restart", self.cancel_restart, kind="bare",
                     size=9).pack(side="right")

        theme.label(body, "ASUS applies the split at boot and ships no documented way to "
                          "write it, so these buttons stage the profile, open Armoury Crate "
                          "and restart. On the next boot CodeMode applies the session itself.",
                    tone="dim2", size=9, wraplength=560, justify="left").pack(
                        fill="x", pady=(16, 0))

    def run_profile(self, profile: str) -> None:
        if not messagebox.askyesno(
                "Restart now?",
                "Stage the %s profile and restart this PC in about 25 seconds?\n\n"
                "Other apps will close." % profile):
            return
        script = self._session_script().replace("code-mode.ps1", "gpu-mode.ps1")
        self._write("\nstaging %s profile\u2026\n" % profile, "sys")

        def job():
            try:
                proc = core.subprocess.run(
                    ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", script, "-Mode", profile], capture_output=True,
                    text=True, timeout=120, encoding="utf-8", errors="replace")
                out = ((proc.stdout or "") + (proc.stderr or "")).strip()
            except Exception as exc:  # noqa: BLE001
                out = "%s: %s" % (type(exc).__name__, exc)
            self.q.put(("note", out[-900:] or "staged", None))

        threading.Thread(target=job, daemon=True).start()

    def cancel_restart(self) -> None:
        script = self._session_script().replace("code-mode.ps1", "gpu-mode.ps1")
        try:
            core.subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", script, "-Mode", "cancel"], capture_output=True, text=True,
                timeout=30, encoding="utf-8", errors="replace")
            self._write("\nrestart cancelled\n", "sys")
        except Exception as exc:  # noqa: BLE001
            self._write("\ncancel failed: %s\n" % exc, "sys")


# ===================================================================== checks
def selftest() -> int:
    app = CodeMode()
    report = {}

    def finish():
        dead = []

        def walk(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Button) and str(child.cget("command")) == "":
                    dead.append(str(child.cget("text")))
                walk(child)

        walk(app)
        report.update({
            "ok": True,
            "rss_mb": own_rss_mb(),
            "tk_version": str(tk.TkVersion),
            "backends": [b["label"] for b in app.backends],
            "models": [m for b in app.backends for m in b["models"]],
            "model": app.model,
            "mode": app.state_mode,
            "restored_messages": len(app.messages),
            "input_below_transcript": app.input.winfo_rooty() > app.txt.winfo_rooty(),
            "sidebar_mapped": bool(app.sidebar.winfo_ismapped()),
            "panel_mapped": bool(app.panel.winfo_ismapped()),
            "transcript_width": app.txt.winfo_width(),
            "dead_buttons": dead,
        })
        app.destroy()
        print(json.dumps(report))

    app.after(1400, finish)
    app.mainloop()
    return 0 if report.get("ok") else 1


def smoke() -> int:
    """Prove the whole path once, without a window: runtime -> model -> tokens."""
    backends = core.list_backends()
    backend, model = core.pick_model(
        backends, os.environ.get("CODEMODE_MODEL", "qwen2.5-coder:3b"))
    if not backend:
        message = ("portable Ollama is staged but not running"
                   if os.path.exists(core.OLLAMA_EXE) else "no local runtime")
        print(json.dumps({"ok": False, "error": message}))
        return 1
    cfg = dict(core.MODES["code"])
    cfg["num_predict"] = 48
    started = time.time()
    chars = 0
    try:
        for delta in core.stream_backend(
                backend, model,
                [{"role": "user", "content": "Reply with exactly: ok"}], cfg):
            chars += len(delta)
            if chars >= 400:
                break
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "backend": backend["kind"], "model": model,
                          "error": "%s: %s" % (type(exc).__name__, exc)}))
        return 1
    print(json.dumps({"ok": chars > 0, "backend": backend["kind"], "model": model,
                      "chars": chars, "seconds": round(time.time() - started, 1)}))
    return 0 if chars else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--selftest" in args:
        raise SystemExit(selftest())
    if "--smoke" in args:
        raise SystemExit(smoke())
    CodeMode(no_shell="--no-shell" in args).mainloop()
