@echo off
chcp 65001 >nul 2>&1
title Grid Trading Bot

echo.
echo    ========================================
echo         Grid Trading Bot v1.0
echo    ========================================
echo.

:: Check Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo    Python не найден. Скачиваю и устанавливаю...
    echo.

    :: Download Python installer
    echo    Скачиваю Python с python.org...
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe' -OutFile '%TEMP%\python-installer.exe'" >nul 2>&1

    if exist "%TEMP%\python-installer.exe" (
        echo    Запускаю установщик Python...
        echo    Следуйте инструкциям в установщике.
        echo    ВАЖНО: поставьте галочку "Add Python to PATH"!
        echo.
        start /wait "" "%TEMP%\python-installer.exe" /passive InstallAllUsers=0 PrependPath=1 Include_test=0
        del "%TEMP%\python-installer.exe" >nul 2>&1

        :: Refresh PATH
        set "PATH=%LOCALAPPDATA%\Programs\Python\Python312\;%LOCALAPPDATA%\Programs\Python\Python312\Scripts\;%PATH%"

        python --version >nul 2>&1
        if %ERRORLEVEL% NEQ 0 (
            echo.
            echo    Python установлен, но нужно перезапустить.
            echo    Закройте это окно и запустите start.bat ещё раз.
            echo.
            pause
            exit /b 1
        )
        echo    Python установлен!
    ) else (
        echo    Не удалось скачать Python.
        echo    Установите вручную: https://python.org/downloads
        echo    При установке поставьте галочку "Add to PATH"
        echo.
        start "" "https://python.org/downloads"
        pause
        exit /b 1
    )
)

echo    Python:
python --version
echo.

:: Install dependencies silently
echo    Устанавливаю компоненты (первый раз 1-2 минуты)...
pip install -r requirements.txt --quiet >nul 2>&1
echo    Готово!
echo.

:: Launch dashboard and open browser
echo    Запускаю панель управления...
echo    Браузер откроется автоматически.
echo.
echo    Чтобы остановить - закройте это окно.
echo.

start "" http://localhost:8501
streamlit run dashboard.py --server.headless true --browser.gatherUsageStats false 2>nul
