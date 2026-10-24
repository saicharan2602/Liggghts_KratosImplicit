@echo off
rem =============================================================================
rem  STOP.bat -- the Kratos server finishes the current window and exits; then close LIGGGHTS
rem =============================================================================
call "%~dp000_SETTINGS.bat"
echo stop> "%DDK_ROOT%\STATUS\STOP"
echo STATUS\STOP written. The next cmd call returns non-zero; LIGGGHTS stops after its retries.
pause
