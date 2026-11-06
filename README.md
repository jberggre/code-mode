# CodeMode

A local, offline coding interface for this machine — an **ASUS ROG Xbox Ally
(RC73YA)**: Ryzen Z2 A (4C/8T), 16 GB LPDDR5X-6400 shared with the Radeon iGPU,
Windows 11 Home 26H2.

It has one toggle that matters: **Chat** vs **Code**. Code mode is not cosmetic —
it swaps the system prompt, tightens sampling, doubles the context budget and
trims history to fit the RAM you actually have.

Nothing here installs services, requires Node, or touches Xbox / Game Bar /
Armoury Crate.

```
app/ui.py         the desktop app: Freebuff-shaped shell, no server, no browser
app/theme.py      palette + widget system (one orange accent on deep navy)
app/panels.py     the right rail: real terminal + session/RAM controls
app/session_store.py  atomic chat persistence, separate from the Code Mode file
app/server.py     browser fallback: serves index.html, proxies chat, streams tokens
app/index.html    the browser interface (dark, touch + keyboard friendly)
scripts/debloat.ps1    reviewable permanent debloat (dry run by default)
scripts/code-mode.ps1  free RAM for a coding session, restore it after
start-codemode.cmd     double-click launcher
PLAN.md           the measurements, the tradeoffs, and what comes next
```

## 1. Install a model runtime (pick one)

You currently have neither. Both are detected automatically; you can install both.

**Ollama** — smallest footprint, one command per model:

```powershell
# portable: no admin, no Windows service, no autostart entry (this is what is installed here)
curl -L -o tools\ollama.zip https://github.com/ollama/ollama/releases/latest/download/ollama-windows-amd64.zip
powershell -Command "Expand-Archive tools\ollama.zip tools\ollama"
tools\ollama\ollama.exe serve
tools\ollama\ollama.exe pull qwen2.5-coder:3b

# or the system-wide install
winget install Ollama.Ollama
```

**LM Studio** — easier tuning, Vulkan offload to the Radeon iGPU:

```powershell
winget install ElementLabs.LMStudio
```

Then in LM Studio: load a coder model, open **Developer → Local Server**, start it
on port `1234`.

Sizes that fit in 16 GB shared RAM with Windows still alive:

| Model | Download | Notes |
| --- | --- | --- |
| `qwen2.5-coder:1.5b` | ~1.0 GB | fastest; single-file edits |
| `qwen2.5-coder:3b` | ~1.9 GB | the sweet spot here |
| `qwen2.5-coder:7b` | ~4.7 GB | slow on 4 cores; needs UMA at 1–2 GB |

## 2. Run it

Double-click **`start-codemode.cmd`**, or:

```powershell
python app\ui.py            # native window, no browser, no server
python app\ui.py --selftest # build the window, check the layout, print JSON, exit
python app\ui.py --smoke    # one real prompt through the selected model, no window
python app\ui.py --no-shell # start with shell access and terminal Run off
```

The desktop window is the default because the interface must not compete with
the model for memory. It has no HTTP server and no port: it talks to Ollama or
LM Studio directly, and shows its own footprint next to free RAM.

Its shape follows Freebuff: a workspace rail on the left, the transcript with
the composer underneath it, and a terminal/session rail on the right. The header
holds the Chat/Code switch, a model picker that fills in from whichever runtime
answers, and one status chip. The right rail has two tabs: **Terminal**, a real
PowerShell that refuses when shell access is off, and **Session**, with the RAM
meter, model, Trim/Unload, Code Mode session, handoff and GPU profile controls.
Above the composer a context meter shows history against the 8k budget, so
compaction is visible before it happens.

**Mic** in the composer starts offline dictation with Windows' own recogniser:
every phrase is inserted while you are still speaking, and pressing Mic again
stops it. If the speech feature is not installed, the app says so instead of
pretending to listen.

Code mode is an agent, not a chat wrapper. The model gets file, search and shell
tools, writes the files it is talking about, runs them, and only then reports. If
it answers with a tutorial instead of calling a tool, the app sends the reply
back once with one instruction: do the work now.

If Ollama is staged but stopped, **Session → Start local runtime** launches
`tools\ollama\ollama.exe serve`; the two pulled coder models appear on their own.

