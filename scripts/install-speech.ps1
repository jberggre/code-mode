<#
    install-speech.ps1 - install the Windows speech recogniser System.Speech needs.

    This machine currently reports zero installed recognisers, so dictation can
    only fail until the Windows speech feature exists. Adding a capability needs
    administrator rights, so the app launches this with -Verb RunAs and you approve
    one UAC prompt.

    Usage:
        powershell -ExecutionPolicy Bypass -File scripts\install-speech.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'

try {
    $installed = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers()
} catch {
    $installed = @()
}
if ($installed -and $installed.Count -gt 0) {
    $names = ($installed | ForEach-Object { $_.Culture.Name }) -join ', '
    Write-Output "already installed: $names"
    exit 0
}

try {
    $capability = Get-WindowsCapability -Online |
        Where-Object { $_.Name -like 'Language.Speech*' } |
        Select-Object -First 1
} catch {
    Write-Output "could not query Windows capabilities: $($_.Exception.Message)"
    exit 1
}

if (-not $capability) {
    Write-Output "this Windows build ships no Language.Speech capability."
    Write-Output "Install a speech language: Settings > Time & language > Speech."
    exit 2
}

if ($capability.State -eq 'Installed') {
    Write-Output "$($capability.Name) is already installed but no recogniser reported."
    exit 3
}

Write-Output "installing $($capability.Name) - this can take a few minutes..."
Add-WindowsCapability -Online -Name $capability.Name | Out-Null

try {
    $after = [System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers()
    $names = ($after | ForEach-Object { $_.Culture.Name }) -join ', '
    Write-Output "done: $names"
} catch {
    Write-Output "installed, but the engine still reports nothing. Reboot once, then retry."
}
