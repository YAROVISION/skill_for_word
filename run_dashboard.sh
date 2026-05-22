#!/bin/bash
# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

# Run streamlit
echo "🚀 Запуск Word Abstraction Level Dashboard..."
python3 -m streamlit run dashboard/app.py
