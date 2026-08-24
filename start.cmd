@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%CD%\.venv-gui\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo Creating the project Python environment...
  py -3 -m venv .venv-gui
  if errorlevel 1 goto :failed
)

"%PYTHON%" -c "import PySide6, Crypto, frida, PIL, pywinauto, reportlab, zstandard" >nul 2>&1
if errorlevel 1 (
  echo Installing project dependencies...
  "%PYTHON%" -m pip install -e ".[gui]"
  if errorlevel 1 goto :failed
)

"%PYTHON%" app.py
if errorlevel 1 goto :failed
exit /b 0

:failed
echo.
echo The application could not start. See the error above.
pause
exit /b 1
