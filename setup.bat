@echo off
chcp 65001 >nul 2>&1
echo.
echo ============================================================
echo   УСТАНОВКА TRADING BOT
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo   [ОШИБКА] Python не найден!
    echo   Скачайте Python 3.11+ с https://python.org
    pause
    exit /b 1
)

echo   [1/3] Python найден:
python --version
echo.

:: Install dependencies
echo   [2/3] Установка зависимостей...
pip install pandas numpy yfinance optuna matplotlib scipy --quiet
echo   [OK] Зависимости установлены
echo.

:: Run demo
echo   [3/3] Запуск демонстрации...
echo.
python demo.py

pause
