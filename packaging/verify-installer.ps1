# Automated end-to-end verification for the Stratum WebUI installer.
# Runs fully silent (no UAC, no dialogs, no browser): install -> verify layout
# -> app smoke -> uninstall -> verify cleanup.
#
# Exit code: 0 = every check passed, 1 = at least one failed (CI gate).
# $ErrorActionPreference stays Continue: a failed step is RECORDED, not fatal —
# the script must run the uninstall cleanup even after an earlier failure.
$ErrorActionPreference = "Continue"
$fail = 0
function Fail($msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; $script:fail += 1 }

# Run from anywhere: resolve the repo root (script lives in packaging\).
$root = Split-Path -Parent $PSScriptRoot
# Setup filename is version-coupled (installer.iss OutputBaseFilename) — derive
# it by glob instead of hardcoding 0.1.0, which would silently rot on a bump.
$setup = Get-ChildItem (Join-Path $root "dist\installer") -Filter "StratumWebUI-Setup-*.exe" `
         -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { Fail "no dist\installer\StratumWebUI-Setup-*.exe found"; exit 1 }
$setup = $setup.FullName
Write-Host "setup = $setup"

$dir = "$env:LOCALAPPDATA\Temp\stratumui-e2e"
if (Test-Path $dir) { Remove-Item -Recurse -Force $dir }

# --- install (per-user, silent) ------------------------------------------------
$p = Start-Process -FilePath $setup -Wait -PassThru `
    -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART","/CURRENTUSER","/DIR=$dir"
Write-Host "install rc      = $($p.ExitCode)"
if ($p.ExitCode -ne 0) { Fail "install rc=$($p.ExitCode)" }

# --- layout --------------------------------------------------------------------
foreach ($f in "StratumWebUI.exe","VERSION.txt","unins000.exe",
               "bin\stratum.exe","_internal\index.html",
               "_internal\report.js","_internal\stl-preview.js") {
    $ok = Test-Path (Join-Path $dir $f)
    Write-Host ("  {0,-24} {1}" -f $f, $ok)
    if (-not $ok) { Fail "layout missing $f" }
}

# --- app smoke (hidden window, no browser, curl status) ------------------------
# snapshot the app's temp work dirs: a Force kill can NEVER run in-process
# cleanup (TerminateProcess), so this script reclaims what it kills itself
$tmpBefore = @(Get-ChildItem $env:TEMP -Filter "stratum_ui_*" -Directory `
               -ErrorAction SilentlyContinue | ForEach-Object FullName)
$env:STRATUM_UI_NO_BROWSER = "1"
$env:STRATUM_UI_PORT = "8803"
$app = Start-Process -FilePath (Join-Path $dir "StratumWebUI.exe") `
       -WorkingDirectory $dir -WindowStyle Hidden -PassThru
Start-Sleep -Seconds 4
try {
    $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8803/api/status" -TimeoutSec 10
    Write-Host "app /api/status= $($r.StatusCode): $($r.Content)"
    if ($r.StatusCode -ne 200) { Fail "api/status rc=$($r.StatusCode)" }
    elseif ($r.Content -notmatch '"binary_found":\s*true') { Fail "api/status binary_found!=true" }
} catch {
    Fail "api/status request failed: $_"
}
try {
    $i = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8803/" -TimeoutSec 10
    Write-Host "app index       = $($i.StatusCode) ($($i.RawContentLength) bytes)"
    if ($i.StatusCode -ne 200) { Fail "index rc=$($i.StatusCode)" }
} catch {
    Fail "index request failed: $_"
}
Stop-Process -Id $app.Id -Force
Wait-Process -Id $app.Id -Timeout 10 -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
# reclaim dirs this script's Force kill orphaned (expected on TerminateProcess;
# the app's own startup sweep would also catch them, but the verifier leaves
# no mess behind by design)
$leaked = @(Get-ChildItem $env:TEMP -Filter "stratum_ui_*" -Directory `
            -ErrorAction SilentlyContinue | ForEach-Object FullName) |
          Where-Object { $tmpBefore -notcontains $_ }
foreach ($d in $leaked) { Remove-Item -Recurse -Force $d -ErrorAction SilentlyContinue }
if ($leaked) { Write-Host "workdir          = reclaimed $($leaked.Count) force-killed dir(s)" }

# --- uninstall (self-detaching; poll until it finishes) -------------------------
Start-Process -FilePath (Join-Path $dir "unins000.exe") `
    -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" | Out-Null
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {
    if (-not (Test-Path (Join-Path $dir "unins000.exe"))) { break }
    Start-Sleep -Seconds 1
}
Start-Sleep -Seconds 2
if (Test-Path $dir) {
    $left = @(Get-ChildItem $dir -Recurse -File).Count
    Write-Host "uninstall       = LEFTOVER ($left files): $((Get-ChildItem $dir -Recurse -File | Select-Object -First 5 | ForEach-Object FullName) -join '; ')"
    Fail "uninstall left $left files behind"
} else {
    Write-Host "uninstall       = clean (directory removed)"
}

if ($fail -gt 0) { Write-Host "$fail check(s) failed"; exit 1 }
Write-Host "all installer checks passed"; exit 0
