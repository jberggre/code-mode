param([string]$Out = "artifacts\codemode-shell.png", [int]$ClickX = -1, [int]$ClickY = -1)
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hwnd, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr extra);
  public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
$pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
if (-not $pythonw) { $pythonw = (Get-Command python).Source }
$proc = Start-Process -FilePath $pythonw -ArgumentList "app\ui.py" -WorkingDirectory (Get-Location) -PassThru
Start-Sleep -Seconds 6
$proc.Refresh()
$h = $proc.MainWindowHandle
if ($h -eq 0) { Write-Error "no window handle for pid $($proc.Id)"; Stop-Process -Id $proc.Id -Force; exit 1 }
[Win]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 700
if ($ClickX -ge 0) {
  [Win]::SetCursorPos($ClickX, $ClickY) | Out-Null
  Start-Sleep -Milliseconds 250
  [Win]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 80
  [Win]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
  Start-Sleep -Milliseconds 600
}
$r = New-Object Win+RECT
[Win]::GetWindowRect($h, [ref]$r) | Out-Null
$w = $r.Right - $r.Left; $hgt = $r.Bottom - $r.Top
$bmp = New-Object System.Drawing.Bitmap $w, $hgt
$g = [System.Drawing.Graphics]::FromImage($bmp)
$hdc = $g.GetHdc()
$ok = [Win]::PrintWindow($h, $hdc, 2)
$g.ReleaseHdc($hdc)
if (-not $ok) { $g.CopyFromScreen($r.Left, $r.Top, 0, 0, $bmp.Size) }
$bmp.Save((Join-Path (Get-Location) $Out), [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Stop-Process -Id $proc.Id -Force
Write-Output "saved $Out ${w}x${hgt} printwindow=$ok"
