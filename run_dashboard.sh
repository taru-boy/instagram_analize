#!/bin/bash
BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "ダッシュボードを起動します..."
echo "同じWiFiのスマホから http://$(hostname -I | awk '{print $1}'):8501 でアクセスできます"
echo "終了するには Ctrl+C を押してください"
echo ""
"$BASE_DIR/.venv/bin/streamlit" run "$BASE_DIR/src/dashboard.py" \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --browser.gatherUsageStats false
