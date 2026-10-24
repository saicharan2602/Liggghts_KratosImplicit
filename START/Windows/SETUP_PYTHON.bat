@echo off
rem =============================================================================
rem  SETUP_PYTHON.bat -- once per PC: <ROOT>\.venv with Kratos 10.3.0 (needs internet, 5-10 min)
rem =============================================================================
rem  Same pin as the beam coupling (SimBa_Kratos_Ver1\requirements.txt). Never upgrade Kratos.
rem  A .venv cannot be copied between PCs: run this on every PC the folder is copied to.
setlocal
call "%~dp000_SETTINGS.bat"
if exist "%PYTHON_EXE%" (
    echo .venv already exists: %PYTHON_EXE%
    "%PYTHON_EXE%" -m pip show KratosMultiphysics | findstr /b "Name Version"
    echo To rebuild it, delete the folder %DDK_ROOT%\.venv and start this file again.
    pause
    exit /b 0
)
echo Creating %DDK_ROOT%\.venv with %BASE_PYTHON% ...
%BASE_PYTHON% -m venv "%DDK_ROOT%\.venv"
if errorlevel 1 goto :fail
"%PYTHON_EXE%" -m pip install "KratosMultiphysics-all==10.3.0" numpy matplotlib
if errorlevel 1 goto :fail
"%PYTHON_EXE%" -m pip show KratosMultiphysics | findstr /b "Name Version"
echo.
echo Done. Next: START\Windows\CHECK.bat
pause
exit /b 0

:fail
echo ERROR: setup failed. Check BASE_PYTHON in START\Windows\00_SETTINGS.bat (a Python 3.12 is known to work).
pause
exit /b 1
