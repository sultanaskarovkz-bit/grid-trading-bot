#!/bin/bash
cd "$(dirname "$0")"

echo ""
echo "    ========================================"
echo "         Grid Trading Bot v1.0"
echo "    ========================================"
echo ""

# --- Step 1: Find or install Python ---
if command -v python3 &> /dev/null; then
    PY=python3
elif command -v python &> /dev/null; then
    PY=python
else
    echo "    Python не найден. Устанавливаю..."
    echo ""

    # Try Homebrew first
    if command -v brew &> /dev/null; then
        echo "    Установка через Homebrew..."
        brew install python3
        PY=python3
    else
        # Install Xcode command line tools (includes Python on newer macOS)
        echo "    Устанавливаю инструменты разработчика (нужно для Python)..."
        echo "    Если появится окно - нажмите 'Установить' и подождите."
        echo ""
        xcode-select --install 2>/dev/null

        # Wait for xcode-select to finish
        echo "    Ожидаю завершения установки..."
        until xcode-select -p &>/dev/null; do
            sleep 5
        done

        # Check again
        if command -v python3 &> /dev/null; then
            PY=python3
        else
            # Last resort: download Python installer
            echo ""
            echo "    Скачиваю Python с python.org..."
            PYTHON_PKG="/tmp/python-installer.pkg"
            curl -L -o "$PYTHON_PKG" "https://www.python.org/ftp/python/3.12.4/python-3.12.4-macos11.pkg" 2>/dev/null

            if [ -f "$PYTHON_PKG" ]; then
                echo "    Запускаю установщик Python..."
                echo "    Следуйте инструкциям в установщике."
                echo ""
                open "$PYTHON_PKG"

                # Wait until python3 appears
                echo "    Ожидаю завершения установки Python..."
                for i in $(seq 1 60); do
                    sleep 5
                    if command -v python3 &> /dev/null || command -v /usr/local/bin/python3 &> /dev/null || command -v /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 &> /dev/null; then
                        break
                    fi
                done

                # Try all known paths
                if command -v python3 &> /dev/null; then
                    PY=python3
                elif [ -f /usr/local/bin/python3 ]; then
                    PY=/usr/local/bin/python3
                elif [ -f /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 ]; then
                    PY=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3
                    export PATH="/Library/Frameworks/Python.framework/Versions/3.12/bin:$PATH"
                else
                    echo ""
                    echo "    Не удалось найти Python после установки."
                    echo "    Закройте это окно, перезагрузите Mac и запустите снова."
                    echo ""
                    read -p "    Нажмите Enter для выхода..."
                    exit 1
                fi
            else
                echo "    Не удалось скачать Python."
                echo "    Установите вручную: https://python.org/downloads"
                open "https://python.org/downloads"
                read -p "    Нажмите Enter для выхода..."
                exit 1
            fi
        fi
    fi

    echo ""
    echo "    Python установлен!"
fi

echo "    Python: $($PY --version 2>&1)"
echo ""

# --- Step 2: Install dependencies ---
echo "    Устанавливаю компоненты (первый раз может занять 1-2 минуты)..."
$PY -m pip install -r requirements.txt --quiet 2>/dev/null
echo "    Готово!"
echo ""

# --- Step 3: Launch ---
echo "    Запускаю панель управления..."
echo "    Браузер откроется автоматически."
echo ""
echo "    Чтобы остановить бота - закройте это окно."
echo ""

sleep 2 && open http://localhost:8501 &
$PY -m streamlit run dashboard.py --server.headless true --browser.gatherUsageStats false
