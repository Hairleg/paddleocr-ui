# 项目清理记录

**日期**: 2026-06-08
**目的**: 准备远端 Docker 构建，清理临时文件和冗余数据

---

## 清理操作

### 1. 输出目录迁移
- **来源**: `app/data/outputs/` (116 个任务目录, 1.8GB)
- **去向**: `_archive/outputs/`
- **保留**: 重建空目录 `app/data/outputs/`

### 2. 示例文件迁移
- **来源**: `example/` (14 个文件, 14MB)
- **去向**: `_archive/example/`
- **保留**: `含盖印合同test.pdf`, `含盖印合同test.docx`, `江苏南通合同2.docx` 三份测试文件

### 3. 上传目录清空
- **来源**: `app/uploads/`
- **操作**: 删除所有上传缓存文件

### 4. 死代码清理
- **文件**: `app/pipeline/core/pipeline_dead_backup.py`
- **去向**: `_archive/pipeline_dead_backup.py`

### 5. 外部子模块迁移
- **来源**: `app/ocr` (PaddleOCR 外部模型目录)
- **去向**: `_archive/app_ocr`

### 6. 软链接删除
- **来源**: `ocr` (项目根目录软链)
- **操作**: 删除

### 7. Python 缓存清理
- `__pycache__/` (11 个目录)
- `*.pyc` 文件
- `.ipynb_checkpoints/` 目录

### 8. 数据库清理
- **来源**: `app/data/paddleocr.db`
- **操作**: 删除 (重启后自动重建)

### 9. .gitignore 更新
新增忽略:
```
_archive/
app/data/
app/uploads/
*.db
*.log
__pycache__/
*.pyc
.ipynb_checkpoints/
ocr
build/
```

### 10. Docker 配置补充
- **Dockerfile**: 添加 `ENV FLAGS_enable_pir_api=False`, `ENV OMP_WAIT_POLICY=passive`
- **docker-compose.yml**: 同步添加环境变量

---

## 清理前后对比

| 指标 | 清理前 | 清理后 |
|------|:---:|:---:|
| 项目大小 | ~1.9GB | ~25MB |
| 输出目录 | 116 个任务 | 1 个空目录 |
| 示例文件 | 14 个 | 3 个测试文件 |
| Python 缓存 | 11 个目录 | 0 |
| 死代码文件 | 1 | 0 |
| 软链接 | 1 | 0 |

---

## 归档目录结构

```
_archive/
├── app_ocr/          # 原 app/ocr 子模块
├── example/          # 所有历史示例文件
├── outputs/          # 所有历史 OCR 输出
├── pipeline_dead_backup.py  # 死代码备份
└── ...               # 其他临时文件
```

`_archive/` 已在 `.gitignore` 中，不会被提交到仓库。
