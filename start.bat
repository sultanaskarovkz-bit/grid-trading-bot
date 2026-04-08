@echo off
chcp 65001 >nul 2>&1
title Grid Trading Bot

echo.
echo    ========================================
echo         Grid Trading Bot v1.0
echo    ========================================
echo.
echo    Запуск... подождите 10-15 секунд
echo.

:: Check Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    [!] Python не найден.
    echo.
    echo    Скачайте Python с https://python.org/downloads
    echo    При установке поставьте галочку "Add to PATH"
    echo.
    pause
    exit /b 1
)

:: Install dependencies silently
echo    [1/2] Проверяю зависимости...
pip install -r requirements.txt --quiet >nul 2>&1
echo    [OK] Готово
echo.

:: Launch dashboard and open browser
echo    [2/2] Открываю панель управления...
echo.
echo    Панель откроется в браузере автоматически.
echo    Если не открылась - перейдите на http://localhost:8501
echo.
echo    Чтобы остановить - закройте это окно.
echo.

start "" http://localhost:8501
streamlit run dashboard.py --server.headless true --browser.gatherUsageStats false 2>nul
