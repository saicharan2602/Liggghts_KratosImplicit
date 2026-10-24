@echo off
rem =============================================================================
rem  01_STL_DERIVATION.bat -- called by LIGGGHTS (in_DRAW_DOWN_KRATOS.lmp l. 31)
rem =============================================================================
rem  Writes STL\NODE_COORD_0.stl, starts the resident Kratos server (fem_server.py serve)
rem  detached and waits until it reports READY (max. 300 s). Log: LOG\stl_derivation.log
call "%~dp000_SETTINGS.bat"
"%PYTHON_EXE%" "%DDK_ROOT%\KRATOS\fem_server.py" launch
if errorlevel 1 (
    echo ERROR: Kratos server not READY - see LOG\stl_derivation.log and LOG\fem_server.log
    exit /b 1
)
exit /b 0
