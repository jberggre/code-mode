import sys, os, subprocess, time

sys.path.insert(0, os.path.join(os.environ.get("HOME", "."), "CodeMode", "app"))

# Start CLI mode
proc = subprocess.Popen(
    [sys.executable, "app/ui.py", "--cli"],
    cwd=r"C:\Users\james\Downloads\CodeMode",
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    env={**os.environ, "CODEMODE_MODEL": "qwen2.5-coder:3b"},
)

print(f"Process started, PID: {proc.pid}")
time.sleep(2)

# Send help command
try:
    proc.stdin.write(b"help\n")
    proc.stdin.flush()
    time.sleep(1)
    # Read output
    output = proc.stdout.read1(8192)
    print(f"CLI output:\n{output}")
except Exception as e:
    print(f"Error sending command: {e}")

# Send a few more commands
time.sleep(1)
try:
    proc.stdin.write(b"new\n")
    proc.stdin.flush()
    time.sleep(1)
    output2 = proc.stdout.read1(8192)
    print(f"After 'new':\n{output2}")
except Exception as e:
    print(f"Error: {e}")

time.sleep(1)
try:
    proc.stdin.write(b"skills\n")
    proc.stdin.flush()
    time.sleep(1)
    output3 = proc.stdout.read1(8192)
    print(f"Skills:\n{output3}")
except Exception as e:
    print(f"Error: {e}")

time.sleep(1)
try:
    proc.stdin.write(b"mode code\n")
    proc.stdin.flush()
    time.sleep(1)
    output4 = proc.stdout.read1(8192)
    print(f"Mode code:\n{output4}")
except Exception as e:
    print(f"Error: {e}")

# Exit
time.sleep(1)
try:
    proc.stdin.write(b"exit\n")
    proc.stdin.flush()
    proc.wait(timeout=5)
    print("Process exited")
except Exception as e:
    print(f"Exit error: {e}")
    proc.kill()

print("CLI test complete!")