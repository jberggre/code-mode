param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$OutDir,
    [string]$Sizes = '16,24,32,48,64,128,256'
)
# Renders one square PNG and one raw BGRA frame per size, using System.Drawing so
# the resize is a proper high-quality resample rather than nearest neighbour.
$ErrorActionPreference = 'Stop'
# -File only binds one token per parameter, so sizes arrive comma separated.
# A fresh name is required: assigning an array back into the typed [string]
# parameter would silently re-join it into "16 24 32".
$sizeList = @($Sizes.Split(',') | Where-Object { $_ -ne '' } | ForEach-Object { [int]$_ })
Add-Type -AssemblyName System.Drawing
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$img = [System.Drawing.Image]::FromFile((Resolve-Path $Source).Path)
try {
    foreach ($s in $sizeList) {
        $bmp = New-Object System.Drawing.Bitmap($s, $s, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
        $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
        $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
        $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
        $g.DrawImage($img, (New-Object System.Drawing.Rectangle(0, 0, $s, $s)))
        $g.Dispose()

        $bmp.Save((Join-Path $OutDir "$s.png"), [System.Drawing.Imaging.ImageFormat]::Png)

        # 32bpp ARGB rows are 4*s bytes wide with no padding, so a flat copy is
        # exactly the frame; the Python side reorders it for the icon container.
        $rect = New-Object System.Drawing.Rectangle(0, 0, $s, $s)
        $bits = $bmp.LockBits($rect, [System.Drawing.Imaging.ImageLockMode]::ReadOnly,
                             [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $buf = New-Object byte[] ($s * $s * 4)
        [System.Runtime.InteropServices.Marshal]::Copy($bits.Scan0, $buf, 0, $buf.Length)
        $bmp.UnlockBits($bits)
        [IO.File]::WriteAllBytes((Join-Path $OutDir "$s.bin"), $buf)
        $bmp.Dispose()
    }
} finally {
    $img.Dispose()
}
Write-Output ('frames: ' + ($sizeList -join ','))
