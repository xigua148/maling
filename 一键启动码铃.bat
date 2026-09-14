@echo off
chcp 65001 >nul
cd /d "%~dp0"

rem ==========================================================
rem   MaLing Maid - One-Click Launcher
rem   Double-click this file. Everything else is automatic.
rem ==========================================================

echo ==========================================
echo   MaLing Maid - One-Click Launcher
echo ==========================================
echo.

rem ---- locate python (python or py) ----
set "PYCMD=python"
where python >nul 2>nul
if errorlevel 1 set "PYCMD=py"

rem ---- first run: install dependencies into venv ----
if not exist "venv\Scripts\python.exe" (
    echo [1/2] First run detected. Installing dependencies...
    echo       This can take a few minutes. Please wait...
    echo.
    %PYCMD% install.py
    if errorlevel 1 (
        echo.
        echo [ERROR] Install failed.
        echo Please install Python 3.10+ first from:
        echo   https://www.python.org/downloads/
        echo IMPORTANT: during setup tick "Add python.exe to PATH".
        echo Then double-click this file again.
        echo.
        pause
        exit /b 1
    )
) else (
    echo [1/2] Dependencies already installed.
)

echo.
echo [2/2] Launching MaLing...
echo       Tip: after launch, fill your API Key via the
echo       "Model Status" button at the bottom of the sidebar.
echo.
"venv\Scripts\python.exe" run.py
if errorlevel 1 (
    echo.
    echo MaLing closed with an error. Screenshot this window and
    echo send it to whoever gave you this folder.
    echo.
    pause
)
