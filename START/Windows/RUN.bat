@echo off
rem =============================================================================
rem  RUN.bat [smoke] -- the coupled run: LIGGGHTS-SIMBA (1 process) + resident Kratos server
rem =============================================================================
rem  RUN.bat         full run, 5.2 s = 5199 windows (about one day)
rem  RUN.bat smoke   same chain, the server stops after window 50 on purpose: the next cmd call
rem                  returns non-zero, LIGGGHTS retries 9 times and stops (intended)
rem  One run per folder: refuses to start if CSV\ holds NODE_COORD files.
setlocal
call "%~dp000_SETTINGS.bat"
set "DDK_MAX_WINDOWS=0"
if /i "%~1"=="smoke" set "DDK_MAX_WINDOWS=50"
if not exist "%PYTHON_EXE%" (
    echo ERROR: %PYTHON_EXE% not found - run START\Windows\SETUP_PYTHON.bat first
    pause
    exit /b 1
)
if not exist "%LIGGGHTS_EXE%" (
    echo ERROR: %LIGGGHTS_EXE% not found - see LIGGGHTS_EXE in START\Windows\00_SETTINGS.bat
    pause
    exit /b 1
)
"%PYTHON_EXE%" "%DDK_ROOT%\KRATOS\fem_server.py" preflight
if errorlevel 1 (
    pause
    exit /b 1
)
for %%D in (STL CSV FORCES STATUS LOG RESULTS LIGGGHTS\post LIGGGHTS\POST LIGGGHTS\MEASUREMENT) do (
    if not exist "%DDK_ROOT%\%%D\" mkdir "%DDK_ROOT%\%%D"
)
title LIGGGHTS + Kratos 10.3 implicit draw-down
echo.
echo ===== LIGGGHTS-SIMBA + Kratos 10.3 implicit (Newmark, beta 1e-4) =====
echo   folder   %DDK_ROOT%
echo   windows  %DDK_MAX_WINDOWS% (0 = full run)
echo   watch    LOG\fem_server.log, RESULTS\laser.csv, LOG\cmd.log
echo   stop     START\Windows\STOP.bat, then close this window
echo.
cd /d "%DDK_ROOT%\LIGGGHTS"
"%LIGGGHTS_EXE%" -in in_DRAW_DOWN_KRATOS.lmp -log ..\LOG\liggghts.log
set "RC=%ERRORLEVEL%"
cd /d "%DDK_ROOT%"
echo stop> "%DDK_ROOT%\STATUS\STOP"
echo.
echo ===== LIGGGHTS ended (exit code %RC%), Kratos server told to stop =====
if exist "%DDK_ROOT%\RESULTS\laser.csv" "%PYTHON_EXE%" "%DDK_ROOT%\KRATOS\plot_results.py"
pause
endlocal
