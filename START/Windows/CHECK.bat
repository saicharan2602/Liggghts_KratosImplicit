@echo off
rem =============================================================================
rem  CHECK.bat [formats|static|modal] -- checks 1-3 before the run (< 5 min), RESULTS\checks.txt
rem =============================================================================
setlocal
call "%~dp000_SETTINGS.bat"
if not exist "%PYTHON_EXE%" (
    echo ERROR: %PYTHON_EXE% not found - run START\Windows\SETUP_PYTHON.bat first
    pause
    exit /b 1
)
"%PYTHON_EXE%" "%DDK_ROOT%\KRATOS\check.py" %*
pause
