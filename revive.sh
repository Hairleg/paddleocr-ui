#!/bin/bash
# Author: sizhchan
# Org: dgaudit
# Version: v0.1.2
# Date: 2026-06-01

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
MISSING="$MISSING $(check_pkg rapidocr rapidocr)"
MISSING="$MISSING $(check_pkg rapidocr_onnxruntime rapidocr_onnxruntime)"
MISSING="$MISSING $(check_pkg doclayout_yolo doclayout-yolo)"
MISSING="$MISSING $(check_pkg magic_pdf magic-pdf)"
MISSING="$MISSING $(check_pkg docx python-docx)"
MISSING="$MISSING $(check_pkg openpyxl openpyxl)"
MISSING="$MISSING $(check_pkg fastapi fastapi)"
MISSING=$(echo "$MISSING" | xargs)

if [ -n "$MISSING" ]; then
    echo "   安装: $MISSING"
    pip3 install -q $MISSING bcrypt==4.0.1 'numpy<2.0'
else
    echo "   ✅ 全部就绪"
fi

# Pin paddlepaddle to 3.0.0 (3.3.x has PIR compatibility issues)
PY_PADDLE_VER=$(python3 -c "import paddle; print(paddle.__version__)" 2>/dev/null || echo "none")
if [ "$PY_PADDLE_VER" != "3.0.0" ]; then
    echo "   ⚠️ Paddle $PY_PADDLE_VER → downgrading to 3.0.0"
    pip3 install -q paddlepaddle==3.0.0 --force-reinstall
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


echo ""
echo "=== 复活完成 ==="
