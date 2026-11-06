# CodeMode — plan and measurements

## What the machine actually is

Measured on this device, not assumed:

| | Value |
| --- | --- |
| Model | ASUS ROG Xbox Ally `RC73YA` (the 2025 Xbox-branded Ally, **not** an Ally X) |
| APU | AMD Ryzen **Z2 A**, 4 cores / 8 threads, 2.8 GHz base |
| GPU | Radeon integrated (RDNA 2), driver 32.0.21045.11001 |
| RAM | 16 GB LPDDR5X-6400 (4 × 4 GB), **9.7 GB visible** to Windows |
| RAM free at rest | **1.7 GB** |
| OS | Windows 11 Home 26H2, build 26300 |
| Storage | 1.8 TB C: with 1.48 TB free |
| Services / AppX | 141 running / 156 packages |
| Autostart | OneDrive, Edge, Battle.net, Epic Games Launcher |
| Games | Xbox/Game Pass: Fallout 4, Fortnite, Hades, Hollow Knight: Silksong, The Long Dark (+2 GUID titles under `C:\XboxGames`); Steam library effectively empty |

The attached guide describes a **Z1 Extreme / 6 GB-default-UMA** Ally. That is a
different APU. Consequences:

- **4C/8T, not 8C/16T.** Prompt processing (reading your pasted code) will be the
  slow half of every request, not just token output. Keep prompts lean.
- **~6 GB is already gone to GPU + hardware reserve**, so "set UMA to 1G and get
  14 GB" is optimistic here; the realistic ceiling after a UMA change is ~12–13 GB
  visible, and it costs game performance.
- The guide's Code Mode stops `XblAuthManager`, `XblGameSave`, `XboxNetApiSvc`,
  `XboxGipSvc`. On this machine those are **already Stopped/Manual** — stopping
  them again buys nothing and risks breaking the Xbox full-screen experience you
  use constantly. So `scripts/code-mode.ps1` does not touch them at all.

## Three deliverables

### 1. Debloat — permanent, safe, reviewable (`scripts/debloat.ps1`)

Tiers, because "permanent" and "gaming safe" pull in opposite directions:

- **Core** (safe, permanent): consumer bloat AppX removed *and* deprovisioned
  (Candy Crush, Solitaire, Bing News/Weather/Sports/Finance, Get Help, Tips,
  Phone Link, Feedback Hub, Paint 3D, Office/OneNote trial hubs, Mail & Calendar,
  Skype, People, Todos, Maps, Cortana, Outlook for Windows), plus telemetry
  services (`DiagTrack`, `dmwappushservice`, `RemoteRegistry`), plus OneDrive and
  Edge autostart.
- **Aggressive** (opt-in): SysMain, WSearch, Spooler, Fax; Clipchamp, Teams,
  Sticky Notes; game-launcher autostart.

Every mutation is preceded by a JSON backup of the AppX list, service start
types, Run-key values and the active power scheme. Autostart is fully reversible
(`-RestoreStartup -Apply`); removed AppX can be reinstalled from the Store.

Hard-coded protection list: anything matching Xbox, GamingServices, Game Bar,
GameInput, Microsoft Store, App Installer, VCLibs/UI.Xaml/NET native,
WindowsAppRuntime, Photos, Camera, classic Paint, Snipping Tool, Notepad,
Terminal, ASUS, Armoury Crate, AMD, Realtek, Dolby, Waves, DTS.

Not automated on purpose: pulling the 156 stock packages further (Store runtime
dependencies break game installs), scheduled-task surgery, and registry "tweak"
packs — all high risk, low reward on a handheld that must keep accepting Game
Pass installs and driver updates.

