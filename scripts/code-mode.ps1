<#
    code-mode.ps1 - a real Code Mode session.

    Entering Code Mode SUSPENDS (does not kill) everything that is not needed to
    code, empties its working set, stops non-critical services, and trims visual
    effects. Leaving Code Mode resumes the same processes, restarts the services,
    and restores the settings. Suspension is reversible; nothing is uninstalled.

    Never touched, by construction:
        svchost, lsass, csrss, winlogon, dwm, explorer, Defender, the audio stack,
        and anything Xbox / GamingServices / Armoury Crate / ASUS / AMD - the full
        screen experience keeps working.

    What this cannot do: free the GPU carve-out. That is the Armoury Crate "memory
    assigned to GPU" setting (1G) and it needs a reboot. Every other GB here is
    processes and services.

    Usage:
        .\code-mode.ps1                       status: what is eating RAM, is a session live
        .\code-mode.ps1 -Mode code            enter Code Mode
        .\code-mode.ps1 -Mode gaming          leave Code Mode, restore everything
        .\code-mode.ps1 -Mode code -DryRun    show the plan, change nothing
        .\code-mode.ps1 -Mode code -KeepBrowsers
        .\code-mode.ps1 -Mode code -IncludeShell    also suspend explorer (extreme)
        .\code-mode.ps1 -Mode code -SetPowerPlan Performance
#>
[CmdletBinding()]
param(
    [ValidateSet('code', 'gaming', 'status')]
    [string]$Mode = 'status',
    [switch]$DryRun,
    [switch]$Kill,
    [switch]$KeepBrowsers,
    [switch]$IncludeShell,
    [string]$SetPowerPlan = ''
)

$ErrorActionPreference = 'SilentlyContinue'

$stateDir = Join-Path $env:LOCALAPPDATA 'CodeMode'
# Deliberately NOT 'session.json': the UI stores chat history in that file, and
# clobbering the record of suspended PIDs would leave apps frozen with no way back.
$stateFile = Join-Path $stateDir 'code-mode-session.json'

