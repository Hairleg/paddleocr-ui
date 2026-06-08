# Docker 构建与部署指南 v0.2.0

**日期**: 2026-06-08
**目标**: PaddleOCR UI v0.2.0 远端服务器构建与部署

---

## 环境信息

| 项目 | 值 |
|------|-----|
| 远端 IP | `119.29.181.114` |
| 账号 | `ubuntu` |
| 密码 | `00100900` |
| 镜像名 | `paddleocr-ui:v0.2.0` |
| 导出文件 | `paddleocr-ui-v0.2.0.tar` |
| 存放路径 | `/cosfs/` |

---

## 一、构建前检查

### 1.1 连接远端服务器
```bash
ssh ubuntu@119.29.181.114
```

### 1.2 检查磁盘空间
```bash
df -h /
```
要求 `/` 可用空间 > 20GB（构建镜像约需 8-10GB）。

### 1.3 清理历史镜像和构建缓存
```bash
# 查看 Docker 磁盘占用
docker system df

# 清理历史镜像（保留当前需要的）
docker images | grep paddleocr-ui

# 清理 /tmp 下的历史构建文件（如存在）
ls -lh /tmp/ | grep -E 'docker|build|paddle'
sudo rm -rf /tmp/docker-* /tmp/build-*

# 通用清理
docker builder prune -f
docker image prune -f
```

---

## 二、构建

### 2.1 上传项目到远端
```bash
# 本地打包（排除 _archive、.git）
cd paddleocr-ui
tar --exclude='_archive' --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
    -czf paddleocr-ui-v0.2.0-src.tar.gz .

# 上传到远端
scp paddleocr-ui-v0.2.0-src.tar.gz ubuntu@119.29.181.114:/tmp/
```

### 2.2 远端解压
```bash
ssh ubuntu@119.29.181.114
mkdir -p /tmp/paddleocr-ui-build
cd /tmp/paddleocr-ui-build
tar xzf /tmp/paddleocr-ui-v0.2.0-src.tar.gz
```

### 2.3 修改 Dockerfile 使用国内源

**Dockerfile 开头 apt-get 改为阿里云源**：
```dockerfile
# ── System deps (国内源加速) ──
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libgomp1 \
    fonts-noto-cjk fonts-dejavu-core curl \
    && rm -rf /var/lib/apt/lists/* && apt-get clean
```

**pip 使用清华源**：
```dockerfile
# pip 全局配置
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2.4 构建镜像
```bash
cd /tmp/paddleocr-ui-build
docker build -t paddleocr-ui:v0.2.0 .
```

构建时间约 15-25 分钟（含 PaddlePaddle 下载和依赖安装）。

---

## 三、编排文件

### 3.1 通用 docker-compose.yml
```yaml
# paddleocr-ui-compose.yml — 通用 docker-compose up
services:
  paddleocr-ui:
    image: paddleocr-ui:v0.2.0
    container_name: paddleocr-ui
    ports:
      - "8000:8000"
    environment:
      - PYTHONUNBUFFERED=1
      - PADDLE_PDX_MODEL_SOURCE=modelscope
      - PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
      - FLAGS_enable_pir_api=False
      - OMP_WAIT_POLICY=passive
      - ADMIN_USERNAME=admin
      - ADMIN_PASSWORD=YOUR_PASSWORD_HERE
      - PADDLEOCR_SECRET=YOUR_SECRET_HERE
    volumes:
      - ./data/db:/app/app/data
      - ./data/uploads:/app/app/uploads
      - ./data/outputs:/app/app/data/outputs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/health"]
      interval: 30s
      timeout: 5s
      start_period: 90s
      retries: 3
```

### 3.2 Portainer Stack 用 YAML
```yaml
# paddleocr-ui-stack.yml — Portainer Stacks
version: '3.8'
services:
  paddleocr-ui:
    image: paddleocr-ui:v0.2.0
    container_name: paddleocr-ui
    ports:
      - target: 8000
        published: 8000
        protocol: tcp
    environment:
      - PYTHONUNBUFFERED=1
      - PADDLE_PDX_MODEL_SOURCE=modelscope
      - PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True
      - FLAGS_enable_pir_api=False
      - OMP_WAIT_POLICY=passive
      - ADMIN_USERNAME=admin
      - ADMIN_PASSWORD=YOUR_PASSWORD_HERE
      - PADDLEOCR_SECRET=YOUR_SECRET_HERE
    volumes:
      - db_data:/app/app/data
      - uploads_data:/app/app/uploads
      - outputs_data:/app/app/data/outputs
    restart: unless-stopped

