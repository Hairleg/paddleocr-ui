# TODO — 项目工作进度

## 进行中

- [ ] **T-001** 等待 16 页合同管道完成，验证 docx 产出
- [ ] **T-002** 子进程隔离架构稳定性验证（uvicorn 存活，子进程崩不影响）
- [ ] **T-003** 对比 PIR=Disabled 产出质量

## 待处理

### 超时功能
- [ ] **T-004** 超时日志可区分：超时 → WARNING，崩溃 → ERROR
- [ ] **T-005** 超时后显式 `proc.kill()` + `await proc.wait()`，二次确认 `os.kill(pid, SIGKILL)`
- [ ] **T-006** 超时后更新 DB：`job_files.status='failed'`，`error_message='timeout'`
- [ ] **T-007** 前端超时上限 120→180 分钟
- [ ] **T-008** 预检时估算耗时提示用户

### 稳定性
- [ ] **T-009** PIR=Disabled 跨作业验证（3 次连续作业不死）
- [ ] **T-010** PDX 磁盘缓存调研（避免每次启动重新编译）
- [ ] **T-011** RapidOCR 表检测偶发崩溃排查

### 前端
- [ ] **T-012** 确认并发参数隐藏无遗漏

---

## 已完成

- [x] **T-013** PIR 禁用（FLAGS_enable_pir_api=False）→ 解决 PirInterpreter SIGSEGV
- [x] **T-014** 子进程隔离架构（close_fds=True）→ uvicorn 与 OC 解耦
- [x] **T-015** writer 移入 process_pdf 内部 → 崩溃前保存结果
- [x] **T-016** 多用户 3 账号测试通过
- [x] **T-017** 前端并发选项隐藏 + 后端白名单移除
- [x] **T-018** DEV_PITFALLS #1-#16 记录
- [x] **T-019** 审计署 130 份报告 无乱码验证
- [x] **T-020** 超时默认值 15→120 分钟
