# zlibrary-batch-download launcher for PowerShell.
#
# ASCII-only on purpose: Windows PowerShell 5.1 reads .ps1 files using the
# system ANSI code page unless they carry a UTF-8 BOM, so Chinese text here
# would decode as garbage. Every human-facing message lives in bootstrap.py,
# which Python reads as UTF-8.
#
# Usage:  .\start.ps1          (from the project folder)
#         .\start.ps1 -Force   (reinstall dependencies)

$ErrorActionPreference = 'Stop'

Set-Location -Path $PSScriptRoot

$pyExe = $null

# Prefer the project venv when it already exists: fastest path, no probing.
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython) {
    $pyExe = $venvPython
}

# py.exe (the PEP 397 launcher) ships with the official installer and picks
# the newest interpreter present; fall back to a bare python on PATH.
if (-not $pyExe) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $pyExe = 'py'
    }
    elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $pyExe = 'python'
    }
}

if (-not $pyExe) {
    Write-Host ''
    Write-Host '  Python not found.'
    Write-Host ''
    Write-Host '  Install Python 3.11 or newer from https://www.python.org/downloads/'
    Write-Host '  During setup, tick "Add python.exe to PATH", then run this script again.'
    Write-Host ''
    exit 1
}

# 5.1 has no && / || chaining, so invoke directly and pass the exit code up.
& $pyExe bootstrap.py @args
exit $LASTEXITCODE
