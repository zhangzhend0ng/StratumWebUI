# Stratum WebUI build script — PyInstaller (onedir) + Inno Setup installer.
#
# Usage (repo root):
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#   powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -SkipInstaller
#
# Prerequisites:
#   - Python 3.8+ on PATH (a dedicated .venv-build is created; tools are
#     pinned in packaging\requirements-build.txt for reproducible builds)
#   - bin\stratum.exe (copy from the Stratum SDK release)
#   - Inno Setup 6 for the Setup.exe step: winget install -e --id JRSoftware.InnoSetup
#     (skipped gracefully when missing or when -SkipInstaller is given)

param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$root  = Split-Path -Parent $PSScriptRoot
$venv  = Join-Path $root ".venv-build"
$dist  = Join-Path $root "dist"
$venvPython = Join-Path $venv "Scripts\python.exe"

# --- 0. preflight --------------------------------------------------------------
$engine = Join-Path $root "bin\stratum.exe"
if (-not (Test-Path $engine)) {
    Write-Error "bin\stratum.exe not found. Copy it from the Stratum SDK release first (see README)."
}

# --- 1. isolated build venv with pinned tools ------------------------------------
if (-not (Test-Path $venvPython)) {
    python -m venv $venv
    if ($LASTEXITCODE -ne 0) { Write-Error "venv creation failed ($LASTEXITCODE)" }
}
& $venvPython -m pip install --quiet -r (Join-Path $PSScriptRoot "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed ($LASTEXITCODE)" }

# --- 2. PyInstaller onedir --------------------------------------------------------
& (Join-Path $venv "Scripts\pyinstaller.exe") `
    (Join-Path $PSScriptRoot "StratumWebUI.spec") `
    --noconfirm --distpath $dist --workpath (Join-Path $root "build")
if ($LASTEXITCODE -ne 0) { Write-Error "pyinstaller failed ($LASTEXITCODE)" }

# --- 3. lay out the portable app (engine + engine VERSION.txt next to the exe) ----
$app = Join-Path $dist "StratumWebUI"
New-Item -ItemType Directory -Force -Path (Join-Path $app "bin") | Out-Null
# whole bin\ dir, not just the exe: SDK manifests ship stratum_shared.dll
# alongside stratum.exe (VERSION.txt 0.21.0) — an exe needing the dll must
# not have it silently dropped from the layout.
Copy-Item (Join-Path $root "bin\*") (Join-Path $app "bin") -Force
Copy-Item (Join-Path $root "VERSION.txt") $app -Force
Write-Host "Portable app ready: $app"

# --- 4. Inno Setup installer --------------------------------------------------------
if ($SkipInstaller) {
    Write-Host "-SkipInstaller given: skipping Setup.exe"
    exit 0
}
$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"  # winget user-scope install
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
    Write-Warning "Inno Setup 6 (ISCC.exe) not found — skipping Setup.exe."
    Write-Warning "Install it with: winget install -e --id JRSoftware.InnoSetup"
    exit 0
}
# installer version = server.py's UI_VERSION (single source of truth; iter 61:
# the previously hardcoded installer version drifted from /api/status ui_version)
$uiVersion = (Select-String -Path (Join-Path $root "server.py") `
    -Pattern 'UI_VERSION\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
if (-not $uiVersion) { $uiVersion = "0.0.0-dev" }
Write-Host "installer version: $uiVersion (from server.py UI_VERSION)"
& $iscc (Join-Path $PSScriptRoot "installer.iss") "/DMyAppVersion=$uiVersion"
if ($LASTEXITCODE -ne 0) { Write-Error "ISCC failed ($LASTEXITCODE)" }
Write-Host "Installer ready: $dist\installer\"
