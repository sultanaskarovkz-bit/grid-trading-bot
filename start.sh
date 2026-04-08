#!/bin/bash
echo ""
echo "============================================================"
echo "  GRID TRADING BOT - Запуск панели управления"
echo "============================================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  [ОШИБКА] Python не найден!"
    echo "  Установи: brew install python3"
    echo "  Или скачай с https://python.org"
    exit 1
fi

echo "  [1/3] Python найден:"
python3 --version
echo ""

# Install dependencies
echo "  [2/3] Установка зависимостей..."
pip3 install pandas numpy yfinance optuna matplotlib scipy requests streamlit plotly --quiet 2>/dev/null
echo "  [OK] Зависимости установлены"
echo ""

# Launch dashboard
echo "  [3/3] Открываю панель управления в браузере..."
echo "  (Для остановки нажми Ctrl+C)"
echo ""
streamlit run dashboard.py --server.headless false --theme.base light
