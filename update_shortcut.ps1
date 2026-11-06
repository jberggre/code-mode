$path = Join-Path ([Environment]::GetFolderPath('Desktop')) 'CodeMode.lnk'
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($path)
$lnk.TargetPath = 'C:\Program Files\Python311\pythonw.exe'
$lnk.Arguments = '-m app.ui'
$lnk.WorkingDirectory = 'C:\Users\james\Downloads\CodeMode'
$lnk.Description = 'CodeMode AI Assistant'
$lnk.Save()
"Created: $path"
$path = Join-Path ([Environment]::GetFolderPath('Desktop')) 'CodeMode.lnk'
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($path)
$lnk.TargetPath = 'C:\Program Files\Python311\pythonw.exe'
$lnk.Arguments = '-m app.ui --no-shell'
$lnk.WorkingDirectory = 'C:\Users\james\Downloads\CodeMode'
$lnk.Description = 'CodeMode AI Assistant (shell off)'
$lnk.Save()
"Updated: $path with args"
