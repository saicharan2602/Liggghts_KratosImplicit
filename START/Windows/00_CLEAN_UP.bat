@echo off
rem =============================================================================
rem  00_CLEAN_UP.bat -- called by LIGGGHTS at the start (in_DRAW_DOWN_KRATOS.lmp l. 15)
rem =============================================================================
rem  One run per folder: never deletes results. If CSV\ holds NODE_COORD files it stops;
rem  otherwise it removes what a failed start may have left (STATUS, FORCES, laser.csv)
rem  and creates the folders.
call "%~dp000_SETTINGS.bat"
if exist "%DDK_ROOT%\CSV\NODE_COORD_*.csv" (
    echo ERROR: CSV\ already holds NODE_COORD files - copy the folder for a new run
    exit /b 1
)
for %%D in (STL CSV FORCES STATUS LOG RESULTS LIGGGHTS\post LIGGGHTS\POST LIGGGHTS\MEASUREMENT) do (
    if not exist "%DDK_ROOT%\%%D\" mkdir "%DDK_ROOT%\%%D"
)
del /q "%DDK_ROOT%\STATUS\*" "%DDK_ROOT%\FORCES\*" "%DDK_ROOT%\RESULTS\laser.csv" >nul 2>nul
echo ## Kratos: folders ready ##
exit /b 0
