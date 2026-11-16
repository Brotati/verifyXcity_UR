@echo off
title Verify to City Bank Automation Launcher
cls

echo ======================================================================
echo           Verify -^> City Bank CPV Document Automation
echo ======================================================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found in .venv
    echo Please ensure Python setup is completed first.
    pause
    exit /b 1
)

echo Select an operation to perform:
echo.
echo   [1] Inspect Today's Queue (Safe Read-Only Check)
echo   [2] Prepare 1 Test Package (Verify Download + Visual Review)
echo   [3] Prepare Today's Entire Queue
echo   [4] Supervised Upload to City Bank (Zero Bank Save)
echo   [5] Clear Today's Checkpoint (Start Fresh)
echo   [6] Exit
echo.
echo ======================================================================
set /p choice="Enter your choice (1-6): "

if "%choice%"=="1" (
    echo.
    echo [STARTING] Inspect Mode...
    .\.venv\Scripts\python.exe daily_runner.py --mode inspect --date 2026-11-12
) else if "%choice%"=="2" (
    echo.
    echo [STARTING] Prepare 1 File...
    .\.venv\Scripts\python.exe daily_runner.py --mode prepare --limit 1 --date 2026-11-12
) else if "%choice%"=="3" (
    echo.
    echo [STARTING] Prepare Entire Queue...
    .\.venv\Scripts\python.exe daily_runner.py --mode prepare --date 2026-11-12
) else if "%choice%"=="4" (
    echo.
    echo [STARTING] Supervised Upload...
    .\.venv\Scripts\python.exe daily_runner.py --mode run --limit 1 --date 2026-11-12
) else if "%choice%"=="5" (
    echo.
    echo Clearing checkpoint for 2026-11-12...
    if exist "runs\daily\2026-11-12" (
        rd /s /q "runs\daily\2026-11-12"
        echo Checkpoint cleared successfully. You can now start fresh.
    ) else (
        echo No existing checkpoint found.
    )
) else if "%choice%"=="6" (
    exit /b 0
) else (
    echo.
    echo [INVALID] Invalid selection.
)

echo.
echo ======================================================================
echo Execution finished. Press any key to exit...
pause >nul
