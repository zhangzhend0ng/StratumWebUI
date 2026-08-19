# Check that the built executables carry a non-default embedded icon.
Add-Type -AssemblyName System.Drawing
$exe = Resolve-Path "dist\StratumWebUI\StratumWebUI.exe"
$setup = Resolve-Path "dist\installer\StratumWebUI-Setup-0.1.0.exe"

foreach ($f in $exe, $setup) {
    $icon = [System.Drawing.Icon]::ExtractAssociatedIcon($f)
    # Save the extracted 32px icon and compare it pixel-wise against our own.
    $bmp = $icon.ToBitmap()
    $tmp = "$env:TEMP\icon_check.png"
    $bmp.Save($tmp, [System.Drawing.Imaging.ImageFormat]::Png)

    $ours = New-Object System.Drawing.Bitmap(
        (Resolve-Path "packaging\stratum-webui.ico").Path)
    # icon.ToBitmap is 32x32; resample ours to 32 for comparison
    $ours32 = New-Object System.Drawing.Bitmap(32, 32)
    $g = [System.Drawing.Graphics]::FromImage($ours32)
    $g.InterpolationMode = "HighQualityBicubic"
    $g.DrawImage($ours, 0, 0, 32, 32)
    $g.Dispose()

    $diff = 0
    for ($x = 0; $x -lt 32; $x++) {
        for ($y = 0; $y -lt 32; $y++) {
            $p1 = $bmp.GetPixel($x, $y)
            $p2 = $ours32.GetPixel($x, $y)
            if ([Math]::Abs($p1.R - $p2.R) -gt 24 -or
                [Math]::Abs($p1.G - $p2.G) -gt 24 -or
                [Math]::Abs($p1.B - $p2.B) -gt 24) { $diff++ }
        }
    }
    "{0}  ->  {1}/1024 pixels differ from our icon (low = embedded OK)" -f `
        (Split-Path -Leaf $f), $diff
}
