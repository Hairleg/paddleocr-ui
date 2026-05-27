#!/bin/bash
# Author: sizhchan
# Org: dgaudit
# Version: v0.1
# Date: 2026-05-27

#!/bin/bash
# PaddleOCR UI 一键复活
# 用法: bash /mnt/workspace/project/paddleocr-ui/revive.sh
set -e

TOOL=/mnt/workspace/tool
ENV_FILE=/mnt/workspace/env/paddleocr-ui.sh
PROJECT=/mnt/workspace/project/paddleocr-ui

echo "=== 1. 加载环境变量 ==="
if [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
    echo "   ✅ $ENV_FILE"
else
    echo "   ❌ $ENV_FILE 不存在"
    exit 1
fi

echo "=== 2. 检查系统依赖 ==="
check_pkg() { python3 -c "import $1" 2>/dev/null || echo "$2"; }
MISSING=""
MISSING="$MISSING $(check_pkg torch torch)"
MISSING="$MISSING $(check_pkg paddle paddlepaddle)"
MISSING="$MISSING $(check_pkg paddleocr paddleocr)"
MISSING="$MISSING $(check_pkg fitz PyMuPDF)"
MISSING="$MISSING $(check_pkg cv2 opencv-contrib-python)"
MISSING="$MISSING $(check_pkg rapid_table rapid_table)"
MISSING="$MISSING $(check_pkg rapidocr_onnxruntime rapidocr_onnxruntime)"
MISSING="$MISSING $(check_pkg magic_pdf magic-pdf)"
MISSING="$MISSING $(check_pkg ultralytics ultralytics)"
MISSING="$MISSING $(check_pkg docx python-docx)"
MISSING="$MISSING $(check_pkg openpyxl openpyxl)"
MISSING="$MISSING $(check_pkg fastapi fastapi)"
MISSING=$(echo "$MISSING" | xargs)

if [ -n "$MISSING" ]; then
    echo "   安装: $MISSING"
    pip3 install -q $MISSING bcrypt==4.0.1
else
    echo "   ✅ 全部就绪"
fi

echo "=== 3. 模型软链（/root → /mnt/workspace/tool）==="
mkdir -p /root/.paddlex /root/.magic-pdf

# PaddleOCR models
if [ -d "$TOOL/models/paddleocr" ]; then
    ln -sfn "$TOOL/models/paddleocr" /root/.paddlex/official_models
    echo "   ✅ paddleocr"
fi

# MinerU layout model
if [ -d "$TOOL/models/mineru" ]; then
    ln -sfn "$TOOL/models/mineru" /root/.magic-pdf/models
    ln -sf "$TOOL/config/magic-pdf.json" /root/magic-pdf.json
    echo "   ✅ mineru"
fi

# RapidTable model
SP=/usr/local/lib/python3.11/site-packages
if [ -d "$TOOL/models/rapid_table" ]; then
    rm -rf "$SP/rapid_table/models"
    ln -sfn "$TOOL/models/rapid_table" "$SP/rapid_table/models"
    echo "   ✅ rapid_table"
fi

# RapidOCR models
if [ -d "$TOOL/models/rapidocr" ]; then
    rm -rf "$SP/rapidocr/models"
    ln -sfn "$TOOL/models/rapidocr" "$SP/rapidocr/models"
    echo "   ✅ rapidocr"
fi

echo "=== 4. 启动服务 ==="
cd "$PROJECT"
fuser -k 8000/tcp 2>/dev/null || true
mkdir -p app/uploads app/data

python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level error &
PID=$!
sleep 3

if kill -0 $PID 2>/dev/null && curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "   ✅ 服务已启动 (PID $PID)"
    echo "   🌐 http://localhost:8000"
else
    echo "   ❌ 启动失败"
    exit 1
fi

echo ""
echo "=== 复活完成 ==="
