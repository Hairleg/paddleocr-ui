#!/bin/bash
# Author: sizhchan
# Org: dgaudit
# Version: v0.1.2
# Date: 2026-06-01
#
# PaddleOCR UI 一键复活脚本
# 用法: bash revive.sh
# 用途: 环境重置后恢复所有依赖、模型软链、启动服务

TOOL=/mnt/workspace/tool
ENV_FILE=/mnt/workspace/env/paddleocr-ui.sh
PROJECT=/mnt/workspace/project/paddleocr-ui
SP=/usr/local/lib/python3.11/site-packages

echo "╔══════════════════════════════════════════╗"
echo "║   PaddleOCR UI v0.1.2 — 环境恢复脚本    ║"
echo "╚══════════════════════════════════════════╝"

# ── 1. 加载环境变量 ──
echo ""
echo "=== 1. 加载环境变量 ==="
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
    echo "   ✅ $ENV_FILE"
else
    echo "   ❌ $ENV_FILE 不存在，退出"
    exit 1
fi

# ── 2. Python 包依赖 ──
echo ""
echo "=== 2. 检查 Python 包 ==="
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
MISSING="$MISSING $(check_pkg aiosqlite aiosqlite)"
MISSING="$MISSING $(check_pkg fastapi fastapi)"
MISSING="$MISSING $(check_pkg uvicorn uvicorn)"
MISSING="$MISSING $(check_pkg jose python-jose)"
MISSING="$MISSING $(check_pkg passlib passlib)"
MISSING="$MISSING $(check_pkg bcrypt bcrypt)"
MISSING="$MISSING $(check_pkg aiofiles aiofiles)"
MISSING="$MISSING $(check_pkg multipart python-multipart)"
MISSING=$(echo "$MISSING" | xargs)


if [ -n "$MISSING" ]; then
    echo "   安装: $MISSING"
    pip3 install -q $MISSING 'bcrypt==4.0.1'
    echo "   ✅ 安装完成"
else
    echo "   ✅ 全部就绪"
fi

# ── 3. Paddle 版本锁定 ──
echo ""
echo "=== 3. PaddlePaddle 版本检查 ==="
PY_PADDLE_VER=$(python3 -c "import paddle; print(paddle.__version__)" 2>/dev/null || echo "none")
if [ "$PY_PADDLE_VER" != "3.0.0" ]; then
    echo "   ⚠️  当前 $PY_PADDLE_VER → 降级到 3.0.0（避免 PIR 兼容性问题）"
    pip3 install -q paddlepaddle==3.0.0 --force-reinstall
    echo "   ✅ PaddlePaddle 3.0.0"

# ── numpy 兼容性 ──
pip3 install -q 'numpy<2.0' --force-reinstall
echo "   ✅ numpy $(python3 -c "import numpy;print(numpy.__version__)" 2>/dev/null)"
else
    echo "   ✅ PaddlePaddle 3.0.0"
fi

# ── 4. 模型软链 ──
echo ""
echo "=== 4. 模型软链 ==="
mkdir -p /root/.paddlex /root/.magic-pdf

# PaddleOCR models
if [ -d "$TOOL/models/paddleocr" ]; then
    ln -sfn "$TOOL/models/paddleocr" /root/.paddlex/official_models
    echo "   ✅ paddleocr"
else
    echo "   ⚠️  paddleocr 模型目录不存在"
fi

# MinerU layout model
if [ -d "$TOOL/models/mineru" ]; then
    ln -sfn "$TOOL/models/mineru" /root/.magic-pdf/models
    if [ -f "$TOOL/config/magic-pdf.json" ]; then
        ln -sf "$TOOL/config/magic-pdf.json" /root/magic-pdf.json
    fi
    echo "   ✅ mineru"
else
    echo "   ⚠️  mineru 模型目录不存在"
fi

# YOLO model check
if [ -f "$MINERU_LAYOUT_MODEL" ]; then
    echo "   ✅ YOLO 模型: $MINERU_LAYOUT_MODEL"
else
    echo "   ❌ YOLO 模型缺失: $MINERU_LAYOUT_MODEL"
fi

# RapidTable model
if [ -d "$TOOL/models/rapid_table" ]; then
    rm -rf "$SP/rapid_table/models"
    ln -sfn "$TOOL/models/rapid_table" "$SP/rapid_table/models"
    echo "   ✅ rapid_table"
else
    echo "   ⚠️  rapid_table 模型目录不存在"
fi

# RapidOCR models
if [ -d "$TOOL/models/rapidocr" ]; then
    rm -rf "$SP/rapidocr/models" 2>/dev/null
    ln -sfn "$TOOL/models/rapidocr" "$SP/rapidocr/models" 2>/dev/null
    rm -rf "$SP/rapidocr_onnxruntime/models" 2>/dev/null
    ln -sfn "$TOOL/models/rapidocr" "$SP/rapidocr_onnxruntime/models" 2>/dev/null
    echo "   ✅ rapidocr"
else
    echo "   ⚠️  rapidocr 模型目录不存在"
fi

# ── 5. 启动服务 ──
echo ""
echo "=== 5. 启动服务 ==="
cd "$PROJECT"

# 清理旧进程
pkill -f "uvicorn app.main:app" 2>/dev/null || true
sleep 1

# 启动（后台运行）
export OMP_NUM_THREADS=32
export MKL_NUM_THREADS=32
export PADDLE_PDX_INFER_WORKER_NUM=32
nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    > /tmp/paddleocr-ui.log 2>&1 &
PID=$!
echo "   ✅ 服务已启动 (PID=$PID)"
echo "   日志: /tmp/paddleocr-ui.log"

# ── 6. 验证 ──
echo ""
echo "=== 6. 验证服务 ==="
sleep 3
if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    echo "   ✅ 健康检查通过"
    echo ""
    echo "╔══════════════════════════════════════════╗"
    echo "║   PaddleOCR UI 已就绪                    ║"
    echo "║   访问: http://localhost:8000            ║"
    echo "║   管理员: admin / admin123               ║"
    echo "║   停止: pkill -f 'uvicorn app.main'      ║"
    echo "╚══════════════════════════════════════════╝"
else
    echo "   ⚠️  健康检查未通过，请检查日志:"
    tail -20 /tmp/paddleocr-ui.log
fi
