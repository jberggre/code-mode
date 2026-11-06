import os
import subprocess
import sys

def run_powershell(code):
    """Run PowerShell code and return output."""
    result = subprocess.run(
        ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', code],
        capture_output=True,
        text=True,
        timeout=10
    )
    return result

desktop = os.path.expanduser('~\Desktop')
target = 'C:\Program Files\Python311\pythonw.exe'
args = '-m app.ui'
workdir = 'C:\Users\james\Downloads\CodeMode'
desc = 'CodeMode AI Assistant'

# We'll generate PowerShell code and run it
ps_code = f'''
$path = Join-Path ([Environment]::GetFolderPath('Desktop')) 'CodeMode.lnk'
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($path)
$lnk.TargetPath = '{target}'
$lnk.Arguments = '{args}'
$lnk.WorkingDirectory = '{workdir}'
$lnk.Description = '{desc}'
$lnk.Save()
"Created: " + $path
'''

result = run_powershell(ps_code)
print(result.stdout)
print('Return code:', result.returncode)
