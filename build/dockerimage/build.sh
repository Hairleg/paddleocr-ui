#!/bin/bash
# ==============================================================
# PaddleOCR UI Docker 镜像构建脚本
# 在有 Docker 的机器上运行此脚本即可生成可移植镜像
# ==============================================================
set -e

# 解压源码
tar xzf paddleocr-ui_src.tar.gz
cd paddleocr-ui

# 构建镜像
echo "Building image..."
docker build -t paddleocr-ui:v0.2.0 .

# 导出镜像
mkdir -p output
docker save -o output/paddleocr-ui_v0.2.0.tar paddleocr-ui:v0.2.0
SIZE=$(du -h output/paddleocr-ui_v0.2.0.tar | cut -f1)
echo "✅ 镜像已生成: output/paddleocr-ui_v0.2.0.tar ($SIZE)"

# 加载命令
echo ""
echo "=== 在其他设备上使用 ==="
echo "  docker load -i paddleocr-ui_v0.2.0.tar"
echo "  docker compose up -d"