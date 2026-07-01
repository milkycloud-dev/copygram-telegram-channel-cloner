@echo off
echo ========================================================
echo         Telegram Channel Copier - Launcher
echo ========================================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Install Python and add it to PATH.
    pause
    exit /b
)

echo Installing dependencies...
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Failed to install requirements!
    pause
    exit /b
)

echo.
echo Starting app...
python main_flet.py
pause
