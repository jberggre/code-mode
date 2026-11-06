<#
    gpu-mode.ps1 - switch this handheld between a Code profile and a Gaming profile.

    Honest scope: the GPU memory split on this ASUS handheld is a platform setting
    applied at boot. There is no documented CLI for it, and this script will not
    blind-invoke vendor WMI methods to poke firmware - on a handheld that is how
    you end up with a device that will not display. What it does instead:

        1. stages the profile, so CodeMode applies its session on the next boot
        2. reports the split it measured and the numbers each profile would give
        3. opens Armoury Crate at the settings app when it cannot write the value
        4. restarts with a visible countdown you can cancel

    Usage:
        .\gpu-mode.ps1                        report only
        .\gpu-mode.ps1 -Mode code             stage code profile, restart in 25s
        .\gpu-mode.ps1 -Mode code -NoReboot   stage only, no restart
        .\gpu-mode.ps1 -Mode gaming           stage gaming profile, restart
        .\gpu-mode.ps1 -Mode cancel           abort a pending restart
#>
[CmdletBinding()]
param(
    [ValidateSet('status', 'code', 'gaming', 'cancel')]
    [string]$Mode = 'status',
    [int]$Delay = 25,
    [switch]$NoReboot,
    [switch]$NoLaunch,
    [int]$CodeGB = 1,
    [int]$GamingGB = 6
)

$ErrorActionPreference = 'SilentlyContinue'

$stateDir = Join-Path $env:LOCALAPPDATA 'CodeMode'
$pendingFile = Join-Path $stateDir 'pending-profile.json'
$adapterKey = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000'

function Get-SplitGB {
    $raw = (Get-ItemProperty $adapterKey -Name 'HardwareInformation.qwMemorySize').'HardwareInformation.qwMemorySize'
    if ($raw) { return [math]::Round($raw / 1GB, 1) }
    return $null
}

function Get-InstalledGB {
    $sum = (Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum
    if ($sum) { return [math]::Round($sum / 1GB, 1) }
    return $null
}

function Get-VisibleGB {
    return [math]::Round((Get-CimInstance Win32_OperatingSystem).TotalVisibleMemorySize / 1MB, 1)
}

function Get-WriteCandidates {
    # Places Armoury Crate has historically kept its settings. Reported, never
    # written: an unknown key here is firmware configuration, not a preference.
    $found = @()
    foreach ($root in @("$env:ProgramData\ASUS", "$env:ProgramData\ArmouryCrate",
                        "$env:LOCALAPPDATA\ArmouryCrateSE")) {
        if (-not (Test-Path $root)) { continue }
        Get-ChildItem $root -Recurse -Depth 2 -Include *.json -File -ErrorAction SilentlyContinue |
            Select-Object -First 40 |
            ForEach-Object {
                $text = Get-Content $_.FullName -Raw -ErrorAction SilentlyContinue
                if ($text -match 'vram|gpu.?memory|uma') { $found += $_.FullName }
            }
    }
    return $found
}

function Open-ArmouryCrate {
    $entry = Get-StartApps | Where-Object { $_.Name -match 'Armoury' } | Select-Object -First 1
    if ($entry) {
        Start-Process 'explorer.exe' ("shell:AppsFolder\" + $entry.AppID)
        return "opened " + $entry.Name
    }
    return "Armoury Crate not found in the start menu - open it manually"
}

# --------------------------------------------------------------------------
if ($Mode -eq 'cancel') {
    # /a complains loudly when nothing was pending; that is not an error here.
    shutdown.exe /a 2>$null | Out-Null
    Write-Host "Pending restart cancelled (if there was one)." -ForegroundColor Green
    if (Test-Path $pendingFile) { Remove-Item $pendingFile -Force; Write-Host "Staged profile discarded." }
    exit 0
}

$installed = Get-InstalledGB
$split = Get-SplitGB
$visible = Get-VisibleGB

if ($Mode -eq 'status') {
    Write-Host ""
    Write-Host "=== GPU memory split ===" -ForegroundColor Cyan
    "  installed        : {0} GB" -f $installed
    "  assigned to GPU  : {0} GB" -f $split
    "  visible to OS    : {0} GB" -f $visible
    "  free right now   : {0:N0} MB" -f ([math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024, 0))
    Write-Host ""
    "  code profile     : GPU {0}G  ->  ~{1} GB visible" -f $CodeGB, [math]::Round($installed - $CodeGB - 0.3, 1)
    "  gaming profile   : GPU {0}G  ->  ~{1} GB visible" -f $GamingGB, [math]::Round($installed - $GamingGB - 0.3, 1)

    if ($null -ne $split -and $split -le ($CodeGB + 0.5)) {
        Write-Host "  verdict          : already code-shaped" -ForegroundColor Green
    } elseif ($null -ne $split) {
        Write-Host "  verdict          : gaming-shaped - switch to $CodeGB`G before a big model" -ForegroundColor Yellow
    }

    $candidates = Get-WriteCandidates
    Write-Host ""
    Write-Host "=== Writable path for the split ===" -ForegroundColor Cyan
    if ($candidates.Count -eq 0) {
        Write-Host "  none found - this is set in Armoury Crate, applied at boot" -ForegroundColor DarkGray
    } else {
        Write-Host "  config candidates (inspect only, never written blindly):" -ForegroundColor DarkGray
        $candidates | ForEach-Object { "    $_" }
    }
    if (Test-Path $pendingFile) {
        Write-Host ""
        $p = Get-Content $pendingFile -Raw | ConvertFrom-Json
        Write-Host ("  staged profile   : {0} (target GPU {1}G, staged {2})" -f $p.profile, $p.target_gb, $p.at) -ForegroundColor Yellow
    }
    exit 0
}

# --------------------------------------------------------------------------
# stage the profile
# --------------------------------------------------------------------------
$target = if ($Mode -eq 'code') { $CodeGB } else { $GamingGB }
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
[pscustomobject]@{
    profile   = $Mode
    target_gb = $target
    at        = (Get-Date).ToString('s')
} | ConvertTo-Json | Set-Content -Path $pendingFile

Write-Host ""
Write-Host "=== Staging the $Mode profile ===" -ForegroundColor Cyan
"  GPU now          : {0} GB  (visible {1} GB)" -f $split, $visible
"  GPU wanted       : {0} GB  (would give ~{1} GB visible)" -f $target, [math]::Round($installed - $target - 0.3, 1)
"  staged for boot  : $pendingFile"
Write-Host ""
Write-Host "  The split itself cannot be written from software: it is applied at boot." -ForegroundColor Yellow
Write-Host "  Armoury Crate SE > Settings > Operating Mode > GPU settings > Memory assigned to GPU" -ForegroundColor Yellow

if (-not $NoLaunch) {
    $opened = Open-ArmouryCrate
    Write-Host "  $opened" -ForegroundColor DarkGray
}

if ($NoReboot) {
    Write-Host ""
    Write-Host "  -NoReboot set: nothing restarted. Profile stays staged." -ForegroundColor DarkGray
    exit 0
}

Write-Host ""
Write-Host "  Restarting in $Delay seconds." -ForegroundColor Yellow
Write-Host "  Cancel with:  shutdown /a     (or the profile dialog in the app)" -ForegroundColor Yellow
shutdown.exe /r /t $Delay /c "CodeMode: switching to $Mode profile"
exit 0
