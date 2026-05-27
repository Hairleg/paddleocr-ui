# Author: sizhchan | Org: dgaudit | Version: v0.1 | Date: 2026-05-27
# PaddleOCR UI

基于 [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) 的 OCR 文字识别服务，支持多用户、任务队列，以 Docker 镜像形式交付。

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
