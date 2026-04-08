#!/bin/bash
cd "$(dirname "$0")"

# Check Python
if command -v python3 &> /dev/null; then
    PY=python3
elif command -v python &> /dev/null; then
    PY=python
else
    osascript -e 'display dialog "Python не установлен.\n\nСкачайте с https://python.org\nили установите через brew install python3" with title "Grid Trading Bot" buttons {"OK"} default button "OK"'
    open "https://python.org/downloads"
    exit 1
fi

# Install dependencies
$PY -m pip install -r requirements.txt --quiet 2>/dev/null

# Open browser and run
sleep 2 && open http://localhost:8501 &
$PY -m streamlit run dashboard.py --server.headless true --browser.gatherUsageStats false
