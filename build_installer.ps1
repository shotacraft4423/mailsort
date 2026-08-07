# One-shot build of the MailSort one-click Windows installer.
#
# This freezes the FastAPI backend into a standalone executable
# (PyInstaller — no Python required on the end user's machine), bundles it
# as a Tauri "sidecar" that the desktop app launches automatically on
# startup, and produces the final NSIS/.exe (and .msi) installer. Everyone
# who *runs the finished installer* needs nothing but the installer file
# itself — no Python, no Node, no manual `pip install`/`npm install` step.
#
# This script itself, however, is a BUILD-machine tool, not something an
# end user ever runs. Prerequisites for the machine that runs this script
# (same as the manual dev setup in README.md):
#   - Python 3.11+           https://www.python.org/downloads/windows/
#   - Node.js 18+ (LTS)      https://nodejs.org/
#   - Rust + MSVC Build Tools: https://rustup.rs/ , then Visual Studio
#     Build Tools with the "C++ によるデスクトップ開発" workload
#   - WebView2 (Windows 11 has it built in; Windows 10 needs the runtime
#     from https://developer.microsoft.com/microsoft-edge/webview2/)
#
# Usage (from the repository root, in PowerShell):
#   powershell -ExecutionPolicy Bypass -File build_installer.ps1
#
# Output:
#   frontend\src-tauri\target\release\bundle\nsis\MailSort_<version>_x64-setup.exe
#   frontend\src-tauri\target\release\bundle\msi\MailSort_<version>_x64_en-US.msi

$ErrorActionPreference = "Stop"

function Write-Section($title) {
    Write-Host ""
    Write-Host "==> $title" -ForegroundColor Cyan
}

$repoRoot = $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"

# --- 1. Freeze the backend -------------------------------------------------
Write-Section "Backend: setting up a build virtualenv"
Push-Location $backendDir
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
pip install -e ".[build]"

Write-Section "Backend: freezing with PyInstaller"
# --noconfirm overwrites a previous dist/build from an earlier run of this
# script without an interactive prompt.
pyinstaller mailsort_backend.spec --noconfirm
if (-not (Test-Path "dist\mailsort-backend.exe")) {
    throw "PyInstaller did not produce dist\mailsort-backend.exe — check the output above for errors."
}
Pop-Location

# --- 2. Place the frozen exe where Tauri's sidecar mechanism expects it ---
# Tauri requires the sidecar binary's filename to carry a "-<target-triple>"
# suffix matching the build machine's own Rust target, so it can pick the
# right one if the same externalBin name were ever built for multiple
# platforms from the same source tree.
Write-Section "Determining this machine's Rust target triple"
$targetTriple = (rustc --print host-tuple).Trim()
Write-Host "Target triple: $targetTriple"

$binariesDir = Join-Path $frontendDir "src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $binariesDir | Out-Null
$sidecarDest = Join-Path $binariesDir "mailsort-backend-$targetTriple.exe"
Copy-Item (Join-Path $backendDir "dist\mailsort-backend.exe") $sidecarDest -Force
Write-Host "Copied backend sidecar to $sidecarDest"

# --- 3. Build the frontend + final installer -------------------------------
Write-Section "Frontend: installing dependencies"
Push-Location $frontendDir
npm install

Write-Section "Building the installer (first run can take several minutes — Rust is compiling Tauri itself)"
npm run tauri build
Pop-Location

Write-Section "Done"
$bundleDir = Join-Path $frontendDir "src-tauri\target\release\bundle"
Write-Host "Installer(s) written under: $bundleDir"
Write-Host "  NSIS:  bundle\nsis\MailSort_<version>_x64-setup.exe"
Write-Host "  MSI:   bundle\msi\MailSort_<version>_x64_en-US.msi"
Write-Host ""
Write-Host "Either of these is the file to hand to an end user — running it installs" -ForegroundColor Green
Write-Host "MailSort with no separate Python/Node/pip/npm step on their machine." -ForegroundColor Green
