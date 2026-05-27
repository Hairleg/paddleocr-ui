# Author: sizhchan | Org: dgaudit | Version: v0.1 | Date: 2026-05-27
FROM python:3.12-slim

WORKDIR /app

# ── System dependencies ──
# opencv, PyMuPDF, and Chinese font support
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgomp1 \
    fonts-noto-cjk \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# ── MinerU config file (required by magic-pdf) ──
RUN echo '{"device-mode":"cpu","layoutreader-model-dir":"","llm-aided-config":{}}' > /root/magic-pdf.json

# ── Configure pip mirror for faster downloads ──
RUN pip config set global.index-url http://mirrors.tencentyun.com/pypi/simple && \
    pip config set install.trusted-host mirrors.tencentyun.com

# ── CPU-only PyTorch (before requirements.txt to prevent CUDA torch) ──
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    torch torchvision

# ── Python dependencies ──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──
COPY app/ ./app/

# ── Pre-warm PaddleOCR ONEDNN kernels ──
RUN python3 -c "\
import os; \
os.environ['PADDLE_PDX_MODEL_SOURCE'] = 'modelscope'; \
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'; \
import numpy as np, cv2; \
img = np.ones((100, 100, 3), dtype=np.uint8) * 255; \
cv2.imwrite('/tmp/warmup.png', img); \
from paddleocr import PaddleOCR; \
ocr = PaddleOCR(lang='ch'); \
ocr.predict('/tmp/warmup.png'); \
print('PaddleOCR warmup complete'); \
"

# ── Runtime directories ──
RUN mkdir -p app/uploads app/data app/data/outputs && chmod 777 app/uploads app/data app/data/outputs

EXPOSE 8000

# ── Environment ──
ENV PYTHONUNBUFFERED=1
ENV PADDLE_PDX_MODEL_SOURCE=modelscope
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
# ENV PADDLEOCR_NUM_THREADS=16   # Override for 96-core servers

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
