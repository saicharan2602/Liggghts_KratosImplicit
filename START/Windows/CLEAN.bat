@echo off
rem =============================================================================
rem  CLEAN.bat [/y] -- empties every run-output folder, so this folder can take a fresh run
rem =============================================================================
rem  Deletes everything in CSV\, FORCES\, STATUS\, STL\, LOG\, RESULTS\ and LIGGGHTS\post (= POST),
rem  LIGGGHTS\MEASUREMENT, plus LIGGGHTS\warnings.liggghts. Keeps RESULTS\checks.txt,
rem  LOG\lmp_diff.txt and the .gitkeep files. Refuses while the Kratos server of this folder runs.
rem  Asks first; CLEAN.bat /y does not ask.
setlocal
call "%~dp000_SETTINGS.bat"
if exist "%PYTHON_EXE%" (
    "%PYTHON_EXE%" "%DDK_ROOT%\KRATOS\fem_server.py" idle
    if errorlevel 1 goto :fail
)
if /i "%~1"=="/y" goto :clean
echo.
echo This deletes ALL results of the last run in
echo   %DDK_ROOT%
echo (CSV, FORCES, STATUS, STL, LOG, RESULTS, LIGGGHTS\post, LIGGGHTS\MEASUREMENT).
echo Kept: RESULTS\checks.txt, LOG\lmp_diff.txt.
set "ANS="
set /p "ANS=Type YES to delete: "
if /i not "%ANS%"=="YES" (
    echo Nothing deleted.
    goto :end
)

:clean
for %%D in (CSV FORCES STATUS STL LIGGGHTS\post LIGGGHTS\MEASUREMENT) do call :empty "%%D"
call :empty RESULTS checks.txt
call :empty LOG lmp_diff.txt
del /f /q "%DDK_ROOT%\LIGGGHTS\warnings.liggghts" >nul 2>nul
if exist "%DDK_ROOT%\CSV\NODE_COORD_*.csv" goto :locked
if exist "%DDK_ROOT%\STATUS\server.lock" goto :locked
echo ## run folders empty: ready for RUN.bat ##
goto :end

rem  :empty <folder> [file to keep] -- delete files and subfolders, keep .gitkeep (restored if missing)
:empty
if not exist "%DDK_ROOT%\%~1\" mkdir "%DDK_ROOT%\%~1"
for %%F in ("%DDK_ROOT%\%~1\*") do (
    if /i not "%%~nxF"==".gitkeep" if /i not "%%~nxF"=="%~2" del /f /q "%%F"
)
for /d %%S in ("%DDK_ROOT%\%~1\*") do rd /s /q "%%S"
if not exist "%DDK_ROOT%\%~1\.gitkeep" type nul > "%DDK_ROOT%\%~1\.gitkeep"
echo   %~1 emptied
goto :eof

:locked
echo ERROR: some files could not be deleted (still open? close the LIGGGHTS window) - run CLEAN.bat again
:fail
if /i not "%~1"=="/y" pause
endlocal
exit /b 1

:end
if /i not "%~1"=="/y" pause
endlocal
exit /b 0
