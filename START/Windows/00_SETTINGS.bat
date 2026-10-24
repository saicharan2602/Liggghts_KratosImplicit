@echo off
rem =============================================================================
rem  00_SETTINGS.bat -- the only machine-specific file. Called by every other batch file.
rem =============================================================================
rem  DDK_ROOT comes from the location of this file: the folder can be copied anywhere.
for %%I in ("%~dp0..\..") do set "DDK_ROOT=%%~fI"

rem  Python used ONCE by SETUP_PYTHON.bat to create .venv (Kratos 10.3.0 wheels: e.g. Python 3.12).
rem  "py -3.12" (Python launcher) or a full path such as C:\Program Files\Python312\python.exe
set "BASE_PYTHON=py -3.12"

rem  Python with Kratos 10.3.0 -- created by SETUP_PYTHON.bat
set "PYTHON_EXE=%DDK_ROOT%\.venv\Scripts\python.exe"

rem  LIGGGHTS-SIMBA 4.1.1 (with its vtk*.dll), run WITHOUT mpiexec = 1 process
set "LIGGGHTS_EXE=%DDK_ROOT%\LIGGGHTS\bin\liggghts_4p1p1_TCP_IP.exe"

rem  single core everywhere
set "OMP_NUM_THREADS=1"
set "MKL_NUM_THREADS=1"
set "OPENBLAS_NUM_THREADS=1"
set "PYTHONUNBUFFERED=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONIOENCODING=utf-8"