Autostart vs updates: the owner relies on launcher autostart to keep games
patched. That is not actually how patching works — Steam, Epic, Battle.net and
the Store patch when they run, not because they started at login. So the plan is
an on-demand **Updates** panel (winget for real, deep links/launchers for the four
storefronts that have no headless API) instead of leaving four processes resident
from boot. Measured waste at rest before the change: Edge 504 MB across 7
processes, Battle.net 218 MB, OneDrive 90 MB, Epic 86 MB.

### 2. The interface (`app/`)

A native Tkinter window (`app/ui.py`) is the default — not a browser tab, not a TUI.
Two reasons: a Chromium tab costs hundreds of MB on a machine where free RAM is
the binding constraint, and a 7-inch handheld has a touchscreen and a controller
but no terminal muscle memory. Everything is Python 3.11 stdlib, the only runtime
already installed (no Node, no pip).

The browser UI (`app/server.py`) is kept as a fallback and as the development
surface. Both front ends import the same `MODES` table, so the Chat/Code toggle
cannot diverge between them.

Measured on this unit (`python app/ui.py --selftest`, idle, no model loaded):
**37.8 MB** working set for the whole desktop UI on Tk 8.6. For reference, Edge
was holding 423 MB across 7 processes at the same moment — that figure includes
the preview tab, so it is not a pure like-for-like, but the order of magnitude is
the point. Budget freed by leaving the browser behind: roughly **350–400 MB**,
the difference between a 3B model loading comfortably and paging.

```
desktop ui.py  <--in-process-->  server module  <--HTTP-->  Ollama :11434 / LM Studio :1234
browser        <--SSE-->         server.py       (fallback path)
```

- Backends auto-detect; model list populates from whichever answers.
- Streaming, abortable mid-generation, with chars / seconds / estimated tok/s.
- Conversations persist in `localStorage`; no cloud, no telemetry.

