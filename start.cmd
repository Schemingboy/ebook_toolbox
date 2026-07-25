@echo off
REM zlibrary-batch-download launcher for Windows -- just double-click this file.
REM
REM Kept deliberately ASCII-only: cmd.exe renders non-ASCII bytes using the
REM console code page, so Chinese text here would show up as garbage on many
REM machines. All human-facing messages live in bootstrap.py, which Python
REM reads as UTF-8. This file only has to find a Python and hand over.

setlocal
cd /d "%~dp0"

set "PYEXE="

REM Prefer the project venv if it already exists (fastest path, no probing).
if exist ".venv\Scripts\python.exe" set "PYEXE=.venv\Scripts\python.exe"

REM Otherwise look for a system Python. py.exe (the PEP 397 launcher) ships
REM with the official installer and resolves the newest version available.
if not defined PYEXE (
    where py >nul 2>&1 && set "PYEXE=py"
)
if not defined PYEXE (
    where python >nul 2>&1 && set "PYEXE=python"
)

if not defined PYEXE (
    echo.
    echo   Python not found.
    echo.
    echo   Install Python 3.11 or newer from https://www.python.org/downloads/
    echo   During setup, tick "Add python.exe to PATH", then run this file again.
    echo.
    pause
    exit /b 1
)

"%PYEXE%" bootstrap.py %*
set "RC=%ERRORLEVEL%"

REM Keep the window open on failure so the error stays readable after a
REM double-click (otherwise cmd closes instantly and the user sees nothing).
if not "%RC%"=="0" (
    echo.
    pause
)

exit /b %RC%
