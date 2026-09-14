@echo off
setlocal

:: MaLing (码铃) - Windows bootstrap (encoding-safe)
:: This tiny wrapper calls the Python installer, which works on
:: any code page / any locale. No Unicode text in this file.
:: Version comes from core/__init__.py via install.py (single source).

where python >nul 2>&1
if not errorlevel 1 (
    python "%~dp0install.py" %*
    goto :eof
)

where python3 >nul 2>&1
if not errorlevel 1 (
    python3 "%~dp0install.py" %*
    goto :eof
)

echo.
echo  [X] Python not found on this computer.
echo.
echo  MaLing needs Python 3.10 or newer.
echo.
echo  Quick install (Windows):
echo    1. https://www.python.org/downloads/
echo    2. Download Python 3.12 (or 3.11 / 3.10)
echo    3. CHECK "Add Python to PATH" during setup
echo    4. Re-open this window and double-click install.bat again
echo.
echo  Press any key to exit...
pause >nul
