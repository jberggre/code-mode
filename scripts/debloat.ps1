<#
    debloat.ps1 - permanent, reviewable debloat for the ROG Xbox Ally (RC73YA).

    Default is a dry run: it prints exactly what it would remove and changes nothing.
    Add -Apply (in an elevated PowerShell) to make the changes permanent.

    Gaming is protected by construction. Anything matching $Protected (Xbox,
    GamingServices, Game Bar, Store, App Installer, ASUS/Armoury, AMD, audio and
    media runtimes) is skipped even if a target pattern matches it.

    Usage:
        .\debloat.ps1                     # audit only
        .\debloat.ps1 -Apply              # remove AppX + telemetry services + OneDrive/Edge autostart
        .\debloat.ps1 -Apply -Aggressive  # also SysMain/WSearch/Spooler + game launcher autostart
        .\debloat.ps1 -RestoreStartup     # put back autostart entries from the newest backup
#>
[CmdletBinding()]
param(
    [switch]$Apply,
    [switch]$Aggressive,
    [switch]$RestoreStartup,
    [string]$BackupRoot = "$env:USERPROFILE\CodeMode\debloat-backups"
)

$ErrorActionPreference = 'Continue'

function Write-Head($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Test-Protected($name) {
    foreach ($p in $script:Protected) { if ($name -like $p) { return $true } }
    return $false
}

# ---- never remove / never disable ------------------------------------------
$Protected = @(
    '*Xbox*', '*GamingServices*', '*GamingApp*', '*GameBar*', '*GameInput*',
    'Microsoft.WindowsStore', 'Microsoft.StorePurchaseApp', 'Microsoft.DesktopAppInstaller',
    'Microsoft.VCLibs*', 'Microsoft.UI.Xaml*', 'Microsoft.NET.Native*',
    'Microsoft.WindowsAppRuntime*', 'Microsoft.Winget*', 'Microsoft.SecHealthUI',
    'Microsoft.AAD.BrokerPlugin', 'Microsoft.AccountsControl',
    'Microsoft.Windows.Photos', 'Microsoft.WindowsCamera', 'Microsoft.Paint',
    'Microsoft.ScreenSketch', 'Microsoft.WindowsNotepad', 'Microsoft.WindowsTerminal',
    'MicrosoftWindows.Client*', 'MicrosoftWindows.CrossDevice*',
    '*ASUS*', 'B9ECED6F*', '*Armoury*', '*AMD*', '*Realtek*', '*Dolby*', '*Waves*', '*DTS*'
)
$ProtectedSvc = @(
    'GamingServices', 'GamingServicesNet', 'XblAuthManager', 'XblGameSave',
    'XboxGipSvc', 'XboxNetApiSvc', 'GameInputSvc', 'XboxGipSvc',
    'Armoury*', 'Asus*', 'ASUS*', 'amd*', 'AudioSrv', 'Audiosrv', 'AudioEndpointBuilder'
)

# ---- what gets removed -----------------------------------------------------
$AppxTargets = @(
    '*CandyCrush*', '*Solitaire*',
    'Microsoft.BingWeather', 'Microsoft.BingNews', 'Microsoft.BingSports', 'Microsoft.BingFinance',
    'Microsoft.News', 'Microsoft.Weather',
    'Microsoft.GetHelp', 'Microsoft.Getstarted', 'Microsoft.YourPhone',
    'Microsoft.WindowsFeedbackHub', 'Microsoft.MixedReality.Portal',
    'Microsoft.MSPaint', 'Microsoft.MicrosoftOfficeHub', 'Microsoft.Office.OneNote',
    'Microsoft.ZuneMusic', 'Microsoft.ZuneVideo', 'Microsoft.SkypeApp',
    'Microsoft.People', 'Microsoft.Todos', 'Microsoft.WindowsMaps',
    'Microsoft.windowscommunicationsapps', 'Microsoft.PowerAutomateDesktop',
    'Microsoft.MicrosoftSolitaireCollection', 'Microsoft.549981C3F5F10',
    'Microsoft.OutlookForWindows'
)
$AppxAggressive = @('Clipchamp.Clipchamp', 'MicrosoftTeams*', 'Microsoft.MicrosoftStickyNotes')

$SvcCore = @('DiagTrack', 'dmwappushservice', 'RemoteRegistry')
$SvcAggressive = @('SysMain', 'WSearch', 'Spooler', 'Fax')

$StartupCore = @('OneDrive', 'MicrosoftEdgeAutoLaunch')
$StartupAggressive = @('Battle.net', 'EpicGamesLauncher', 'Steam', 'GalaxyClient')

$RunKeys = @(
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
    'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'
)

Write-Host "ROG Xbox Ally debloat" -ForegroundColor Magenta
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if ($Apply -and -not $isAdmin) {
    Write-Host "ERROR: -Apply needs an elevated PowerShell (right-click > Run as administrator)." -ForegroundColor Red
    exit 1
}
if (-not $Apply) {
    Write-Host "DRY RUN - nothing will change. Add -Apply (as admin) to execute." -ForegroundColor Yellow
}
if ($Aggressive) {
    Write-Host "Aggressive set enabled (SysMain/WSearch/Spooler + game launcher autostart)." -ForegroundColor Yellow
    Write-Host "  Launcher autostart off is safe for updates: games patch when the launcher runs." -ForegroundColor DarkGray
    Write-Host "  Start them from the Updates panel in CodeMode instead of at login." -ForegroundColor DarkGray
}

# ---- backup ---------------------------------------------------------------
$backupDir = $null
if ($Apply) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $backupDir = Join-Path $BackupRoot "backup-$stamp"
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Get-AppxPackage | Select-Object Name, PackageFullName, Version |
        ConvertTo-Json -Depth 3 | Set-Content -Path (Join-Path $backupDir 'appx-before.json')
    Get-Service | Select-Object Name, DisplayName, Status, StartType |
        ConvertTo-Json -Depth 3 | Set-Content -Path (Join-Path $backupDir 'services-before.json')
    $runDump = [ordered]@{}
    foreach ($k in $RunKeys) {
        if (-not (Test-Path $k)) { continue }
        $vals = [ordered]@{}
        $item = Get-ItemProperty -Path $k
        foreach ($name in $item.PSObject.Properties.Name) {
            if ($name -like 'PS*') { continue }
            $vals[$name] = $item.$name
        }
        $runDump[$k] = $vals
    }
    $runDump | ConvertTo-Json -Depth 4 | Set-Content -Path (Join-Path $backupDir 'run-keys.json')
    (powercfg /getactivescheme) | Set-Content -Path (Join-Path $backupDir 'power-scheme.txt')
    Write-Host "backup written: $backupDir" -ForegroundColor DarkGray
}

