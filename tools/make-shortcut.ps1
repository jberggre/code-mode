param(
    [string]$Icon = '',
    [string]$Name = 'Code Mode',
    [string]$Source = 'app/ui.py'
)
# Creates (or refreshes) a desktop shortcut that launches the Tk window with no
# console window, using the generated .ico as its thumbnail.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not $Icon) { $Icon = Join-Path $root 'assets\codemode.ico' }
$Icon = (Resolve-Path $Icon).Path
$desktop = [Environment]::GetFolderPath('Desktop')
if (-not $desktop) { throw 'could not find the Desktop folder' }

$candidates = @(
    (Join-Path (Split-Path -Parent (Get-Command python -ErrorAction SilentlyContinue).Source) 'pythonw.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\pythonw.exe')
) | Where-Object { $_ -and (Test-Path $_) }
$pythonw = $candidates | Select-Object -First 1
if (-not $pythonw) { throw 'pythonw.exe not found next to python on PATH' }

$target = (Resolve-Path (Join-Path $root $Source)).Path
$link = Join-Path $desktop "$Name.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"' + $target + '"'
$shortcut.WorkingDirectory = $root
$shortcut.IconLocation = $Icon + ',0'
$shortcut.Description = 'Code Mode - local coding agent'
$shortcut.WindowStyle = 1
$shortcut.Save()
$shell = $null

$check = (New-Object -ComObject WScript.Shell).CreateShortcut($link)
Write-Output ('shortcut:    ' + $link)
Write-Output ('target:      ' + $check.TargetPath)
Write-Output ('arguments:   ' + $check.Arguments)
Write-Output ('workingdir:  ' + $check.WorkingDirectory)
Write-Output ('icon:        ' + $check.IconLocation)
Write-Output ('exists:      ' + (Test-Path $link))
