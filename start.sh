#!/bin/bash
echo ""
echo "    ========================================"
echo "         Grid Trading Bot v1.0"
echo "    ========================================"
echo ""
echo "    Запуск... подождите 10-15 секунд"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "    [!] Python не найден."
    echo ""
    echo "    Установи: brew install python3"
    echo "    Или скачай с https://python.org"
    exit 1
fi

# Install dependencies
echo "    [1/2] Проверяю зависимости..."
pip3 install -r requirements.txt --quiet 2>/dev/null
echo "    [OK] Готово"
echo ""

echo "    [2/2] Открываю панель управления..."
echo ""
echo "    Панель откроется в браузере автоматически."
echo "    Если не открылась - перейди на http://localhost:8501"
echo ""
echo "    Чтобы остановить - нажми Ctrl+C"
echo ""

# Open browser and run
open http://localhost:8501 2>/dev/null || xdg-open http://localhost:8501 2>/dev/null &
streamlit run dashboard.py --server.headless true --browser.gatherUsageStats false
