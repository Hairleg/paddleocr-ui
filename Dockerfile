# Author: sizhchan | Org: dgaudit | Version: v0.2.0 | Date: 2026-06-08
FROM python:3.11-slim
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app

# ── System deps (OpenCV, PyMuPDF, fonts) ──
RUN sed -i 's|http://deb.debian.org|http://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1 \
    fonts-noto-cjk fonts-dejavu-core curl gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/* && apt-get clean

# ── CPU-only PyTorch (before other deps to avoid CUDA torch) ──
RUN pip install --no-cache-dir torch torchvision

# ── Python dependencies ──
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── RapidTable / RapidOCR + YOLO 模型预下载 ──
RUN pip install --no-cache-dir rapid_table rapidocr rapidocr_onnxruntime doclayout-yolo 'numpy<2.0'
RUN python3 -c "from huggingface_hub import hf_hub_download; p=hf_hub_download('juliozhao/DocLayout-YOLO', 'doclayout_yolo_docstructbench_imgsz1280_2501.pt'); print('YOLO:', p)"

# ── Application code ──
COPY app/ ./app/

# ── Pre-warm PaddleOCR (compile ONEDNN kernels once) ──
RUN python3 -c "\
import os; \
os.environ['PADDLE_PDX_MODEL_SOURCE']='modelscope'; \
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK']='True'; \
import numpy as np, cv2; \
img = np.ones((120,120,3),dtype=np.uint8)*255; \
cv2.imwrite('/tmp/warmup.png',img); \
from paddleocr import PaddleOCR; \
ocr = PaddleOCR(lang='ch'); \
ocr.predict('/tmp/warmup.png'); \
print('PaddleOCR OK')"

# ── MinerU config ──
RUN echo '{"device-mode":"cpu","table-config":{"enable":true,"model":"rapid_table"},"layout-config":{"enable":false},"formula-config":{"enable":false}}' > /root/magic-pdf.json

# ── Runtime directories ──
RUN mkdir -p /app/app/uploads /app/app/data /app/app/data/outputs

EXPOSE 8000

# ── Environment ──
ENV PYTHONUNBUFFERED=1
ENV PADDLE_PDX_MODEL_SOURCE=modelscope
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
ENV FLAGS_enable_pir_api=False
ENV OMP_WAIT_POLICY=passive
ENV ADMIN_USERNAME=admin
ENV ADMIN_PASSWORD=admin123
ENV PADDLEOCR_SECRET=paddleocr-prod-secret-change-me
ENV MINERU_LAYOUT_MODEL=/root/.cache/huggingface/hub/models--juliozhao--DocLayout-YOLO/snapshots/main/doclayout_yolo_docstructbench_imgsz1280_2501.pt

# ── Healthcheck ──
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