# ---- restore mode ---------------------------------------------------------
if ($RestoreStartup) {
    $latest = Get-ChildItem $BackupRoot -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending | Select-Object -First 1
    if (-not $latest) { Write-Host "no backup found in $BackupRoot" -ForegroundColor Red; exit 1 }
    $file = Join-Path $latest.FullName 'run-keys.json'
    if (-not (Test-Path $file)) { Write-Host "backup has no run-keys.json" -ForegroundColor Red; exit 1 }
    $dump = Get-Content $file -Raw | ConvertFrom-Json
    foreach ($key in $dump.PSObject.Properties.Name) {
        if (-not (Test-Path $key)) { continue }
        $vals = $dump.$key
        foreach ($name in $vals.PSObject.Properties.Name) {
            if ($Apply) {
                New-ItemProperty -Path $key -Name $name -Value $vals.$name -PropertyType String -Force | Out-Null
                Write-Host "  restored startup: $name" -ForegroundColor Green
            } else {
                Write-Host "  would restore startup: $name"
            }
        }
    }
    if (-not $Apply) { Write-Host "DRY RUN - add -Apply to write." -ForegroundColor Yellow }
    exit 0
}

# ---- AppX -----------------------------------------------------------------
Write-Head "AppX packages"
$targets = $AppxTargets
if ($Aggressive) { $targets += $AppxAggressive }
$matched = @()
foreach ($t in $targets) {
    $matched += Get-AppxPackage | Where-Object { $_.Name -like $t }
}
$matched = $matched | Sort-Object Name -Unique

