"""CodeMode visual system: a Freebuff-shaped shell in deep navy and orange.

One accent (orange) on a layered navy ground, 1px hairlines instead of heavy
borders, uppercase micro-labels, and monospace reserved for code and numbers.
Every helper exists so the shell reads as one design instead of a pile of tk
defaults.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

# --- palette ---------------------------------------------------------------
BG = "#0a0f1e"          # app ground, deepest navy
SIDEBAR = "#0b1222"     # rail behind navigation
SURFACE = "#101a30"     # raised surface: top bar, cards
SURFACE_2 = "#16223c"   # inputs, chips, hover
SURFACE_3 = "#1d2b49"   # pressed / selected surface
HAIRLINE = "#1e2c4a"    # 1px separators
TEXT = "#e9eef9"
DIM = "#93a1bf"
DIM2 = "#5f6f90"
ACCENT = "#ff7a1a"
ACCENT_HOVER = "#ff9346"
ACCENT_INK = "#1a0f06"
OK = "#3ddc97"
WARN = "#ffb454"
BAD = "#ff5d6c"
CODE_BG = "#081120"
CODE_FG = "#c6d6ef"

FAMILY = "Segoe UI"
MONO_FAMILY = (
    "Cascadia Mono"
    if os.path.exists(os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                                   "Fonts", "CascadiaMono.ttf"))
    else "Consolas"
)

TONES = {
    "text": TEXT, "dim": DIM, "dim2": DIM2, "accent": ACCENT,
    "ok": OK, "warn": WARN, "bad": BAD, "ink": ACCENT_INK,
}


def ui(size: int = 10, weight: str = "normal") -> tuple:
    return (FAMILY, size, weight)


def mono(size: int = 9, weight: str = "normal") -> tuple:
    return (MONO_FAMILY, size, weight)


def parent_bg(widget, fallback: str = BG) -> str:
    try:
        value = widget.cget("bg")
        return str(value) or fallback
    except (tk.TclError, AttributeError):
        return fallback


def label(parent, text: str = "", tone: str = "text", size: int = 10,
          weight: str = "normal", **kw) -> tk.Label:
    options = dict(bg=parent_bg(parent), fg=TONES.get(tone, TEXT),
                   font=ui(size, weight), anchor="w", justify="left")
    options.update(kw)
    return tk.Label(parent, text=text, **options)


def micro(parent, text: str, tone: str = "dim2", **kw) -> tk.Label:
    """A section label: 8pt, bold, uppercase, dim. Used above every group."""
    options = dict(bg=parent_bg(parent), fg=TONES.get(tone, DIM2),
                   font=ui(8, "bold"), anchor="w", pady=2)
    options.update(kw)
    return tk.Label(parent, text=text.upper(), **options)


def hairline(parent, color: str = HAIRLINE) -> tk.Frame:
    return tk.Frame(parent, bg=color, height=1)


def card(parent, bg: str = SURFACE) -> tk.Frame:
    """A surface with a 1px hairline: the closest tk gets to Freebuff's cards."""
    return tk.Frame(parent, bg=bg, highlightbackground=HAIRLINE,
                    highlightthickness=1, bd=0)


def attach_hover(widget, normal: str, active: str) -> None:
    widget.configure(bg=normal)
    widget.bind("<Enter>", lambda _e: widget.configure(bg=active), add="+")
    widget.bind("<Leave>", lambda _e: widget.configure(bg=normal), add="+")


def button(parent, text: str, command, kind: str = "ghost", size: int = 10,
           weight: str = "normal", padx: int = 12, pady: int = 6,
           anchor: str = "center", **kw) -> tk.Button:
    """primary = the one orange action; ghost = surface button; bare = text only."""
    if kind == "primary":
        normal, fg, active, weight = ACCENT, ACCENT_INK, ACCENT_HOVER, "bold"
    elif kind == "danger":
        normal, fg, active = "#2a1620", BAD, "#3a1d29"
    elif kind == "bare":
        normal, fg, active = parent_bg(parent), DIM, SURFACE_2
    else:
        normal, fg, active = SURFACE_2, TEXT, SURFACE_3

    widget = tk.Button(parent, text=text, command=command, bg=normal, fg=fg,
                       activebackground=active, activeforeground=fg,
                       relief="flat", bd=0, highlightthickness=0, padx=padx,
                       pady=pady, font=ui(size, weight), cursor="hand2",
                       anchor=anchor, **kw)
    if kind != "primary":
        attach_hover(widget, normal, active)
    return widget


