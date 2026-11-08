@echo off
chcp 65001 >nul
title WOS Merge Tool
echo ========================================
echo WOS Literature Merge Script
echo ========================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in the system PATH.
    pause
    exit /b
)

python ./Script/merge_wos.py

echo.
echo Process finished.
pause