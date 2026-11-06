"""Offline speech to text, streamed into the composer.

Windows already ships a recogniser (System.Speech), so nothing is downloaded and
no audio leaves the machine. The old path ran the whole thing as one blocking
subprocess: you pressed Dictate, waited blind for up to 20 seconds, and only then
got one sentence - or an error - in the transcript.

This keeps one PowerShell child alive and turns every recognised phrase into a
line on its stdout, so text appears in the composer while you are still talking
and a second press stops it.
"""

from __future__ import annotations

import base64
import subprocess
import threading

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# One recogniser, looping until the parent stops us. Every phrase is flushed as
# its own line: Python reads it line by line and inserts it immediately.
SCRIPT = r"""
$ErrorActionPreference = 'Stop'
try { Add-Type -AssemblyName System.Speech } catch {
  [Console]::Error.WriteLine('Windows speech is not installed. Settings > Apps > Optional features > Speech.')
  exit 2
}
$engine = $null
try {
  $engine = New-Object System.Speech.Recognition.SpeechRecognitionEngine
  $engine.LoadGrammar((New-Object System.Speech.Recognition.DictationGrammar)) | Out-Null
  $engine.InitialSilenceTimeout = [TimeSpan]::FromSeconds(45)
  $engine.BabbleTimeout = [TimeSpan]::FromSeconds(45)
  $engine.EndSilenceTimeout = [TimeSpan]::FromMilliseconds(900)
  $engine.SetInputToDefaultAudioDevice()
} catch {
  [Console]::Error.WriteLine('mic/speech error: ' + $_.Exception.Message)
  exit 1
}
try {
  while ($true) {
    $result = $engine.Recognize([TimeSpan]::FromSeconds(6))
    if ($null -ne $result) {
      [Console]::Out.WriteLine($result.Text.Trim())
      [Console]::Out.Flush()
    }
  }
} catch {
  [Console]::Error.WriteLine('mic/speech error: ' + $_.Exception.Message)
  exit 1
} finally {
  if ($engine) { $engine.Dispose() }
}
"""

QUERY = (
    "[System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers()"
    " | ForEach-Object { $_.Culture.Name }"
)


def _encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _default_popen():
    return subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", _encoded(SCRIPT)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace", bufsize=1,
        creationflags=CREATE_NO_WINDOW,
    )


_CACHE = {"languages": None}


def installed_languages(refresh: bool = False, timeout: float = 12.0) -> list:
    """Which dictation languages Windows has available. Empty means none.

    A machine with no recogniser is the one case where the UI should say
    "install speech" rather than "speak now" and then fail. The answer is cached
    because querying it spawns PowerShell for about a second, and the window must
    not pay that on every refresh.
    """
    if _CACHE["languages"] is not None and not refresh:
        return list(_CACHE["languages"])
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", QUERY],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return []
    languages = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    _CACHE["languages"] = languages
    return list(languages)


class Dictation:
    """One listening session. Phrases go to on_text; failures to on_error."""

    def __init__(self, on_text, on_error, popen=None):
        self.on_text = on_text
        self.on_error = on_error
        self._popen = popen or _default_popen
        self._proc = None
        self._reader = None
        self._stopping = threading.Event()

    @property
    def running(self) -> bool:
        return self._proc is not None

    def start(self) -> bool:
        if self._proc is not None:
            return True
        try:
            self._proc = self._popen()
        except OSError as exc:
            self.on_error("could not start the speech engine: %s" % exc)
            return False
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        return True

    def _pump(self) -> None:
        proc = self._proc
        try:
            for line in proc.stdout:
                text = (line or "").strip()
                if text and not self._stopping.is_set():
                    self.on_text(text)
        except Exception as exc:  # noqa: BLE001 - reported, never raised into Tk
            if not self._stopping.is_set():
                self.on_error("speech reader stopped: %s" % exc)
        finally:
            stderr = ""
            try:
                stderr = (proc.stderr.read() or "").strip()
            except Exception:  # noqa: BLE001 - a dead pipe is not an error here
                pass
            code = proc.wait()
            self._proc = None
            if not self._stopping.is_set() and code != 0:
                tail = stderr.splitlines()[-1] if stderr else ""
                self.on_error(tail or "speech engine exited (%s)" % code)

    def stop(self) -> None:
        self._stopping.set()
        proc = self._proc
        if proc is None:
            return
        try:
            proc.terminate()
        except OSError:
            pass
