@echo off
rem =============================================================================
rem  03_BULK_ANALYSIS.bat -- the 'cmd' of fix mesh/surface/stress/fem, once per 1 ms window
rem =============================================================================
rem  fem_cmd.py hands window N to the resident server and returns 0 when CSV\NODE_COORD_N.csv
rem  and STATUS\DONE_N exist (non-zero on FAILED, stale heartbeat or planned stop). LOG\cmd.log
call "%~dp000_SETTINGS.bat"
"%PYTHON_EXE%" "%DDK_ROOT%\KRATOS\fem_cmd.py" %*
exit /b %ERRORLEVEL%
