# 开发踩坑备忘录

> 记录 paddleocr-ui 项目从 v0.1.2 到当前版本的开发过程中遇到的所有关键问题和解决方案。

---

## 1. PaddlePaddle 与 PaddleOCR 版本兼容

| 组合 | 结果 | 根因 |
|------|:--:|------|
| paddlepaddle 3.3.1 + paddleocr 3.6.0 | ❌ PIR 错误 | ONEDNN 不识别 ArrayAttribute\<DoubleAttribute\> |
| paddlepaddle 3.3.0 + paddleocr 3.6.0 | ❌ 同上 | 3.3.x 系列共享同一 PIR 序列化格式 |
| paddlepaddle 3.0.0 + paddleocr 3.6.0 | ⚠️ 首次正常，后续 SIGSEGV | PirInterpreter::CheckGC 内存管理 bug |

### PIR 错误原文
```
ConvertPirAttribute2RuntimeAttribute not support 
[pir::ArrayAttribute<pir::DoubleAttribute>]
at onednn_instruction.cc:116
```

**锁定的最低可行配置**：`paddlepaddle==3.0.0` + `paddleocr==3.6.0` + `numpy==1.26.4`

---

## 2. ONEDNN 状态污染（核心架构问题）

### 现象
管道直跑（独立 Python 进程）始终成功；服务（uvicorn 长进程）首次成功，后续作业 SIGSEGV。

### 根因
ONEDNN 是 C++ 进程级全局单例，析构不完整。一次 OCR 推理后 C++ 层 buffer 未完全释放，下次推理踩到脏内存。

```
作业1: ONEDNN.分配buffer() → 推理 → Python GC → C++未释放
作业2: ONEDNN.分配buffer() → 访问已释放内存 → SIGSEGV
```

### 理想解决方案：子进程隔离
每个 OCR 作业在独立 `multiprocessing.Process` 中运行，作业完成后进程退出，ONEDNN 状态随进程销毁。

---

## 3. paddleocr 3.6.0 数据结构变更

### 现象
`page_ocr.get("rec_texts", [])` 始终返回空列表 → 输出 0 字。

### 根因
paddleocr 3.6.0 把识别结果从顶层移到 `json['res']` 内：
```python
# 旧版本
rec_texts = page_ocr.get("rec_texts", [])

# 3.6.0
rec_texts = page_ocr.json.get("res", {}).get("rec_texts", [])
```

### 修复位置
`app/pipeline/core/pipeline.py` 的 `_build_text_elements_from_ocr()` 函数。

---

## 4. word_writer 的 reading_order 空列表 bug

### 现象
管道产生 23 个元素，但 docx 输出 0 字。

### 根因
`PageLayout.reading_order` 默认 `[]`（空列表），writer 遍历空列表 → 跳过所有元素。

### 修复
```python
if page.reading_order:
    for elem_idx in page.reading_order:
        ...
else:
    for elem in page.elements:  # 兜底：直接遍历全部
        ...
```

---

## 5. PDX 编译阻塞事件循环

### 现象
服务启动后首次请求 timeout（login / health 全部超时）。

### 根因
`preload_all` 在 uvicorn lifespan 中同步调用，PDX 编译占用 ONEDNN 全局锁，阻塞整个 asyncio 事件循环。

### 修复
- 禁用启动预加载（`app/main.py` 中注释 `preload_all`）
- PaddleOCR 惰性导入（`app/pipeline/core/ocr/engine.py` 中 `get_ocr()` 内部按需 `import`）

---

## 6. PIR 解释器崩溃与 SIGSEGV (✅ 已解决)

### 现象
```
FatalError: Segmentation fault is detected by the operating system.
[SignalInfo: *** SIGSEGV (@0x0) received]
```
单个 uvicorn 进程连续 OCR 后必死，无 Python traceback。

