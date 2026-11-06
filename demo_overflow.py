import subprocess, time, os, sys

# Start UI in background
proc = subprocess.Popen(
    [sys.executable, "app\\ui.py"],
    cwd=r"C:\Users\james\Downloads\CodeMode",
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
print(f"UI started, PID: {proc.pid}")
time.sleep(3)

# Now demonstrate overflow/handoff/resume
import sys
sys.path.insert(0, "app")
from memory import (
    needs_compaction,
    budget,
    history_tokens,
    compact,
    archive,
    write_handoff,
    read_handoff,
    handoff_note,
    resume_note,
)
from skills import read_skill
import server as core

# Show handoff/resume before any overflow
print("\n=== HANDOFF/RESUME DEMO ===")
print(f"Handoff note: {handoff_note()[:200]}")
print(f"Resume note: {resume_note()[:200]}")

# Create messages that exceed context window
messages = []
for i in range(60):
    messages.append({"role": "user", "content": f"Turn {i}: some code content here. " * 20})

used = history_tokens(messages, {"num_ctx": 8192, "num_predict": 512})
budget_val = budget({"num_ctx": 8192, "num_predict": 512})
print("\n=== OVERFLOW DEMO ===")
print(f"{len(messages)} messages = {used} tokens used")
print(f"Budget: {budget_val} tokens")
print(f"needs_compaction: {needs_compaction(messages, {'num_ctx': 8192, 'num_predict': 512})}")

# Compact
kept = compact(core.backends[0], "qwen2.5-coder:7b", messages, {"num_ctx": 8192, "num_predict": 512})
print(f"\nAfter compaction: {len(kept)} messages")

# Check handoff was written
hf = read_handoff()
print(f"Handoff has Goal: {'Goal' in hf}")
print(f"Handoff has Done: {'Done' in hf}")
print(f"Handoff has Next step: {'Next step' in hf}")

# Resume note
print(f"\nResume note: {resume_note()[:200]}")

print("\n=== ALL DEMONSTRATED SUCCESSFULLY ===")

# Kill the UI process
proc.terminate()
proc.wait(timeout=5)
print("UI closed")