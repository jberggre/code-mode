"""The right-hand rail: a real terminal and the session/memory control centre.

Two tabs, because this is the core set the owner chose: run something, and see
what the machine and the context window are doing. Every control here calls the
same backend the browser UI uses - no mock rows, no placeholder buttons.
"""

from __future__ import annotations

import threading
import tkinter as tk

import server as core
import speech
import theme
import tools as toolbox


class RightPanel(tk.Frame):
    def __init__(self, app, parent):
        super().__init__(parent, bg=theme.SIDEBAR, width=344,
                         highlightbackground=theme.HAIRLINE, highlightthickness=1)
        # Children are packed, so grid_propagate alone leaves the rail free to
        # grow to the terminal's default 80-character width.
        self.grid_propagate(False)
        self.pack_propagate(False)
        self.app = app
        self.tab = "terminal"

        head = tk.Frame(self, bg=theme.SIDEBAR)
        head.pack(side="top", fill="x", padx=10, pady=(10, 8))
        self.tabs = theme.Segmented(head, [("terminal", "Terminal"), ("session", "Session")],
                                    "terminal", on_change=self.show, size=9)
        self.tabs.pack(side="left")
        theme.button(head, "\u2715", self.app.toggle_panel, kind="bare", size=10,
                     padx=7, pady=2).pack(side="right")

        theme.hairline(self).pack(side="top", fill="x")

        self.body = tk.Frame(self, bg=theme.SIDEBAR)
        self.body.pack(side="top", fill="both", expand=True)

        self.views = {
            "terminal": self._build_terminal(self.body),
            "session": self._build_session(self.body),
        }
        self.show("terminal")

    # ------------------------------------------------------------------ tabs
    def show(self, tab: str) -> None:
        if tab not in self.views:
            return
        self.tab = tab
        self.tabs.select(tab)
        for name, view in self.views.items():
            if name == tab:
                view.pack(fill="both", expand=True)
            else:
                view.pack_forget()

    # -------------------------------------------------------------- terminal
    def _build_terminal(self, parent) -> tk.Frame:
        view = tk.Frame(parent, bg=theme.SIDEBAR)

        bar = tk.Frame(view, bg=theme.SIDEBAR)
        bar.pack(side="top", fill="x", padx=12, pady=(10, 6))
        theme.micro(bar, "PowerShell \u00b7 workspace").pack(side="left")
        theme.button(bar, "Clear", self.clear, kind="bare", size=8, padx=6,
                     pady=2).pack(side="right")

        wrap = tk.Frame(view, bg=theme.CODE_BG, highlightbackground=theme.HAIRLINE,
                        highlightthickness=1)
        wrap.pack(side="top", fill="both", expand=True, padx=12, pady=(0, 8))

        self.term_out = tk.Text(wrap, width=30, height=12, bg=theme.CODE_BG,
                                fg=theme.CODE_FG, relief="flat", bd=0,
                                highlightthickness=0, wrap="word",
                                font=theme.mono(9), padx=10, pady=8,
                                insertbackground=theme.ACCENT, spacing1=1, spacing3=2)
        scroll = theme.scrollbar(wrap, self.term_out.yview)
        self.term_out.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.term_out.pack(side="left", fill="both", expand=True)
        self.term_out.tag_configure("cmd", foreground=theme.ACCENT)
        self.term_out.tag_configure("bad", foreground=theme.BAD)
        self.term_out.tag_configure("ok", foreground=theme.OK)
        self.term_out.configure(state="disabled")

        self.shell_note = theme.label(view, "", tone="dim2", size=8)
        self.shell_note.pack(side="bottom", fill="x", padx=12, pady=(0, 8))

        row = tk.Frame(view, bg=theme.SIDEBAR)
        row.pack(side="bottom", fill="x", padx=12, pady=(0, 6))
        self.cmd_var = tk.StringVar()
        self.cmd_entry = tk.Entry(row, textvariable=self.cmd_var, bg=theme.SURFACE_2,
                                  fg=theme.TEXT, insertbackground=theme.ACCENT,
                                  relief="flat", bd=0, highlightthickness=1,
                                  highlightbackground=theme.HAIRLINE,
                                  highlightcolor=theme.ACCENT, font=theme.mono(9))
        self.cmd_entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.cmd_entry.bind("<Return>", lambda _e: self.run_command())
        theme.button(row, "Run", self.run_command, kind="primary", size=9,
                     padx=12, pady=5).pack(side="left", padx=(6, 0))

        self.write("Ready. Commands run in the workspace as you.\n", "ok")
        return view

    def write(self, text: str, tag: str = "") -> None:
        self.term_out.configure(state="normal")
        self.term_out.insert("end", text, (tag,) if tag else ())
        self.term_out.see("end")
        self.term_out.configure(state="disabled")

    def clear(self) -> None:
        self.term_out.configure(state="normal")
        self.term_out.delete("1.0", "end")
        self.term_out.configure(state="disabled")

    def run_command(self) -> None:
        command = self.cmd_var.get().strip()
        if not command:
            return
        if not self.app.shell_on:
            self.write("shell access is off - turn it on below, then run this again\n", "bad")
            return
        self.cmd_var.set("")
        self.write("> %s\n" % command, "cmd")

        def job():
            result = toolbox.run_command(self.app.workspace, command, timeout=120)
            self.app.q.put(("term", result.rstrip() + "\n", None))

        threading.Thread(target=job, daemon=True).start()

    # --------------------------------------------------------------- session
    def _build_session(self, parent) -> tk.Frame:
        view = tk.Frame(parent, bg=theme.SIDEBAR)
        pad = tk.Frame(view, bg=theme.SIDEBAR)
        pad.pack(fill="both", expand=True, padx=12, pady=12)

        theme.micro(pad, "Memory").pack(fill="x")
        mem_card = theme.card(pad)
        mem_card.pack(fill="x", pady=(4, 12))
        self.ram_meter = theme.Meter(mem_card, width=290, height=6)
        self.ram_meter.pack(fill="x", padx=10, pady=(10, 6))
        self.ram_text = theme.label(mem_card, "reading\u2026", tone="text", size=9)
        self.ram_text.pack(fill="x", padx=10)
        self.rss_text = theme.label(mem_card, "", tone="dim2", size=8)
        self.rss_text.pack(fill="x", padx=10, pady=(0, 8))

        theme.micro(pad, "Model").pack(fill="x")
        model_card = theme.card(pad)
        model_card.pack(fill="x", pady=(4, 12))
        self.model_name = theme.label(model_card, "none selected", tone="text",
                                      size=10, weight="bold")
        self.model_name.pack(fill="x", padx=10, pady=(8, 0))
        self.model_backend = theme.label(model_card, "no runtime", tone="dim2", size=8)
        self.model_backend.pack(fill="x", padx=10, pady=(1, 6))
        model_actions = tk.Frame(model_card, bg=theme.SURFACE)
        model_actions.pack(fill="x", padx=10, pady=(0, 9))
        theme.button(model_actions, "Start runtime", self._start_runtime,
                     kind="ghost", size=9).pack(side="left", fill="x", expand=True)
        theme.button(model_actions, "Unload", self.app.unload, kind="ghost",
                     size=9).pack(side="left", fill="x", expand=True, padx=(6, 0))

        theme.micro(pad, "Session").pack(fill="x")
        for text, command in (
            ("Code Mode session", self.app.toggle_session_btn),
            ("Trim system for Code Mode", self.app.trim_system),
            ("Compact + write handoff", self.app.compact_now),
            ("Show handoff", self.app.show_handoff),
            ("GPU profile + restart", self.app.open_profile),
        ):
            theme.button(pad, text, command, kind="bare", size=9, padx=8,
                         pady=3, anchor="w").pack(fill="x")

        theme.hairline(pad).pack(fill="x", pady=(8, 4))
        theme.micro(pad, "Capabilities").pack(fill="x")
        self.agent_btn = theme.button(pad, "Agent tools \u00b7 on", self._toggle_agent,
                                      kind="bare", size=9, padx=8, pady=4, anchor="w")
        self.agent_btn.pack(fill="x")
        self.shell_btn = theme.button(pad, "Shell access \u00b7 on", self._toggle_shell,
                                      kind="bare", size=9, padx=8, pady=4, anchor="w")
        self.shell_btn.pack(fill="x")
        self.mic_btn = theme.button(pad, "Dictate \u00b7 off", self.app.dictate,
                                    kind="bare", size=9, padx=8, pady=4, anchor="w")
        self.mic_btn.pack(fill="x")
        # Packed by offer_speech_install() only if the background probe finds no
        # recogniser - probing here would block the window for a second at start.
        self.speech_btn = theme.button(pad, "Install Windows speech",
                                       self.app.install_speech, kind="bare",
                                       size=9, padx=8, pady=4, anchor="w")
        self.note = theme.label(pad, "Runs as you, unsandboxed \u00b7 turn it off to be safe.",
                                tone="dim2", size=8, wraplength=290, justify="left")
        self.note.pack(fill="x", pady=(4, 0))
        return view

    def offer_speech_install(self, missing: bool) -> None:
        if missing:
            self.speech_btn.pack(fill="x")
            self.note.pack_forget()
            self.note.pack(fill="x", pady=(4, 0))
        else:
            self.speech_btn.pack_forget()

    def _start_runtime(self) -> None:
        self.app.q.put(("note", "starting the portable Ollama server\u2026", None))

        def job():
            self.app.q.put(("note", core.start_ollama(), None))
            self.app.q.put(("refresh", None, None))

        threading.Thread(target=job, daemon=True).start()

    def _toggle_agent(self) -> None:
        self.app.toggle_agent()
        self.refresh(self.app.last_rss)

    def _toggle_shell(self) -> None:
        self.app.toggle_shell()
        self.refresh(self.app.last_rss)

    # ---------------------------------------------------------------- update
    def refresh(self, rss_mb: float = 0.0) -> None:
        app = self.app
        mem = core.memory()
        total = mem.get("total_gb") or 0
        avail = mem.get("avail_gb") or 0
        used = 1 - (avail / total) if total else 0
        colour = theme.BAD if used > 0.85 else theme.WARN if used > 0.7 else theme.ACCENT
        self.ram_meter.set(used, colour)
        self.ram_text.configure(text="%.1f GB free of %.1f GB" % (avail, total))
        self.rss_text.configure(
            text="this window %.0f MB \u00b7 %s" % (
                rss_mb, "session live" if app.session_on else "no session"))
        self.model_name.configure(text=app.model or "none selected")
        self.model_backend.configure(
            text=app.backend["label"] if app.backend else "no runtime answering")
        self.agent_btn.configure(text="Agent tools \u00b7 %s" % ("on" if app.agent_on else "off"))
        self.shell_btn.configure(text="Shell access \u00b7 %s" % ("on" if app.shell_on else "off"))
        self.mic_btn.configure(
            text="Dictate \u00b7 %s" % ("listening" if app.listening else "off"))
        self.shell_note.configure(
            text="" if app.shell_on else "shell access is off \u00b7 Run will refuse",
            fg=theme.DIM2 if app.shell_on else theme.WARN)