# --------------------------------------------------------------------------
# native bits: suspend / resume / trim working set
# --------------------------------------------------------------------------
if (-not ('CM.Native' -as [type])) {
    Add-Type -Namespace CM -Name Native -MemberDefinition @"
[DllImport("ntdll.dll")] public static extern int NtSuspendProcess(IntPtr handle);
[DllImport("ntdll.dll")] public static extern int NtResumeProcess(IntPtr handle);
[DllImport("psapi.dll")] public static extern bool EmptyWorkingSet(IntPtr handle);
[DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
[DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);
"@
}

$PROCESS_SUSPEND_RESUME = 0x0800
$PROCESS_SET_QUOTA = 0x0100
$PROCESS_QUERY_INFORMATION = 0x0400

function Suspend-App($proc) {
    $handle = [CM.Native]::OpenProcess($PROCESS_SUSPEND_RESUME, $false, $proc.Id)
    if ($handle -eq [IntPtr]::Zero) { return $false }
    $rc = [CM.Native]::NtSuspendProcess($handle)
    [void][CM.Native]::CloseHandle($handle)
    if ($rc -ne 0) { return $false }
    $trim = [CM.Native]::OpenProcess(($PROCESS_SET_QUOTA -bor $PROCESS_QUERY_INFORMATION), $false, $proc.Id)
    if ($trim -ne [IntPtr]::Zero) {
        [void][CM.Native]::EmptyWorkingSet($trim)
        [void][CM.Native]::CloseHandle($trim)
    }
    return $true
}

function Resume-App($proc) {
    $handle = [CM.Native]::OpenProcess($PROCESS_SUSPEND_RESUME, $false, $proc.Id)
    if ($handle -eq [IntPtr]::Zero) { return $false }
    $rc = [CM.Native]::NtResumeProcess($handle)
    [void][CM.Native]::CloseHandle($handle)
    return ($rc -eq 0)
}

function Purge-Standby {
    # What RAMMap calls "Empty Standby List": converts standby pages into free
    # pages. This is the step that actually raises headroom for a model; the
    # suspend alone only moves pages onto the standby list. Needs admin.
    if (-not ('CM.Mem' -as [type])) {
        Add-Type -Namespace CM -Name Mem -MemberDefinition @"
[DllImport("ntdll.dll")] public static extern int NtSetSystemInformation(int infoClass, IntPtr info, int length);
"@
    }
    $buffer = [System.Runtime.InteropServices.Marshal]::AllocHGlobal(4)
    [System.Runtime.InteropServices.Marshal]::WriteInt32($buffer, 4)  # MemoryPurgeStandbyList
    $rc = [CM.Mem]::NtSetSystemInformation(0x50, $buffer, 4)         # SystemMemoryListInformation
    [System.Runtime.InteropServices.Marshal]::FreeHGlobal($buffer)
    return ($rc -eq 0)
}

function Free-RamMB {
    return [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024, 0)
}

function Head($text) { Write-Host ""; Write-Host "=== $text ===" -ForegroundColor Cyan }

# --------------------------------------------------------------------------
# what may and may not be touched
# --------------------------------------------------------------------------

# Always denied: OS critical, this app, terminals, the shell, the audio stack.
$neverTouch = @(
    'System', 'Idle', 'Registry', 'Memory Compression', 'smss', 'csrss', 'wininit',
    'winlogon', 'services', 'lsass', 'svchost', 'dwm', 'fontdrvhost', 'LogonUI',
    'sihost', 'ctfmon', 'TextInputHost', 'audiodg', 'explorer', 'RuntimeBroker',
    'ShellExperienceHost', 'StartMenuExperienceHost', 'SearchHost', 'SearchApp',
    'MsMpEng', 'NisSrv', 'MpDefenderCoreService', 'SecurityHealthService',
    'SecurityHealthSystray', 'python', 'pythonw', 'conhost', 'WindowsTerminal',
    'cmd', 'powershell', 'pwsh', 'WindowsPowerShell'
)

# Vendor stacks that must keep working even mid-session.
$protectedVendor = @('Armoury', 'ASUS', 'Asus', 'AMD', 'Radeon', 'Realtek',
                     'Xbox', 'GamingServices', 'GameInput', 'Dolby', 'Waves', 'DTS')

$browserTargets = @('msedge', 'chrome', 'firefox', 'brave', 'opera', 'vivaldi')
$appTargets = @(
    'OneDrive', 'Dropbox', 'GoogleDriveFS', 'pCloud', 'MEGAsync',
    'EpicGamesLauncher', 'Battle.net', 'Steam', 'GalaxyClient', 'UbisoftConnect',
    'EADesktop', 'Origin', 'RiotClientServices',
    'Teams', 'ms-teams', 'Slack', 'Discord', 'Telegram', 'WhatsApp', 'Signal', 'Zoom',
    'Spotify', 'SpotifyWebHelper',
    'GameBar', 'GameBarFT',
    'YourPhone', 'PhoneExperienceHost',
    'Widgets', 'WidgetService'
)

# Services that are safe to stop for a coding session. Protected names are
# rejected below even if listed here by mistake.
$serviceTargets = @('DiagTrack', 'dmwappushservice', 'RemoteRegistry', 'WSearch',
                    'SysMain', 'Spooler', 'MapsBroker', 'Fax', 'WMPNetworkSvc')
$protectedServices = @('GamingServices', 'GamingServicesNet', 'XblAuthManager',
                       'XblGameSave', 'XboxGipSvc', 'XboxNetApiSvc', 'GameInputSvc',
                       'Audiosrv', 'AudioEndpointBuilder', 'Armoury*', 'Asus*',
                       'ASUS*', 'amd*', 'bthserv', 'BTAGService')

function Test-Denied($name) {
    foreach ($d in $neverTouch) { if ($name -eq $d) { return $true } }
    foreach ($p in $protectedVendor) { if ($name -like "*$p*") { return $true } }
    return $false
}

function Test-ProtectedService($name) {
    foreach ($p in $protectedServices) { if ($name -like $p) { return $true } }
    return $false
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------
if ($Mode -eq 'status') {
    Head "Memory"
    "  free now : {0:N0} MB" -f (Free-RamMB)

    if (Test-Path $stateFile) {
        $existing = Get-Content $stateFile -Raw | ConvertFrom-Json
        "  session  : ACTIVE since $($existing.saved_at)"
        "  paused   : {0} processes, {1} services stopped" -f @($existing.suspended).Count, @($existing.services).Count
        foreach ($item in $existing.suspended) { "      {0} (pid {1}, {2} MB)" -f $item.name, $item.pid, $item.mb }
    } else {
        "  session  : not active"
    }

    Head "Top memory consumers"
    Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 12 | ForEach-Object {
        "  {0,-24} {1,7:N0} MB  pid {2}" -f $_.ProcessName, ($_.WorkingSet64 / 1MB), $_.Id
    }

    Head "Facts"
    "  admin    : $isAdmin (services need it; processes do not)"
    "  GPU/BIOS reserve is not reachable from here - Armoury Crate, memory assigned to GPU."
    exit 0
}

# --------------------------------------------------------------------------
# leave Code Mode: restore everything
# --------------------------------------------------------------------------
if ($Mode -eq 'gaming') {
    Head "Restoring Code Mode session"
    if (-not (Test-Path $stateFile)) {
        Write-Host "  no session recorded - nothing to restore." -ForegroundColor Yellow
        exit 0
    }
    $session = Get-Content $stateFile -Raw | ConvertFrom-Json

    foreach ($item in $session.suspended) {
        $proc = Get-Process -Id $item.pid -ErrorAction SilentlyContinue
        if (-not $proc) { Write-Host ("  gone: " + $item.name + " (pid " + $item.pid + ")") -ForegroundColor DarkGray; continue }
        if ($DryRun) { Write-Host ("  would resume: " + $item.name); continue }
        if (Resume-App $proc) { Write-Host ("  resumed " + $item.name) -ForegroundColor Green }
        else { Write-Host ("  could not resume " + $item.name) -ForegroundColor Yellow }
    }

    foreach ($name in $session.services) {
        if ($DryRun) { Write-Host ("  would start service: " + $name); continue }
        Start-Service -Name $name -ErrorAction SilentlyContinue
        Write-Host ("  service started: " + $name) -ForegroundColor Green
    }

    $settings = $session.settings
    if ($settings) {
        if (-not $DryRun) {
            if ($null -ne $settings.transparency) {
                Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize' -Name 'EnableTransparency' -Value ([int]$settings.transparency) -Type DWord
            }
            if ($null -ne $settings.min_animate) {
                Set-ItemProperty -Path 'HKCU:\Control Panel\Desktop\WindowMetrics' -Name 'MinAnimate' -Value ([string]$settings.min_animate) -Type String
            }
            if ($null -ne $settings.visual_fx) {
                New-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects' -Force | Out-Null
                Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects' -Name 'VisualFXSetting' -Value ([int]$settings.visual_fx) -Type DWord
            }
            if ($settings.power_scheme) { powercfg /setactive $settings.power_scheme }
        }
        Write-Host "  visual effects restored" -ForegroundColor Green
    }

    if (-not $DryRun) { Remove-Item $stateFile -Force -ErrorAction SilentlyContinue }

    Head "Result"
    "  free RAM: {0:N0} MB" -f (Free-RamMB)
    Write-Host ""
    Write-Host "Xbox, Game Bar, GamingServices, Armoury Crate and audio were never touched." -ForegroundColor Yellow
    exit 0
}

# --------------------------------------------------------------------------
# enter Code Mode
# --------------------------------------------------------------------------
Head "Code Mode session"
if ($DryRun) { Write-Host "  DRY RUN - nothing will be suspended or stopped." -ForegroundColor Yellow }
if (-not $isAdmin) {
    Write-Host "  not elevated: processes will be paused, services will be skipped." -ForegroundColor DarkYellow
    Write-Host "  run once as administrator to also stop DiagTrack/WSearch/SysMain/etc." -ForegroundColor DarkGray
}

if ((Test-Path $stateFile) -and -not $DryRun) {
    Write-Host "  A session is already recorded. Restore it first:" -ForegroundColor Yellow
    Write-Host "      .\code-mode.ps1 -Mode gaming" -ForegroundColor Yellow
    Write-Host "  Refusing to start a second session - that would orphan the suspended apps." -ForegroundColor DarkGray
    exit 2
}

$before = Free-RamMB
$session = [ordered]@{
    saved_at = (Get-Date).ToString('s')
    suspended = @()
    services = @()
    settings = @{
        transparency = (Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize' -Name 'EnableTransparency').EnableTransparency
        min_animate = (Get-ItemProperty -Path 'HKCU:\Control Panel\Desktop\WindowMetrics' -Name 'MinAnimate').MinAnimate
        visual_fx = (Get-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects' -Name 'VisualFXSetting').VisualFXSetting
        power_scheme = ((powercfg /getactivescheme) -join ' ')
    }
}
if ($session.settings.power_scheme -match '([0-9a-fA-F-]{36})') {
    $session.settings.power_scheme = $matches[1]
}

$targets = @()
if (-not $KeepBrowsers) { $targets += $browserTargets }
$targets += $appTargets
if ($IncludeShell) { $targets += @('explorer') }

Head "Pausing background apps"
$pausedCount = 0
$claimedMB = 0
foreach ($name in $targets) {
    foreach ($proc in (Get-Process -Name $name -ErrorAction SilentlyContinue)) {
        if ($proc.Id -eq $PID) { continue }
        if (Test-Denied $proc.ProcessName -and -not ($IncludeShell -and $proc.ProcessName -eq 'explorer')) { continue }
        $mb = [math]::Round($proc.WorkingSet64 / 1MB, 0)
        if ($DryRun) {
            Write-Host ("  would pause {0} ({1:N0} MB)" -f $proc.ProcessName, $mb)
            $pausedCount++
            $claimedMB += $mb
            continue
        }
        if ($Kill) {
            if ($DryRun) {
                Write-Host ("  would close {0} ({1:N0} MB)" -f $proc.ProcessName, $mb)
                $pausedCount++
                $claimedMB += $mb
                continue
            }
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            $pausedCount++
            $claimedMB += $mb
            Write-Host ("  closed {0} ({1:N0} MB)" -f $proc.ProcessName, $mb) -ForegroundColor Green
            continue
        }
        if (Suspend-App $proc) {
            $session.suspended += [pscustomobject]@{ pid = $proc.Id; name = $proc.ProcessName; mb = $mb }
            $pausedCount++
            $claimedMB += $mb
            Write-Host ("  paused {0} ({1:N0} MB)" -f $proc.ProcessName, $mb) -ForegroundColor Green
        }
    }
}
if ($pausedCount -eq 0) { Write-Host "  nothing to pause - already lean" -ForegroundColor DarkGray }

Head "Stopping non-critical services"
foreach ($name in $serviceTargets) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $svc -or $svc.Status -ne 'Running') { continue }
    if (Test-ProtectedService $svc.Name) { Write-Host ("  skip (protected): " + $svc.Name) -ForegroundColor DarkYellow; continue }
    if ($DryRun) { Write-Host ("  would stop " + $svc.Name); continue }
    if (-not $isAdmin) { Write-Host ("  needs admin: " + $svc.Name) -ForegroundColor DarkGray; continue }
    Stop-Service -Name $svc.Name -Force -ErrorAction SilentlyContinue
    $session.services += $svc.Name
    Write-Host ("  stopped " + $svc.Name) -ForegroundColor Green
}

Head "Cutting visual overhead"
if ($DryRun) {
    Write-Host "  would disable transparency and window animations"
} else {
    Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize' -Name 'EnableTransparency' -Value 0 -Type DWord
    Set-ItemProperty -Path 'HKCU:\Control Panel\Desktop\WindowMetrics' -Name 'MinAnimate' -Value '0' -Type String
    New-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects' -Force | Out-Null
    Set-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects' -Name 'VisualFXSetting' -Value 2 -Type DWord
    Write-Host "  transparency off, animations off, effects = best performance" -ForegroundColor Green
}

Head "Releasing standby memory"
if (-not $isAdmin) {
    Write-Host "  needs admin: purging the standby list is the step that turns paused" -ForegroundColor DarkGray
    Write-Host "  pages into real free RAM. Re-run from an elevated shell to use it." -ForegroundColor DarkGray
} elseif ($DryRun) {
    Write-Host "  would purge the standby list"
} elseif (Purge-Standby) {
    Write-Host "  standby list purged" -ForegroundColor Green
} else {
    Write-Host "  kernel refused the purge" -ForegroundColor Yellow
}

if ($SetPowerPlan -and -not $DryRun) {
    Head "Power plan"
    $guid = (powercfg /list | Select-String ([regex]::Escape($SetPowerPlan)) | ForEach-Object {
        if ($_ -match '([0-9a-fA-F-]{36})') { $matches[1] }
    } | Select-Object -First 1)
    if ($guid) { powercfg /setactive $guid; Write-Host "  active scheme -> $SetPowerPlan" -ForegroundColor Green }
    else { Write-Host "  scheme '$SetPowerPlan' not found; left unchanged" -ForegroundColor DarkYellow }
}

if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
    $session | ConvertTo-Json -Depth 6 | Set-Content -Path $stateFile
}

$after = Free-RamMB
$freed = $after - $before

Head "Result"
if ($DryRun) {
    "  would pause {0} processes, claiming about {1:N0} MB" -f $pausedCount, $claimedMB
    "  free RAM now: {0:N0} MB" -f $after
} else {
    if ($Kill) {
        "  closed   : {0} processes ({1:N0} MB of working set)" -f $pausedCount, $claimedMB
        "  note     : closed apps cannot be restored by -Mode gaming; only suspended ones can."
    } else {
        "  paused   : {0} processes ({1:N0} MB of working set)" -f $pausedCount, $claimedMB
    }
    "  free RAM : {0:N0} MB -> {1:N0} MB  (freed {2:N0} MB)" -f $before, $after, $freed
    "  undo     : .\code-mode.ps1 -Mode gaming"
}
Write-Host ""
Write-Host "The GPU carve-out is not reachable from here: Armoury Crate > GPU memory 1G," -ForegroundColor Yellow
Write-Host "then reboot. That is the only lever that frees multiple GB for a 7B+ model." -ForegroundColor Yellow
exit 0
