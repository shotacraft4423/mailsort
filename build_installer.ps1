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

# $ErrorActionPreference = "Stop" only turns PowerShell-level errors (a
# cmdlet throwing, a missing file) into a hard stop — it does NOT do that
# for an external .exe that runs to completion but exits with a non-zero
# code, which is exactly how a Rust/npm compile failure reports itself.
# Without this check, a failed `cargo build` deep inside `npm run tauri
# build` printed its error and then let the script fall straight through
# to the "Done" section, which then printed installer paths that were
# never actually produced — a real failure was reported as success.
function Invoke-Checked([string]$Description, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed (exit code $LASTEXITCODE) - see the output above for the actual error."
    }
}

$repoRoot = $PSScriptRoot
$backendDir = Join-Path $repoRoot "backend"
$frontendDir = Join-Path $repoRoot "frontend"

# --- 1. Freeze the backend -------------------------------------------------
Write-Section "Backend: setting up a build virtualenv"
Push-Location $backendDir
if (-not (Test-Path ".venv")) {
    Invoke-Checked "python -m venv" { python -m venv .venv }
}
& .\.venv\Scripts\Activate.ps1
Invoke-Checked "pip install" { pip install -e ".[build]" }

Write-Section "Backend: freezing with PyInstaller"
# --noconfirm overwrites a previous dist/build from an earlier run of this
# script without an interactive prompt.
Invoke-Checked "PyInstaller" { pyinstaller mailsort_backend.spec --noconfirm }
if (-not (Test-Path "dist\mailsort-backend.exe")) {
    throw "PyInstaller reported success but dist\mailsort-backend.exe is missing - check the output above."
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
Invoke-Checked "npm install" { npm install }

Write-Section "Building the installer (first run can take several minutes - Rust is compiling Tauri itself)"
Invoke-Checked "npm run tauri build" { npm run tauri build }
Pop-Location

# Confirm the installer(s) this script is about to advertise actually
# exist, rather than trusting the exit code alone — `tauri build` can
# report success while only producing a subset of the configured targets
# on some setups (e.g. missing WiX for msi).
$bundleDir = Join-Path $frontendDir "src-tauri\target\release\bundle"
$installers = Get-ChildItem -Path $bundleDir -Recurse -Include "*.exe", "*.msi" -ErrorAction SilentlyContinue
if (-not $installers) {
    throw "Build finished but no .exe/.msi installer was found under $bundleDir - check the tauri build output above."
}

Write-Section "Done"
Write-Host "Installer(s) written under: $bundleDir" -ForegroundColor Green
foreach ($installer in $installers) {
    Write-Host "  $($installer.FullName)" -ForegroundColor Green
}
Write-Host ""
Write-Host "Either of these is the file to hand to an end user - running it installs" -ForegroundColor Green
Write-Host "MailSort with no separate Python/Node/pip/npm step on their machine." -ForegroundColor Green
