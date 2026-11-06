$ErrorActionPreference = 'Stop'
try {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut("$HOME\Desktop\CodeMode.lnk")
    $link.TargetPath = 'C:\Program Files\Python311\pythonw.exe'
    $link.Arguments = '-m app.ui'
    $link.WorkingDirectory = 'C:\Users\james\Downloads\CodeMode'
    $link.Description = 'CodeMode AI Assistant'
    $link.Save()
    Write-Output "Created shortcut at $HOME\Desktop\CodeMode.lnk"
} catch {
    Write-Error "Failed to create shortcut: $_"
    exit 1
}
