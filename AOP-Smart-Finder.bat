@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
SETLOCAL ENABLEDELAYEDEXPANSION

:: ============================================================
:: 1. Check if Python is installed
:: ============================================================
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo.
    echo ❌ Python is not installed or not in PATH.
    echo    Please install Python 3.8+ from:
    echo      https://www.python.org/downloads/
    echo    IMPORTANT: During installation, check "Add Python to PATH".
    echo.
    pause
    exit /b
)

echo.
echo Python detected:
python --version

echo [INFO] Checking Python dependencies...
python -c "import openai, pandas, networkx, openpyxl, lxml" 2>nul
IF ERRORLEVEL 1 (
    echo [INFO] Some dependencies are missing. Installing from ./Script/requirements.txt ...
    python -m pip install --upgrade pip
    python -m pip install -r "./Script/requirements.txt"
    IF ERRORLEVEL 1 (
        echo.
        echo ❌ Failed to install dependencies.
        echo    Please check your network / pip configuration, or run manually:
        echo      python -m pip install -r "./Script/requirements.txt"
        pause
        exit /b
    )
    echo  Dependencies installed.
) ELSE (
    echo All Python dependencies are already installed.
)


echo ====================================================
echo [PREPARATION]
echo Please ensure your WoS-exported Excel files are in the current folder.
echo.
echo NOTES:
echo   - Mode 1 (compound-based): the file name MUST exactly match
echo     the compound name to be processed, e.g. DEHP.xlsx
echo   - Mode 2 (file-based): file name does NOT matter,
echo     just use the downloaded file name as-is.
echo.
echo [AVAILABLE FILES] Found in current folder:
echo ----------------------------------------------------
for %%f in (*.xlsx *.xls) do echo   -^> %%~nf
echo ====================================================
echo.
set /p INPUT_WORD=Please type the EXACT compound name from the list above (WITHOUT .xlsx): 

set INPUT_WORD=!INPUT_WORD!

:: 1 Check if Python is installed
python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo ❌ Python is not installed. Please install Python first.
    pause
    exit /b
)

:: 2 Check openai
python -c "import openai" 2>nul || (
    echo openai library not found. Installing...
    python -m pip install openai
)

:: 3 Check AOP-Smart.json
IF NOT EXIST "./File/AOP-Smart.json" (
    IF EXIST "./File/aop-wiki.xml" (
        echo Running XML_analysis.py ...
        python ./Script/XML_analysis.py
    ) ELSE (
        echo ❌ aop-wiki.xml not found. Cannot continue.
        pause
        exit /b
    )
)

:: 4 Check input file
set "INPUT_FILE=!INPUT_WORD!"

:: 检查输入是否已经包含了 .xls 或 .xlsx 后缀
if /I not "!INPUT_FILE:~-4!"==".xls" if /I not "!INPUT_FILE:~-5!"==".xlsx" (
    :: 如果没有后缀，先尝试找 .xls
    if exist "!INPUT_WORD!.xls" (
        set "INPUT_FILE=!INPUT_WORD!.xls"
    ) else (
        :: 如果 .xls 也没有，再尝试找 .xlsx
        if exist "!INPUT_WORD!.xlsx" (
            set "INPUT_FILE=!INPUT_WORD!.xlsx"
        ) else (
            :: 如果两个都没有，默认还是拼上 .xls，留给下一步报错
            set "INPUT_FILE=!INPUT_WORD!.xls"
        )
    )
)

IF NOT EXIST "!INPUT_FILE!" (
    echo [Error] File "!INPUT_FILE!" not found.
    pause
    exit /b
)

python ./Script/WOS_manage.py
if errorlevel 1 ( echo ❌ WOS_manage.py failed & pause & exit /b )


python ./Script/AOP-Smart-Finder.py
if errorlevel 1 ( echo ❌ AOP-Smart-Finder.py failed & pause & exit /b )


python ./Script/visual.py
if errorlevel 1 ( echo ❌ visual.py failed & pause & exit /b )


echo All done!
pause