def chip(parent, text: str = "", tone: str = "dim") -> dict:
    """A pill: hairline border, dot, small label. Returns handles to update it."""
    frame = tk.Frame(parent, bg=SURFACE_2, highlightbackground=HAIRLINE,
                     highlightthickness=1, bd=0)
    dot = tk.Label(frame, text="\u25cf", bg=SURFACE_2, fg=TONES.get(tone, DIM),
                   font=ui(7))
    dot.pack(side="left", padx=(8, 5), pady=3)
    label_widget = tk.Label(frame, text=text, bg=SURFACE_2, fg=DIM,
                            font=ui(9), anchor="w")
    label_widget.pack(side="left", padx=(0, 9), pady=2)
    return {"frame": frame, "dot": dot, "label": label_widget}


def set_chip(handle: dict, text: str, tone: str = "dim") -> None:
    handle["label"].configure(text=text)
    handle["dot"].configure(fg=TONES.get(tone, DIM))


def scrollbar(parent, command):
    """A vertical scrollbar in shell colours.

    Tk's native Windows scrollbar ignores bg/troughcolor and paints a white
    strip down the transcript, which is the one thing that made the window read
    as "tkinter" rather than as a deliberate dark UI.
    """
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("CodeMode.Vertical.TScrollbar", background=SURFACE_3,
                    troughcolor=BG, bordercolor=BG, arrowcolor=DIM2,
                    darkcolor=SURFACE_3, lightcolor=SURFACE_3, relief="flat",
                    arrowsize=11)
    style.map("CodeMode.Vertical.TScrollbar",
              background=[("active", SURFACE_3), ("pressed", ACCENT)])
    return ttk.Scrollbar(parent, orient="vertical", command=command,
                         style="CodeMode.Vertical.TScrollbar")


class Segmented(tk.Frame):
    """Freebuff's mode switch: a hairline track with one filled segment."""

    def __init__(self, parent, options, value: str, on_change=None, size: int = 10):
        super().__init__(parent, bg=SURFACE_2, highlightbackground=HAIRLINE,
                         highlightthickness=1, bd=0)
        self.on_change = on_change
        self.buttons = {}
        for key, text in options:
            btn = tk.Button(self, text=text, command=lambda k=key: self.select(k, notify=True),
                            bg=SURFACE_2, fg=DIM, activebackground=SURFACE_3,
                            activeforeground=TEXT, relief="flat", bd=0,
                            highlightthickness=0, padx=14, pady=4,
                            font=ui(size, "bold"), cursor="hand2")
            btn.pack(side="left", padx=2, pady=2)
            self.buttons[key] = btn
        self.value = value
        self.select(value)

    def select(self, key: str, notify: bool = False) -> None:
        if key not in self.buttons:
            return
        self.value = key
        for name, btn in self.buttons.items():
            selected = name == key
            btn.configure(bg=ACCENT if selected else SURFACE_2,
                          fg=ACCENT_INK if selected else DIM)
        if notify and self.on_change:
            self.on_change(key)


class Meter(tk.Canvas):
    """A thin unlabelled bar: RAM headroom and context budget use the same shape."""

    def __init__(self, parent, width: int = 140, height: int = 5,
                 track: str = SURFACE_3, fill: str = ACCENT):
        super().__init__(parent, width=width, height=height,
                         bg=parent_bg(parent), highlightthickness=0, bd=0)
        self._width = width
        self._height = height
        self._track = track
        self._fill = fill
        self._value = 0.0
        self.bind("<Configure>", lambda _e: self.redraw())

    def set(self, value, color: str | None = None) -> None:
        self._value = max(0.0, min(1.0, float(value or 0)))
        if color:
            self._fill = color
        self.redraw()

    def redraw(self) -> None:
        width = self.winfo_width() or self._width
        self.delete("all")
        self.create_rectangle(0, 0, width, self._height, fill=self._track, outline="")
        if self._value > 0:
            self.create_rectangle(0, 0, max(2, int(width * self._value)),
                                  self._height, fill=self._fill, outline="")