A browser front end still exists if you want it — `start-web-ui.cmd`, then
<http://127.0.0.1:8765/>. It shares the same `MODES` table, but a Chromium tab
costs hundreds of MB where the Tk window costs tens, so it is the fallback.

Keyboard: **Enter** sends, **Shift+Enter** newlines, **Ctrl+L** starts a new chat,
**Ctrl+J** collapses the right rail.

Built for a 7-inch touchscreen: 11 pt transcript, a composer that grows to seven
lines, and a window that opens maximised inside the work area so the composer is
never below the screen edge.

**Dictate** runs on Windows' own speech engine (`app/speech.py`) — offline, no
model download. One PowerShell child stays alive for the whole session and every
phrase lands in the composer as you pause, so it keeps listening until you press
Mic again. It is dictation-grade: fine for "add a null check before the parse",
not for dictating identifier names. `scripts\dictate.ps1` is the one-shot version
for a terminal. If Windows genuinely has no recogniser, the app says so and
offers to install it — a probe that merely fails never claims speech is missing.

Options (environment variables):

| Variable | Default | Meaning |
| --- | --- | --- |
| `CODEMODE_PORT` | `8765` | port to serve on (loopback only) |
| `CODEMODE_KEEP_ALIVE` | `5m` | how long Ollama holds the model in RAM after a reply |
| `CODEMODE_MODEL` | unset | pre-select a model by name in the desktop app |
| `CODEMODE_NO_BROWSER` | unset | web UI only: set to `1` to skip opening the browser |
| `OLLAMA_BASE` | `http://127.0.0.1:11434` | Ollama address |
| `LMS_BASE` | `http://127.0.0.1:1234` | LM Studio address |
| `LMS_API_KEY` | unset | only if your LM Studio server requires a key |

## 3. Debloat (optional, permanent, reviewable)

Audit first — it changes nothing and prints every action:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\debloat.ps1
```

Commit it in an **elevated** PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\debloat.ps1 -Apply
powershell -ExecutionPolicy Bypass -File scripts\debloat.ps1 -Apply -Aggressive
```