### 根因
PaddlePaddle 3.0.0 默认 PIR 执行模式。`PirInterpreter::CheckGC` 在首次 OCR 后 ONEDNN buffer 未完全释放，第二次推理 GC 访问已释放内存 → 段错误。

### 解决：禁用 PIR，回退图执行器
```bash
export FLAGS_enable_pir_api=False
```

### 效果
| 指标 | PIR=Enabled | PIR=Disabled |
|------|:--:|:--:|
| 单页 OCR | ~15s | **~8s** |
| 跨作业稳定性 | ❌ 第2次崩 | ✅ 稳定 |
| 准确率 | 114字 | 114字 (同) |

禁用 PIR 不仅消除崩溃，速度还提升 ~47%。

---

## 7. passlib → bcrypt 认证兼容

### 问题
`passlib` 在新版 `bcrypt>=4.1` 下报错：`AttributeError: module 'bcrypt' has no attribute '__about__'`

### 修复
`app/api/routes.py` 认证部分替换为直接 `bcrypt==4.0.1`：
```python
import bcrypt
if bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
    ...
```

---

## 8. uvicorn 端口争抢

### 现象
多次启动后 `pkill` 杀不干净，残留进程仍绑定 8000 端口。

### 排查方法
```bash
ss -tlnp | grep 8000    # 查看谁在监听
fuser -k 8000/tcp        # 强制释放端口
```

---

## 9. numpy 版本冲突

### 问题
paddlepaddle 3.0.0 要求 `numpy<2.0`，但环境中已安装 `numpy 2.4.6`。

### 修复
在 paddlepaddle 安装之后执行 `pip install 'numpy<2.0' --force-reinstall`，确保 `numpy==1.26.4`。

---

## 总结：架构推荐

```
┌─ uvicorn 主进程（轻量，永不碰 PaddlePaddle）────┐
│  health ✅  login ✅  precheck ✅                 │
└──────────────────────────────────────────────────┘
         │ pipe/socket
         ▼
┌─ OCR worker 子进程（独立，崩溃即重生）────────────┐
│  import paddleocr → PDX → OCR → 写盘 → return     │
│  每次作业可选新进程或复用一个（Pool）               │
└──────────────────────────────────────────────────┘
```

- **版本锁定**：`paddlepaddle==3.0.0` + `paddleocr==3.6.0` + `numpy==1.26.4`
- **启动脚本**：`revive.sh` 包含完整安装逻辑
- **日志**：`/tmp/paddleocr-ui.log`
- **模型目录**：`/root/.paddlex/official_models/`

---

## 10. multiprocessing.Process fork 继承监听 socket

### 现象
主进程（uvicorn）退出后，子进程（OCR worker）仍占用 8000 端口。
```
ss -tlnp | grep 8000
LISTEN  0.0.0.0:8000  users:(("pt_main_thread",pid=24761,fd=16))
```
新 uvicorn 启动时报 `EADDRINUSE`。

### 根因
Linux 下 `fork()` 复制整个文件描述符表：

```
父进程: fd=16 → TCP LISTEN 0.0.0.0:8000
        ↓ fork()
子进程: fd=16 → TCP LISTEN 0.0.0.0:8000  ← 继承同一个 socket
```

两个进程同时持有监听 socket，内核允许（非争抢）。父进程崩溃后子进程变孤儿，socket 存活 → 端口永久占用。

### spawn 为什么不行
`mp.set_start_method("spawn")` 理论上不继承 fd，但实际导致主进程卡死：
- spawn 会 `import` 全部模块进行 pickle 序列化
- 其中的 PaddleOCR import 触发 PDX ONEDNN 编译
- 同步编译阻塞 asyncio 事件循环 → 所有 HTTP 超时

### 子进程关 fd 为什么不行
在 worker 函数入口处 `for fd in range(3,256): os.close(fd)` 理论上有效，但时机问题：
- 父进程先于子进程崩溃（SIGSEGV）
- 子进程来不及执行到关闭 fd 的代码
- socket 已泄漏