**What the Chat/Code toggle actually changes** (single source of truth in
`MODES`, served to the UI so the two can't drift):

| | Chat | Code |
| --- | --- | --- |
| System prompt | concise handheld assistant | terse senior engineer, no preamble, complete functions, "Node is not installed" |
| Temperature / top_p | 0.7 / 0.95 | 0.1 / 0.9 |
| Context (`num_ctx`) | 4096 | 8192 |
| Max output | 1024 | 2048 |
| History | kept | trimmed to fit the 8k budget, newest first |

That trimming is the part that matters on this box: at 7 B with 8k context the
KV cache alone is several hundred MB, and Windows only has 1.7 GB spare before
you start.

### 3. OS side of Code Mode (`scripts/code-mode.ps1` + sidebar button)

A session, not a trim. `code` **suspends** (NtSuspendProcess, never kills) every
background app that has no role in coding, empties each working set
(EmptyWorkingSet), stops non-critical services, flattens visual effects and
records the lot to `code-mode-session.json`; `gaming` resumes those exact PIDs,
restarts the services and restores the registry values.

Measured on this unit, entering and leaving a session for real: **8 processes
paused, 513 MB of working set, 54 MB of free RAM returned.** The gap is not a bug
and not fixable in userspace — `NtSuspendProcess` + `EmptyWorkingSet` moves pages
to the standby list; only the standby purge (admin) or terminating the process
converts that into free pages. So the honest model of this feature is:

| Lever | Realistic return | Cost |
| --- | --- | --- |
| Suspend background apps | ~0.05–0.3 GB free; more usable under pressure | none, fully reversible |
| `-Kill` instead of suspend | 0.5–1.5 GB | app state lost, not restorable |
| Elevated: standby purge + service stop | +1–2 GB | admin prompt, brief slowdown |
| Armoury Crate GPU memory 1G + reboot | **+~5 GB** (6G -> 1G) | fewer frames in games until reverted |

Switching between the two shapes is orchestrated by `gpu-mode.ps1`: it stages the
profile, opens Armoury Crate at the setting, restarts with a cancellable
countdown, and the app finishes the job on next boot by consuming the staged
profile and entering the session. The firmware value itself stays a manual click -
ASUS documents no write path, and blind-invoking a vendor WMI method to change
display memory is not a risk worth taking on a handheld.

Nothing here reaches a 7B model's comfort zone without the last two rows. That is
the real answer to "can a button shut everything off": it can shut everything
*off*, but Windows does not hand the memory back the way task-killing an app does.

Safety properties that matter more than the number:
- A second session is refused while one is recorded, so nothing gets orphaned.
- Suspension is reversible and survives the app being killed: the state file is
  separate from the UI's chat history (they collided once; that is now split).
- `-DryRun` prints the full plan and touches nothing.
- The always-denied list (`svchost`, `lsass`, `csrss`, `winlogon`, `dwm`,
  `explorer`, Defender, audio) plus the Xbox/Armoury/ASUS/AMD vendor filter is
  re-checked per process, not assumed from the target list.
Never touched: Xbox services, Game Bar, Armoury Crate/Command Center, ASUS
services, AMD graphics, power plan (Armoury owns TDP; opt in with
`-SetPowerPlan`).

The real RAM lever remains manual: **Armoury Crate SE → GPU memory = 1G** for a
coding session (reboot required). Worth it for 7 B class models; not worth it
permanently, because it costs frames in every game.

## Honest expectations

No speed numbers are claimed here — nothing has been measured on this unit yet,
and there is no runtime installed. What follows is sizing logic, not benchmarks:

- 3 B Q4_K_M (~2 GB weights) leaves roughly 7 GB for Windows, the browser and
  the model's KV cache. Expect usable, not fast, on 4 cores.
- 7 B Q4_K_M (~4.7 GB weights) is the ceiling; it needs the trim, an 8k context
  cap, and ideally a UMA change. Token output will be memory-bandwidth bound.
- The iGPU is worth trying (LM Studio's Vulkan runtime, or Ollama's Vulkan
  backend), but on a 4-core APU with shared bandwidth the win is usually smaller
  than expected, and Ollama has had documented 780M-class Vulkan regressions.
  Measure before believing: same prompt, both runtimes, compare tok/s.

## Phases

**Done now** — v1 interface with a real Chat/Code toggle, streaming, persistence,
backend autodetect; debloat + OS-mode scripts with backups and a protection list;
this document.

**Recovered 2026-11-06** — the desktop window had been left half-rewritten: no
model was ever selected (so it refused to send), `_save_session` was called but
never defined (the first reply raised inside the Tk `after()` callback and froze
the event loop), the composer sat in a horizontal pane, six sidebar buttons had
no command, and a test handoff sentence was injected into every system prompt.
It is now a three-column Freebuff-shaped shell: `app/theme.py` (palette and
widget system), `app/panels.py` (real terminal, session/RAM rail),
`app/session_store.py` (atomic chat persistence), and `--selftest` / `--smoke`
checks that assert the layout, the model choice, and a real token round trip.

**Built now** — context survival: compaction at 72% of the window, full transcript
archived to state/transcripts/, handoff written to state/handoff.md and injected
into the next session's system prompt so work continues instead of restarting.

**Also built** — agentic tools (read/write/patch files in the workspace
folder, run PowerShell and feed output back), which turns this from a chat box
into something closer to the app you were looking at; a file/folder attach for
context; a per-model profile file so 1.5 B vs 7 B get different budgets.

**Later** — controller bindings (Armoury Crate maps M1/M2 to keystrokes, which
can focus the composer or fire "new chat"); voice input; a small benchmark screen
so model choice stops being guesswork.

## Open questions for you

1. Ollama or LM Studio first? (Ollama: one command, CPU-first. LM Studio: GUI,
   Vulkan offload, easier to compare models.)
2. Is a 1 G UMA switch acceptable for coding sessions, i.e. are you willing to
   reboot between "code" and "game" for ~3 GB more model headroom?
3. Do you want the agent to touch real files on this machine, or stay a chat?
   That decision sets the whole security model of phase 2.