if (-not $matched) {
    Write-Host "  nothing matched - already clean" -ForegroundColor DarkGray
}
foreach ($pkg in $matched) {
    if (Test-Protected $pkg.Name) {
        Write-Host ("  skip (protected): " + $pkg.Name) -ForegroundColor DarkYellow
        continue
    }
    if ($Apply) {
        Remove-AppxPackage -Package $pkg.PackageFullName -ErrorAction SilentlyContinue
        Write-Host ("  removed: " + $pkg.Name) -ForegroundColor Green
    } else {
        Write-Host ("  would remove: " + $pkg.Name)
    }
}

if ($Apply) {
    Write-Head "Provisioned copies (blocks reinstall for new users)"
    $prov = Get-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue
    foreach ($t in $targets) {
        foreach ($pkg in ($prov | Where-Object { $_.DisplayName -like $t })) {
            if (Test-Protected $pkg.DisplayName) { continue }
            Remove-AppxProvisionedPackage -Online -PackageName $pkg.PackageName -ErrorAction SilentlyContinue | Out-Null
            Write-Host ("  deprovisioned: " + $pkg.DisplayName) -ForegroundColor Green
        }
    }
}

# ---- services -------------------------------------------------------------
Write-Head "Services"
$svcTargets = $SvcCore
if ($Aggressive) { $svcTargets += $SvcAggressive }
foreach ($name in $svcTargets) {
    $svc = Get-Service -Name $name -ErrorAction SilentlyContinue
    if (-not $svc) { Write-Host ("  not present: " + $name) -ForegroundColor DarkGray; continue }
    if (Test-Protected $svc.Name) { Write-Host ("  skip (protected): " + $svc.Name) -ForegroundColor DarkYellow; continue }
    if ($Apply) {
        Stop-Service -Name $svc.Name -Force -ErrorAction SilentlyContinue
        Set-Service -Name $svc.Name -StartupType Disabled -ErrorAction SilentlyContinue
        Write-Host ("  disabled: " + $svc.Name + " (" + $svc.DisplayName + ")") -ForegroundColor Green
    } else {
        Write-Host ("  would disable: " + $svc.Name + " [" + $svc.StartType + "] " + $svc.DisplayName)
    }
}

# ---- startup entries ------------------------------------------------------
Write-Head "Autostart entries"
$startTargets = $StartupCore
if ($Aggressive) { $startTargets += $StartupAggressive }
foreach ($key in $RunKeys) {
    if (-not (Test-Path $key)) { continue }
    $item = Get-ItemProperty -Path $key
    foreach ($name in @($item.PSObject.Properties.Name)) {
        if ($name -like 'PS*' -or $name -eq '(default)') { continue }
        $hit = $false
        foreach ($t in $startTargets) { if ($name -like "*$t*") { $hit = $true } }
        if (-not $hit) { continue }
        if ($Apply) {
            Remove-ItemProperty -Path $key -Name $name -ErrorAction SilentlyContinue
            Write-Host ("  disabled startup: " + $name) -ForegroundColor Green
        } else {
            Write-Host ("  would disable startup: " + $name)
        }
    }
}

# ---- report ---------------------------------------------------------------
Write-Head "State"
$os = Get-CimInstance Win32_OperatingSystem
"  free RAM   : {0:N1} GB of {1:N1} GB" -f ($os.FreePhysicalMemory / 1MB), ($os.TotalVisibleMemorySize / 1MB)
"  appx count : " + (Get-AppxPackage | Measure-Object).Count
"  services   : " + (Get-Service | Where-Object Status -eq 'Running' | Measure-Object).Count + " running"
"  protected  : Xbox, GamingServices, Game Bar, Store, ASUS/Armoury, AMD, audio"

Write-Host ""
if ($Apply) {
    Write-Host "Done. Reboot so the removed packages and disabled services settle." -ForegroundColor Yellow
    Write-Host "Undo autostart changes: .\debloat.ps1 -RestoreStartup -Apply" -ForegroundColor DarkGray
    Write-Host "Removed AppX can be reinstalled from the Store if you ever want one back." -ForegroundColor DarkGray
} else {
    Write-Host "Nothing changed. Re-run with -Apply in an elevated shell to commit." -ForegroundColor Yellow
}
