@echo off
setlocal

:: MaLing (码铃) - Windows launcher (encoding-safe)
:: This tiny wrapper calls the Python launcher, which works on
:: any code page / any locale. No Unicode text in this file.
:: Version comes from core/__init__.py via run.py (single source).

where python >nul 2>&1
if not errorlevel 1 (
    python "%~dp0run.py" %*
    goto :eof
)

where python3 >nul 2>&1
if not errorlevel 1 (
    python3 "%~dp0run.py" %*
    goto :eof
)

echo.
echo  [X] Python not found on this computer.
echo.
echo  Please run install.bat first, or install Python 3.10+.
echo.
echo  https://www.python.org/downloads/
echo.
echo  Press any key to exit...
pause >nul
