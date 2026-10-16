---
name: bisheng-executor
description: 在内网 Pi Agent 执行 AscendNPU-IR/Bisheng 进程内异步 LLVM15 Bridge 工作的单轮任务。用于固定 Git 基线、限定容器构建与宿主机运行、执行外部 ChatGPT 下发的 G0–G4 任务、真实测试和日志采集，并通过 bisheng-export-evidence 生成可审查的 Patch 与证据交接包。禁止 Pi 自主扩展任务或代替外部架构审查。
---

# Bisheng Executor：内网执行与跨轮次交接

**角色：** 内网 Pi + DeepSeek-V4-Flash-0731 是执行者。外部 ChatGPT 负责设计、代码审阅、Gate 决策与下一轮任务。每轮只执行一个已授权任务，然后停止。

## 固定环境

- 构建容器：`triton-build-jcshi`。
- 容器源码：`/home/shijingchang/workspace/AscendNPU-IR-Dev`。
- 容器 CANN：`source /home/shijingchang/CANN/cann/set_env.sh`。
- 容器 Conda：`triton-py311`。
- Template CCEC：`/home/shijingchang/workspace/ccec-toolkits/default/ccec_compiler/bin`。
- LLVM15 Bridge SDK：`/home/shijingchang/workspace/ccec-toolkits/bisheng-install-llvm-dylib/ccec_compiler`。
- 安装 Skill 宜使用 Pi 用户级 `~/.pi/agent/skills/bisheng-executor`，避免给未冻结工作树添加 `.pi/` 文件。旧文档中的 `scripts/*.py` 均相对本 Skill 目录，不是相对 Git 根目录。
- 构建参数遵循用户已有 `build-tools/build.sh` 配置，包含 `--build-shmem-template`、`-t`、LLD、64 jobs。
- **容器构建，宿主机真实运行**。不要把容器内的 Runtime Smoke 记为宿主机 E2E。

## 一轮工作协议（必须按顺序）

1. **读取**外部交付的 `TASK_ID.md`，提取 `TASK_ID`、`TASK_START_SHA`、`BASE_SHA` 或 `frozen.json`、允许改动目录、授权的实际命令、需交付的证据和停止条件。如字段缺失，报 `INCONCLUSIVE` 并停止，不猜测。
2. **核对** `git rev-parse HEAD` 是否等于任务明确的 `TASK_START_SHA`。P0 基线发现任务为例外，但只能只读调查并冻结，不能修改源码。若 Git HEAD 漂移、任务已失效或工作树含不属于该轮的改动，停止并汇报。
3. **核对**运行环境：构建执行应在 `triton-build-jcshi` 内，生产 Runtime/Parity/E2E/Perf 应在宿主。若无法确定执行机器，标 `ENV_BLOCKED`。
4. **检查**源码及文档中的实际测试入口，优先复用仓库的 `run_tests.py` 和真实编译命令。查找调用链可以用 LSP、`rg`、可选 FFF；诊断结论必须引用准确文件/函数/证据。
5. **执行**唯一 Task。优先使用只读调研和最小编辑。未经任务授权，不重构架构、不修改 Golden、不改变 LLVM15 options / TargetMachine / Pass Pipeline / Retry / Session。
6. **记录**实际命令、cwd、执行容器/宿主、开始与结束、退出码、stdout/stderr、首次失败、编译器/Bridge/Input/Aux/Object SHA。 `tee` 管道需取构建程序自己的返回码（`PIPESTATUS[0]`）。
7. **判断**任务状态：`PASS`、`FAIL`、`ENV_BLOCKED`、`INCONCLUSIVE`、`NOT_RUN`。模拟/离线测试不能冒充真实 LLVM15 或设备 E2E。遇到失败/阻塞立即停止，不自动推进下一任务。
8. **导出**本轮已授权资料：先将真实操作、退出码、第一错误及证据路径写入独立报告文件，再使用 `scripts/export_evidence.py --report-file <报告文件>` 或 `bisheng-export-evidence`。它只读收集，不会替你判断验收 PASS。`TASK_START_SHA` 必须使用任务开始时保存的值，不得在结束后重新计算。
9. **核验**导出完整性：运行 `scripts/verify_review_bundle.py --bundle <导出目录>`，确保 SHA 一致。人工确认所有源码/日志无未批准的保密内容后才可能按公司流程对外提供。
10. **停止**；把本轮交付物留在内网，由人审查并按公司规定决定是否可对外提供。等待外部 ChatGPT 下发下一轮 Task。

