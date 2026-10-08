@echo off
setlocal

set SCRIPT=STM32_Timer

echo.
echo ===============================
echo Building %SCRIPT%.exe
echo ===============================
echo.

:: --------------------------------------------------
:: Build Application
:: --------------------------------------------------
python -m PyInstaller --onefile --clean --noconfirm --name %SCRIPT% %SCRIPT%.py
if errorlevel 1 (
    echo.
    echo ERROR: Build failed. Install requirements with: pip install pyinstaller numpy
    goto cleanup
)

:: --------------------------------------------------
:: Move Executable next to the script
:: --------------------------------------------------
move /Y "dist\%SCRIPT%.exe" "%SCRIPT%.exe" >nul

echo.
echo =====================================
echo Build completed: %SCRIPT%.exe
echo =====================================

:: --------------------------------------------------
:: Cleanup (keep only the exe)
:: --------------------------------------------------
:cleanup
if exist build rmdir /S /Q build
if exist dist rmdir /S /Q dist
if exist %SCRIPT%.spec del /Q %SCRIPT%.spec
if exist __pycache__ rmdir /S /Q __pycache__

pause