### 理想方案（未实施）
uvicorn 创建 socket 时设置 `SO_REUSEADDR` + 子进程 `FD_CLOEXEC`，但需改 uvicorn 源码。

### 实际方案
回退线程池架构，不做进程隔离。

---

## 11. enqueue_job 签名不匹配

### 现象
`TypeError: enqueue_job() missing 1 required positional argument: 'file_record'`

### 根因
routes.py 调用 1 参数，queue.py 签名要求 2 参数。环境重置后版本不一致。

### 修复
添加 `file_record=None` 默认值，内部从 DB 查询。

---

## 12. 环境重置后数据库清零

### 现象
`data.db` 0 字节 → `KeyError: 'id'`

### 根因
空文件不是有效 SQLite DB，`CREATE TABLE IF NOT EXISTS` 失败。

### 修复
启动前 `rm -f data.db`，让 `init_db()` 从头建表。

---

## 13. 缺失 Python 依赖

### 现象
`ModuleNotFoundError: No module named 'jose'` / `'docx'`

### 修复
`revive.sh` 追加 `python-docx` 和 `bcrypt==4.0.1`。

---

## 14. 代码探针污染

### 教训
- 探针用 `try/except` 包裹
- 避免链式访问（如 `_p.source.value`），用 `str()` 防御
- 完毕后 `grep -r "trace.log\|_df.write"` 确认清除

---

## 当前可用状态 (v0.1.2+fix)

| 组件 | 状态 |
|------|:--:|
| paddlepaddle 3.0.0 + paddleocr 3.6.0 | ✅ |
| 管道直跑 | ✅ 23元素/页 |
| 服务端 OCR | ✅ (首次PDX编译5-10min) |
| 服务响应性 | ✅ (preloader已禁用) |

---

## 15. ONEDNN 线程池 SIGSEGV（PIR 无关） (✅ 已解决)

### 现象
- 管道完成后（`Processing complete: 16 pages, 267 elements`），进程立即死亡
- 日志无 Python traceback，无 SIGSEGV 记录（可能被系统吞）
- 小文档正常，大文档（16 页含表）必死

### 根因
PaddlePaddle 的 `run_in_executor` 在线程归还池时触发 ONEDNN buffer 清理，访问已释放内存 → SIGSEGV。与 PIR 模式无关（PIR=Enabled/Disabled 均触发，仅时机不同）。

### 解决：子进程隔离

将 `process_pdf` 从线程池搬进独立子进程，用 `close_fds=True` 避免 socket 继承：

```python
# queue.py: 线程池 run_in_executor → subprocess 隔离
proc = await asyncio.create_subprocess_exec(
    sys.executable, "-c", worker_script,
    close_fds=True,
)
stdout, stderr = await proc.communicate()
# 子进程崩（SIGSEGV）不影响 uvicorn
```

### 效果
- 子进程完成 OCR + writer → 写盘
- 子进程可能崩（ONEDNN 清理），**uvicorn 无感知**
- 主进程从磁盘读取结果

### 注意
- `close_fds=True` 是 Linux 特性，Windows 不支持
- 首次 PDX 编译每次都在新子进程重新编译（磁盘无缓存）


---

## 16. 超时伪装 SIGSEGV——诊断误导 (✅ 已修复)

### 现象
子进程隔离后，管道完成（16 页 267 元素），子进程突然死亡，无 docx 产出。误判为 writer 或 ONEDNN 崩溃。

### 根因
`asyncio.wait_for(proc.communicate(), timeout=15*60)` —— 默认超时 15 分钟。
PDX 编译 7-10 分钟 + 16 页 OCR 110 秒/页 ≈ 29 分钟 > 15 分钟。

子进程被 `TimeoutError` 杀死，非 SIGSEGV。

### 修复
`DEFAULT_MAX_RUNTIME_MINUTES = 15` → `120`

### 教训
子进程隔离后，超时掩盖了真实崩溃点。以后调试应先查 `asyncio.TimeoutError`。