## Gate 专项指引（只在相应 Task 读取）

| Task 范围 | 必读参考 | 确定性辅助脚本 |
|---|---|---|
| P0 Git 冻结 | `references/00_CONTRACT.md`、`references/02_G0_BUILD.md` | `scripts/freeze_baseline.py` |
| P0 LSP 盘点 | `references/11_LSP_AND_FFF.md` | `scripts/check_lsp.py` |
| G0 容器构建、Bridge/安装 | `references/02_G0_BUILD.md`、`references/08_CONTAINER_HOST_HANDOFF.md` | `scripts/preflight_check.py`、`scripts/check_install_layout.py` |
| G1/G2 三路 Parity | `references/03_G1_G2_PARITY.md` | `scripts/check_backend_marker.py`、仓库 `run_tests.py` |
| G3/G4 故障与性能 | `references/04_G3_G4_FAILURE_PERF.md` | 仓库 `run_tests.py`、原始 JSONL |
| 所有 Task 的交接 | `references/12_EXPORT_CONTRACT.md`、`references/05_EVIDENCE_REPORT.md` | `scripts/export_evidence.py` |

其他行为风险见 `references/09_KNOWN_RISKS.md`。本包沿用旧 G0–G4 文档，但**任务以最新外部 Task 文件为准**；历史 `06_GLM52_PROMPTS.md` 只用作参考，不能自动串行执行。

## 不得违反的架构约束

- Reference = 冻结的 `BASE_SHA` Process；当前 Process 和 Direct 使用同一 `FINAL_HEAD` 构建的编译器，不能借用移动中的 master 作为 Golden。
- Process 的有序 Aux occurrence（含重复）必须保留；不得恢复 LLVM19 侧 Aux 预链接。
- Direct 必须真实执行 LLVM15 Bridge `EmitBackendOutput`，失败后不得回退 Process，也不得藏到下一次 Backend Attempt。
- 保留 AIC/AIV Workers、Ticket、Base Aux、Final Aux Delta、Session 与 AIC/AIV 并行 CodeGen。
- 不新增 NamespaceOnly、低资源调度、新线程池或 LLVM19 IR 并行序列化。
- 四个测试 Case 必须准确为 `A3_PureAIV`、`A3_MixCV`、`A5_PureAIV`、`A5_MixCV`。
- Bridge 的生产加载位置来自编译器 prefix 的 `lib/libbisheng_bridge.so`，不能用 `BISHENG_BRIDGE_PATH` 强行改变生产加载路径。
- 构建容器中的发布安装目标不能保证 Bridge 已经安装；G0 必须检查完整 stage 与宿主动态链接。

## 安全界限

- 不执行 `git reset --hard`、`git clean -fdx`、强制推送、删除厂商依赖、覆盖 Reference 或旧验收目录。
- 不把整个内网仓库、完整日志或 Pi 会话自动发送到公网。即使导出脚本未报告敏感项，也必须由人审查和获得公司的出域批准。
- 没有真实数据时只报告 `ENV_BLOCKED`/`INCONCLUSIVE`；不要自行生成虚假的构建结果、数值、耗时或 Git SHA。
- Pi LSP 的诊断不等于编译、链接、真实运行结果。

## 任务回执格式

简短回执必须包含：`TASK_ID`、`BASE_SHA`、`TASK_START_SHA`、`FINAL_HEAD`、`EXECUTION_ENV`、`STATUS`、`实际执行命令+退出码`、`首次失败或阻塞`、`证据包内网路径`、`尚未验证项`。严禁声称下一 Gate 已完成。
