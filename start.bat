@echo off
chcp 65001 >nul 2>&1
echo.
echo ============================================================
echo   GRID TRADING BOT - Запуск панели управления
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo   [ОШИБКА] Python не найден!
    echo   Скачайте Python 3.11+ с https://python.org
    echo   При установке поставьте галочку "Add to PATH"
    pause
    exit /b 1
)

:: Install dependencies
echo   Проверка зависимостей...
pip install pandas numpy yfinance optuna matplotlib scipy requests streamlit plotly --quiet 2>nul
echo   [OK] Зависимости установлены
echo.

:: Launch dashboard
echo   Открываю панель управления в браузере...
echo   (Для остановки нажмите Ctrl+C в этом окне)
echo.
streamlit run dashboard.py --server.headless false --theme.base light

pause