Every run writes a backup to `%USERPROFILE%\CodeMode\debloat-backups\<timestamp>\`
(AppX list, service start types, Run-key values, active power scheme). Autostart
entries can be restored with `-RestoreStartup -Apply`. Disabling *launcher*
autostart (`-Aggressive`) is safe for updates: use the **Updates** panel to start
the launcher when you want one to pull game patches.

**Guaranteed untouched**: Xbox app, GamingServices, Game Bar, Xbl* services,
Microsoft Store, App Installer, Armoury Crate SE, Command Center, all ASUS
services, AMD graphics, audio runtimes. The script skips any match on those by
name, even if a removal pattern would otherwise hit it.

## 4. Updates without autostart

The browser UI's **Updates** panel replaces launcher autostart (the desktop shell deliberately keeps only Terminal and Session). Steam, Epic,
Battle.net and the Microsoft Store all update games *when they run*, so starting
them at login only moves the check earlier — it is not what keeps games current.

| Source | What the button really does |
| --- | --- |
| **Windows apps** (winget) | Real CLI. **Scan** runs `winget upgrade`, **Update all** runs `winget upgrade --all --silent`. |
| **Xbox / Game Pass** | Lists `C:\XboxGames`; opens the Store updates page. MSIX games have no headless update API. |
| **Steam** | Lists installed apps from the `appmanifest` files with last-update dates; opens Steam. |
| **Epic** | Reads `C:\ProgramData\Epic\...\Manifests\*.item`; opens the launcher. |
| **Battle.net** | Detects the launcher; opens it. |

No storefront exposes a supported headless "update everything" call, so four of
the five rows open the launcher instead of pretending to drive it. The winget
row is fully automated. Nothing stays resident after you close a launcher.

## 5. Free RAM for a coding session

```powershell
powershell -ExecutionPolicy Bypass -File scripts\code-mode.ps1            # status
powershell -ExecutionPolicy Bypass -File scripts\code-mode.ps1 -Mode code
powershell -ExecutionPolicy Bypass -File scripts\code-mode.ps1 -Mode gaming
```

Also available as the **Trim system for Code Mode** button in the sidebar.

In the desktop app both live in the right rail's **Session** tab: Trim runs the
script below, Unload drops the model from RAM immediately instead of waiting for
Ollama's keep-alive to expire.

`code` stops OneDrive and idle game launchers, turns off transparency and window
animations, and records what it changed. `gaming` puts it all back. Power plans
are left alone by default because Armoury Crate owns TDP on this device — pass
`-SetPowerPlan Performance` if you want it anyway.

## 6. Code Mode session (the ⚡ button)

**Session → Code Mode session** (also in the left rail) suspends everything
that is not needed to code, and one click puts it back. **It suspends, it does not kill** — a resume restores the same process with
its state, so nothing is lost and nothing is uninstalled.

What it pauses: browsers, OneDrive/Dropbox/Drive sync, Steam / Epic / Battle.net /
Riot launchers, Teams / Discord / Slack / Spotify, Game Bar, Widgets, Phone Link.
It also empties their working sets, stops `DiagTrack`, `WSearch`, `SysMain`,
`Spooler` and friends, and flattens the visual effects.

What it never touches: `svchost`, `lsass`, `csrss`, `winlogon`, `dwm`, `explorer`,
Defender, the audio stack, and anything Xbox, GamingServices, Armoury Crate, ASUS
or AMD — so the full-screen experience and your controller keep working.

```powershell
.\scripts\code-mode.ps1                          # what is eating RAM, is a session live
.\scripts\code-mode.ps1 -Mode code -DryRun       # show the plan, change nothing
.\scripts\code-mode.ps1 -Mode code               # enter (as admin to stop services)
.\scripts\code-mode.ps1 -Mode gaming             # leave, restore everything
```

> **It cannot free the GPU carve-out.** That is Armoury Crate → GPU memory = 1G,
> then reboot. Processes and services give back roughly 1–2.5 GB; the framebuffer
> is a separate ~3 GB you can only get by lowering it.

### Measured, not promised

A real session on this machine: **8 processes paused, 513 MB of working set named,
54 MB actually returned as free RAM.** That gap is the whole story — suspending a
process moves its pages to the standby list, it does not release them. Windows
still counts them as cache it can reclaim under pressure, so a model loading will
push them out, but "free RAM" barely moves and you should not expect otherwise.

Three things actually move the needle:

1. **`-Mode code -Kill`** closes the apps instead of pausing them. That returns
   real memory immediately, at the cost of the app's state (and `gaming` cannot
   bring those back).
2. **Run it elevated.** Admin adds the standby purge (the RAMMap "empty standby
   list" trick, via `NtSetSystemInformation`) plus stopping `DiagTrack`, `WSearch`,
   `SysMain` and `Spooler`. Without admin both are skipped.
3. **Armoury Crate → GPU memory = 1G, reboot.** This is the big one: it hands back
   the framebuffer reservation, and no userspace trick can touch it.

Realistic budget for a model: **1–2.5 GB** from processes and services, plus
**~5 GB** if you drop the GPU carve-out (measured: the GPU currently holds 6 GB
of the 16 GB, Windows sees 9.7 GB; at 1G it would see ~14.5 GB). That is what
decides 3B versus 7B here.

If the app is force-killed mid-session, restore with the `-Mode gaming` command —
the state lives in `%LOCALAPPDATA%\CodeMode\code-mode-session.json`, deliberately
separate from your chat history.

## 7. Profile switch with restart (the two buttons)

**GPU profile + restart** (left rail or Session tab) opens both directions of the trade: one click
stages the profile you want, opens Armoury Crate at the GPU setting, and restarts
with a 25-second cancellable countdown. When the machine comes back up, CodeMode
sees the staged profile and enters the Code session on its own.

```powershell
.\scripts\gpu-mode.ps1                        # report only: split, visible RAM, verdict
.\scripts\gpu-mode.ps1 -Mode code             # stage + open Armoury + restart
.\scripts\gpu-mode.ps1 -Mode code -NoReboot   # stage only
.\scripts\gpu-mode.ps1 -Mode cancel           # abort a pending restart
```

### What it can and cannot do

It **cannot** write the GPU split. That value is applied at boot and ASUS ships no
documented interface for it; the script lists any plausible config store it finds
and deliberately never writes one, because poking an undocumented firmware setting
on a handheld is how you get a device that will not come back up.

What it removes is the *forgetting*: stage, prompt, restart, resume — one button
each way. You still pick 1G or 6G in Armoury Crate.

## 8. Tools and the Superpowers standard

Every system prompt is built from three parts: the **Superpowers rules and skill
index**, the mode prompt, then the tool contract. That means the model checks
skills before answering in every session, not only when you remember to ask.

```
skills/superpowers/skills/*/SKILL.md     15 skills, cloned from the upstream repo
app/skills.py                            discovery, prompt index, read_skill
app/tools.py                             the tools themselves
app/web.py                               fetch + search, HTML stripped in Python
app/agent.py                             model -> tool -> result -> model loop
```

The model calls tools by emitting one strict block:

```
<tool>{"name": "run_command", "args": {"command": "python -m py_compile app/ui.py"}}</tool>
```

| Tool | What it does |
| --- | --- |
| `read_file` | numbered lines, so it can quote and patch precisely |
| `write_file` | whole-file writes inside the workspace |
| `list_dir` | directory listing |
| `search_code` | regex across the workspace |
| `run_command` | **real PowerShell**, cwd = workspace, output fed back |
| `read_skill` | loads a skill body, or one resource file inside it |
| `fetch_url` | fetches a page and returns readable text, markup stripped |
| `web_search` | DuckDuckGo results as titles + urls, no API key |

### The internet question

`run_command` already reaches the network - the shell is a real shell - so `curl`
works. But a web page is 50-150 KB of markup, which does not fit 8192 tokens and
which a 3B model cannot reliably read. So fetching is done in Python and the model
gets a few KB of prose instead. `web_search` uses DuckDuckGo's HTML endpoint: no
key, no account, no quota to manage. It can be blocked or rate-limited, in which
case the tool says so instead of pretending it searched.

One-off fix worth doing: `python -m pip install --user certifi`. This Python has
OpenSSL with no CA bundle of its own, so a handful of hosts fail verification.
`fetch_url` tries the Windows store first and certifi second, so with certifi
present those hosts start working and nothing else changes.

Search results and page text are **data, not instructions**. A web page is exactly
the place a prompt injection would come from, and the tool help tells the model to
report what a page says rather than obey it. Combined with shell access, a
sufficiently unlucky page could still get the model to run something - another
reason the shell toggle exists.

Up to 5 tool steps per message, then it must answer. Toggle with **⋯ → Toggle
agent tools** and **⋯ → Toggle shell access**.

### Safety, stated plainly

The workspace boundary is enforced: every path is resolved and refused if it
escapes the project folder. Shell commands are time-limited and checked against a
short destructive list (disk formatting, `diskpart`, `bcdedit`, power commands).

That is a **speed bump, not a sandbox**. A command the model writes can still do
damage you did not intend, because it is running as you, unsandboxed, on your real
machine. Turn shell access off for sessions where you do not want that risk.

## 9. Surviving the context limit

A 7B model at 8192 tokens forgets the top of a conversation after three files
read through tools. Old behaviour was worse than forgetting: `trim_messages`
silently dropped the oldest turns. Now:

- **Compaction at 72%.** When history passes ~72% of the context budget the
  oldest turns are summarised by the model into a dense note, that note becomes
  the first turn, and the last two turns stay verbatim.
- **Nothing is deleted.** The full transcript is written to
  `state/transcripts/` before anything is summarised away.
- **Handoff.** Every compaction writes `state/handoff.md`: Goal, Done, In
  progress, Next step, Files and commands, Gotchas.
- **Next boot resumes.** While the handoff is fresh (< 7 days) it is injected
  into the system prompt above the mode prompt, so a new window continues the
  work instead of starting over. Boot also shows it in the transcript.
- **Mid-run too.** The agent loop checks the budget before every model call, so
  a long tool session compacts in the middle rather than blowing up.

```
app/memory.py            budget maths, archiving, summarising, handoff
state/handoff.md         what the next session is told
state/transcripts/*.md   full transcripts, never trimmed
```

Buttons: **Compact + handoff** in the left rail and **Session → Compact + write
handoff**. Clearing the chat archives the transcript and clears the handoff,
because "new session" should mean new. If no model is reachable for the summary, a mechanical digest of
 the last turns is used instead - losing polish beats losing the work.

## Layout on a 7-inch screen

The sidebar collapses to icons under 820 px, the composer grows with your text,
and Enter sends / Shift+Enter adds a line. Nothing depends on hover.
