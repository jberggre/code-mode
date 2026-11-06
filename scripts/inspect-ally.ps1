$ErrorActionPreference = 'SilentlyContinue'
function Line($t){ Write-Output ""; Write-Output ("=== " + $t + " ===") }

Line "MACHINE"
$cs = Get-CimInstance Win32_ComputerSystem
"Model      : $($cs.Manufacturer) $($cs.Model)"
"RAM_GB     : {0:N1}" -f ($cs.TotalPhysicalMemory/1GB)
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
"CPU        : $($cpu.Name) ($($cpu.NumberOfCores)C/$($cpu.NumberOfLogicalProcessors)T)"
$os = Get-CimInstance Win32_OperatingSystem
$rel = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
"OS         : $($os.Caption) $($rel.DisplayVersion) build $($os.BuildNumber)"
Get-CimInstance Win32_VideoController | ForEach-Object { "GPU        : $($_.Name) driver $($_.DriverVersion)" }

Line "DISKS"
Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -gt 0 } | ForEach-Object { "Drive {0}: free {1:N1} GB of {2:N1} GB" -f $_.Name, ($_.Free/1GB), (($_.Used+$_.Free)/1GB) }

Line "DEV TOOLING"
foreach ($c in 'node','npm','python','py','uv','git','ollama','winget','bun','code') {
  $p = Get-Command $c -ErrorAction SilentlyContinue
  if ($p) { "{0,-8} : {1}" -f $c, $p.Source } else { "{0,-8} : MISSING" -f $c }
}

Line "LOCAL LLM APPS"
foreach ($p in @("$env:LOCALAPPDATA\Programs\LM Studio","$env:LOCALAPPDATA\Programs\lm-studio","$env:PROGRAMFILES\LM Studio","$env:LOCALAPPDATA\Programs\Ollama","$env:PROGRAMFILES\Ollama","$env:LOCALAPPDATA\Programs\Jan","$env:LOCALAPPDATA\Programs\GPT4All")) { if (Test-Path $p) { "FOUND $p" } }
if (Get-Command ollama) { "OLLAMA MODELS:"; ollama list }
if (Test-Path "$env:USERPROFILE\.lmstudio\models") { "LMSTUDIO MODEL DIRS:"; Get-ChildItem "$env:USERPROFILE\.lmstudio\models" -Directory | ForEach-Object { "  " + $_.Name } }
Get-ChildItem "$env:LOCALAPPDATA\Programs" -Directory | Where-Object { $_.Name -match 'lm.?studio|ollama|jan|gpt4all|anything|kobold|text-gen' } | ForEach-Object { "PROGRAMS DIR: " + $_.FullName }

Line "STEAM LIBRARIES"
$steamRoots = @("C:\Program Files (x86)\Steam","C:\Program Files\Steam")
$libPaths = @()
foreach ($root in $steamRoots) {
  $lf = Join-Path $root 'steamapps\libraryfolders.vdf'
  if (Test-Path $lf) {
    "library file: $lf"
    (Get-Content $lf) | Select-String -Pattern '"path"\s+"(.+)"' | ForEach-Object { $libPaths += ($_.Matches[0].Groups[1].Value -replace '\\','\') }
  }
}
if ($libPaths.Count -eq 0) { $libPaths = @("C:\Program Files (x86)\Steam") }
foreach ($lp in ($libPaths | Select-Object -Unique)) {
  $sa = Join-Path $lp 'steamapps'
  if (Test-Path $sa) { "  LIB: $lp" }
  Get-ChildItem (Join-Path $sa 'appmanifest_*.acf') | ForEach-Object {
    $txt = Get-Content $_.FullName -Raw
    $name = if ($txt -match '"name"\s+"([^"]+)"') { $matches[1] } else { $_.Name }
    $sz = if ($txt -match '"SizeOnDisk"\s+"(\d+)"') { [math]::Round([int64]$matches[1]/1GB,1) } else { 0 }
    "  GAME {0,6} GB  {1}" -f $sz, $name
  }
}

Line "XBOXGAMES FOLDER"
if (Test-Path 'C:\XboxGames') { Get-ChildItem 'C:\XboxGames' -Directory | ForEach-Object { "  " + $_.Name } } else { '  none at C:\XboxGames' }

Line "XBOX / GAMING APPX"
Get-AppxPackage | Where-Object { $_.Name -match 'Xbox|GamingServices|GameBar|GamingApp' } | ForEach-Object { "APPX $($_.Name) $($_.Version)" }
"total appx packages: " + (Get-AppxPackage | Measure-Object).Count

Line "GAMING / FSE STATE"
"GameBar processes: " + (@(Get-Process GameBar,GamingServices,XboxPcApp -ErrorAction SilentlyContinue) | ForEach-Object { $_.Name } | Sort-Object -Unique) -join ', '
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\GameDVR' | Select-Object AppCaptureEnabled, GameDVR_Enabled | Format-List
Get-Service GamingServices,GameBar,GameInputSvc,XblGameSave,XblAuthManager 2>$null | ForEach-Object { "  svc $($_.Name): $($_.Status)/$($_.StartType)" }

Line "SERVICES + MAINTENANCE"
(Get-Service | Where-Object Status -eq 'Running' | Measure-Object).Count.ToString() + " services running"
Get-Service SysMain,DiagTrack,WSearch,Spooler,BTAGService,bthserv | ForEach-Object { "  $($_.Name): $($_.Status)/$($_.StartType)" }

Line "AUTOSTART"
Get-CimInstance Win32_StartupCommand | ForEach-Object { "  $($_.Name) -> $($_.Command)" }

Line "POWER PLANS"
powercfg /list