volumes:
  db_data:
  uploads_data:
  outputs_data:
```

---

## 四、测试验证

### 4.1 启动容器
```bash
docker run -d --name paddleocr-ui-test -p 8000:8000 \
  -e ADMIN_PASSWORD=test123 \
  -e PADDLEOCR_SECRET=test-secret \
  paddleocr-ui:v0.2.0
```

### 4.2 等待服务就绪
```bash
# 查看日志确认 PDX 编译完成
docker logs -f paddleocr-ui-test

# 健康检查
curl http://localhost:8000/health
```

### 4.3 上传 1 页 PDF 测试
```bash
# 登录
TOKEN=$(curl -s http://localhost:8000/api/auth/login -X POST \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"test123"}' | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# 预检（使用容器内的测试 PDF）
# 先上传一个 1 页 PDF 到容器
docker cp 江苏南通合同2.pdf paddleocr-ui-test:/tmp/test.pdf

# 通过 API 提交
JOB=$(curl -s http://localhost:8000/api/jobs/precheck -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@江苏南通合同2.pdf" -F "dpi=200" -F "lang=ch" -F "table=0" | \
  python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

# 确认
curl -s -X POST "http://localhost:8000/api/jobs/$JOB/confirm" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"dpi":200,"lang":"ch","table":false}'

# 等待完成后下载
sleep 600
curl -s -o /tmp/result.zip \
  "http://localhost:8000/api/jobs/$JOB/download?token=$TOKEN"
ls -la /tmp/result.zip
unzip -l /tmp/result.zip
```

### 4.4 验证清单
- [ ] 健康检查返回 `{"status":"ok","version":"0.2.0"}`
- [ ] 上传 PDF 预检成功
- [ ] OCR 管道完成，无 `OCR failed` 日志
- [ ] ZIP 下载成功，含 docx/xlsx/txt
- [ ] docx 打开有正常文字内容
- [ ] 容器运行稳定，未退出

### 4.5 清理测试容器
```bash
docker stop paddleocr-ui-test && docker rm paddleocr-ui-test
```

---

## 五、打包与导出

### 5.1 导出镜像
```bash
docker save paddleocr-ui:v0.2.0 -o /cosfs/paddleocr-ui-v0.2.0.tar
```

### 5.2 复制编排文件
```bash
cp paddleocr-ui-compose.yml /cosfs/paddleocr-ui-compose.yml
cp paddleocr-ui-stack.yml /cosfs/paddleocr-ui-stack.yml
```

### 5.3 确认导出
```bash
ls -lh /cosfs/paddleocr-ui-*
# 预期:
#   paddleocr-ui-v0.2.0.tar      (约 4-6GB)
#   paddleocr-ui-compose.yml     (约 1KB)
#   paddleocr-ui-stack.yml       (约 1KB)
```

### 5.4 清理构建临时文件
```bash
rm -rf /tmp/paddleocr-ui-build /tmp/paddleocr-ui-v0.2.0-src.tar.gz
```

---

## 六、加载使用

### 远端加载镜像
```bash
docker load -i /cosfs/paddleocr-ui-v0.2.0.tar
```

### Docker Compose 启动
```bash
cd /cosfs
docker-compose -f paddleocr-ui-compose.yml up -d
```

### Portainer Stack 部署
1. 进入 Portainer → Stacks → Add Stack
2. 名称: `paddleocr-ui`
3. 粘贴 `paddleocr-ui-stack.yml` 内容
4. Deploy the stack

---

## 关键环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ADMIN_USERNAME` | `admin` | 管理员用户名 |
| `ADMIN_PASSWORD` | `admin123` | **生产环境务必修改** |
| `PADDLEOCR_SECRET` | 随机 | **JWT 密钥，务必修改** |
| `FLAGS_enable_pir_api` | `False` | PIR 禁用，保证跨作业稳定 |
| `OMP_WAIT_POLICY` | `passive` | ONEDNN 线程空闲释放 CPU |

---

## 注意事项

1. **首次启动**: PaddleOCR 模型从 ModelScope 自动下载 (~2GB)，PDX 编译 5-10 分钟
2. **内存**: 建议 ≥ 8GB，单任务 OCR 峰值 ~2GB，ONEDNN 32 线程
3. **存储**: 镜像 ~5GB + 模型 ~3GB + 用户数据，建议 ≥ 30GB
4. **端口**: 默认 `8000`，通过 `-p` 映射
5. **数据库**: SQLite，DIFFICULT TO SCALE（仅单机使用）
