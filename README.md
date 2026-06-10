# Author: sizhchan | Org: dgaudit | Version: v0.1 | Date: 2026-05-27
# PaddleOCR UI

- 本项目主要是同事提出，敏感文件不敢使用商业ocr，故使用vibecoding编写了该项目，可以在内网离线运行。
- 基于 [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) 的 OCR 文字识别服务，支持多用户、任务队列，以 Docker 镜像形式交付。

## 功能

- 用户注册 / 登录（JWT 认证）
- 图片上传（拖拽 / 点击选择）
- **OCR 任务队列**：逐个处理，避免多用户并发时资源争抢
- 任务状态追踪（排队中 → 处理中 → 已完成 / 失败）
- 用户隔离：每人只能看到自己的上传和识别结果
- Docker 一键部署

## 快速开始

### Docker Compose（推荐）

```bash
docker compose up -d
```

访问 http://localhost:8000 → 注册账号 → 上传图片 → 等待队列处理。

### 手动构建

```bash
docker build -t paddleocr-ui .
docker run -p 8000:8000 paddleocr-ui
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PADDLEOCR_SECRET` | `paddleocr-dev-secret-...` | JWT 签名密钥，**生产环境务必修改** |
| `PADDLEOCR_DB_PATH` | `app/data/paddleocr.db` | SQLite 数据库路径 |

## API

所有任务 API 需要 `Authorization: Bearer <token>` 头。

### 认证

- `POST /api/auth/register` — `{"username":"...", "password":"..."}` → `{token, user}`
- `POST /api/auth/login` — 同上
- `GET /api/auth/me` — 当前用户信息

### 任务

- `POST /api/tasks` — 上传图片（`multipart/form-data`，字段 `file`）→ `{task_id, status}`
- `GET /api/tasks` — 当前用户的任务列表
- `GET /api/tasks/{id}` — 任务详情（含识别结果）
- `GET /api/tasks/{id}/image` — 下载原始图片

### 其他

- `GET /health` — 健康检查

## 技术栈

- **OCR**：PaddleOCR
- **Web**：FastAPI + Uvicorn
- **队列**：asyncio.Queue（进程内，零外部依赖）
- **数据库**：SQLite + aiosqlite（WAL 模式）
- **认证**：bcrypt + JWT（python-jose）
- **容器**：Docker 多阶段构建

## 项目结构

```
paddleocr-ui/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI 入口 + lifespan
│   ├── auth.py              # JWT 认证 + bcrypt
│   ├── db.py                # SQLite 数据库模块
│   ├── queue.py             # asyncio.Queue + 后台 worker
│   ├── ocr/
│   │   ├── __init__.py
│   │   └── engine.py        # PaddleOCR 封装
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py        # 页面 + API 路由
│   ├── templates/
│   │   ├── login.html       # 登录页
│   │   ├── register.html    # 注册页
│   │   └── index.html       # 主界面（上传 + 任务列表）
│   ├── uploads/             # 上传文件（运行时）
│   └── data/                # SQLite 数据库（运行时）
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```


## 性能参考

| 指标 | 数值 |
|------|------|
| OCR 速度 | **~111 秒/页**（含文本检测+识别+表格提取） |
| 页间波动 | 60-184 秒（取决于页面复杂度、表格数量） |
| 16 页合同总耗时 | ~28 分钟 |
| PDX 首次编译 | 5-10 分钟（切换 PIR 模式后需重新编译） |
| 并发能力 | **禁用**（ONEDNN 非线程安全） |
| 进程稳定性 | PIR=Disabled 跨作业稳定，PIR=Enabled 第2次 SIGSEGV |
| 大文档实测 | 62页 中国人口研究报告: 2h07m, 149段 45155字 8表 |
| 内存占用 | 62页 OCR期间 ~1.3GB, ONEDNN空闲 0% CPU (OMP_WAIT_POLICY=passive) |


### 当前配置

```
paddlepaddle == 3.0.0
paddleocr    == 3.6.0
numpy        == 1.26.4
FLAGS_enable_pir_api = False   # 禁用 PIR 避免崩溃
PADDLE_PDX_MODEL_SOURCE = modelscope
CPU: 4 核 Intel Xeon
内存: 6 GB
```

### 速度分解

| 阶段 | 单页耗时 |
|------|:--:|
| PDF→PNG 渲染 (250 DPI) | ~3s |
| OCR 文本检测 + 识别 | ~50s |
| 表格检测 (YOLO) + 表格 OCR (RapidOCR) | ~55s |
| Word/Excel 写入 | ~3s |

> 含表格的页面（如合同）约 110s/页，纯文字页面约 60s/页。
