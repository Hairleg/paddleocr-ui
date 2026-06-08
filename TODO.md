# TODO — 项目工作进度 (updated 2026-06-05)

## 进行中

- [x] **T-001** 16 页合同管道完成，docx 产出 ✅ 4235字 vs 4092字 (103%)
- [x] **T-003** PIR=Disabled 质量对比 ✅
- [x] **T-021** 清理调试代码 → 暂缓
- [x] **T-009** 稳定性测试: 3账号5文件, PIR=Disabled连续处理 ✅ 7次连续不崩

## 待处理

### 前端

- [x] **T-028** ONEDNN 线程 spin-wait 不释放:
  - 根因: PaddlePaddle 3.0.0 `predict()` 后线程进入忙等，非休眠
  - 方案 A: 环境变量 `OMP_WAIT_POLICY=passive` → OpenMP 线程空闲时 `sleep` 而非 `spin`，CPU 降至 0
  - 方案 B: OCR 完成后 `del ocr_engine` + `gc.collect()` 手动销毁引擎对象
  - 方案 C: `revive.sh` 设置 `export OMP_WAIT_POLICY=passive` 一劳永逸
  - 推荐: A + B 组合，文件: `app/pipeline/core/ocr/engine.py`

- [x] **T-029** DB 状态更新卡死（aiosqlite WAL 锁）:
  - 根因: `await db.commit()` 在 WAL 锁竞争下永久 hang，`process_job` 无超时
  - 方案: 用 `asyncio.wait_for(db.commit(), timeout=30)` 包裹所有 DB 写操作
  - 超时时 `await db.close()`，不抛异常，worker 继续取下一任务
  - 文件: `app/queue.py` L118-122, L127-128
  - 关联: T-025（已存在，合并为一）

- [x] **T-024** 队列状态显示优化:
  - 状态标签: 排队中 / 终止 / 正在处理 / 异常，请联系管理员 / 完成
  - 排队中 → 显示已等候时间
  - 正在处理 → 显示已处理时间
  - 终止/异常/完成 → 显示状态变更时刻



### Worker 稳定性
- [x] **T-025** DB 操作加超时保护:
  - `await db.execute(...)` 和 `await db.commit()` 用 `asyncio.wait_for(..., timeout=30)` 包裹
  - 超时时 `await db.close()` 释放连接，防止 WAL 锁永久持有
  - 文件: `app/queue.py` L118-122, L127-128
  
- [x] **T-026** (T-028已解决: OMP_WAIT_POLICY=passive) `run_in_executor` 线程泄漏防护:
  - 方案 A: `ProcessPoolExecutor` 替代 `ThreadPoolExecutor`，子进程可显式 `kill()`
  - 方案 B: 用 `threading.Thread` + `join(timeout)` 手动管理，超时后 `os._exit` 杀死子线程（副作用大）
  - 推荐 A: 与 revive.sh 的子进程启动方式一致，`close_fds=True` 避免 socket 继承
  - 文件: `app/queue.py` L87-90

- [x] **T-027** 图片路径 `process_image` 改为异步:
  - `process_image(img_path, out_dir)` → `await run_in_executor(None, partial(process_image, img_path, out_dir))`
  - 避免 OCR 占用 event loop 线程导致服务假死
  - 文件: `app/queue.py` L102-103

### 超时功能
- [x] **T-004** 超时日志区分：超时 → WARNING，崩溃 → ERROR
- [x] **T-005** 超时后 `proc.kill()` + 二次确认
- [x] **T-006** 超时后更新 DB status='failed'
- [ ] **T-007** 前端超时上限 120→180 分钟
- [ ] **T-008** 预检时估算耗时提示

### 性能
- [ ] **T-010** PDX 磁盘缓存调研（避免每次重启重新编译 5-10min）
- [ ] **T-011** 16 页合同在含表页面偶发崩溃排查

### 前端
- [x] **T-012** 前端并发参数隐藏确认无遗漏 ✅ 已完成

### 文档
- [ ] **T-022** README 性能数据最终更新
- [ ] **T-023** DEV_PITFALLS 补充 PIR 解决方案 + writer 大文档坑

---

## 已完成

- [x] **T-013** PIR 禁用 → 解决 SIGSEGV
- [x] **T-016** 多用户 3 账号测试
- [x] **T-017** 前端并发锁 + 后端白名单
- [x] **T-018** DEV_PITFALLS #1-#16
- [x] **T-019** 审计署 130 份报告验证
- [x] **T-020** 超时默认 120 分钟
- [x] **T-002** 子进程隔离 → 已废弃（回退线程池）
- [x] **T-015** pkl 保存点 → 已埋入 queue.py

---

## 废弃

- ~~T-002 子进程隔离架构~~ → socket 继承 + PDX 重编译，回退线程池
- ~~T-014 子进程 close_fds~~ → 架构已废弃
