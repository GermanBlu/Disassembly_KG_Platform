@echo off
REM Cross-platform entry point for Windows. Delegates to run.py so the OS
REM detection and PYTHONPATH wiring live in one place.

cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
    py -3 run.py %*
    exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
    python run.py %*
    exit /b %ERRORLEVEL%
)

echo No Python interpreter found on PATH. Install Python 3 from python.org.
exit /b 1
