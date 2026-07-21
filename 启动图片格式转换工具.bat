@echo off
setlocal EnableExtensions

cd /d "%~dp0"

set "PYTHON_CMD="

where pyw >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=pyw -3"
)

if not defined PYTHON_CMD (
  where pythonw >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=pythonw"
  )
)

if not defined PYTHON_CMD (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=py -3"
  )
)

if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=python"
  )
)

if not defined PYTHON_CMD (
  echo Python was not found.
  echo Please install Python 3, or add python.exe to PATH.
  echo.
  pause
  exit /b 1
)

start "" %PYTHON_CMD% "%~dp0image_converter_gui.py"

if errorlevel 1 (
  echo.
  echo Failed to start image converter.
  echo Please make sure Pillow is installed:
  echo   %PYTHON_CMD% -m pip install pillow
  echo.
  pause
  exit /b 1
)
