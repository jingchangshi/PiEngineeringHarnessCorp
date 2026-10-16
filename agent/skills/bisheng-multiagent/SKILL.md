---
name: bisheng-multiagent
description: 在内网 Pi Agent 使用 npm:pi-subagents，将外部 ChatGPT 授权的 AscendNPU-IR/Bisheng LLVM15 Bridge 单轮 Task 拆为短生命周期工作单元，调度隔离上下文的 Scout、Implementer、Verifier、Reviewer，保持冻结 Git SHA、容器构建/宿主运行、真实证据导出及 Gate 停止条件。适用于 Bisheng 异步 in-process 后端的 P0/G0–G4 工作流；不得跨轮自动推进。
---

# Bisheng Multiagent — 单轮任务内的受控调度

本 Skill **只在已安装 `bisheng-executor` 的前提下**启用。它是调度层，不修改原 G0–G4 技术合同，不替代 `bisheng-executor`、`bisheng-export-evidence` 或外部 ChatGPT 的 Gate 裁决。

## 入口与保护

1. 读取绝对路径 TASK 文件；同时读取 `bisheng-executor/SKILL.md` 及该 Gate 对应参考，不把历史 `06_GLM52_PROMPTS.md` 当作连续任务队列。
2. 运行本 Skill `scripts/check_task_contract.py --task <TASK_FILE> --repo <SOURCE_REPO> --run-root <RUN_ROOT>`。核对 `TASK_ID`、`TASK_START_SHA`、`BASE_SHA`/`FROZEN_JSON`、授权目录、运行环境、停止条件。仅 `P0-*` 只读冻结 Task 可使用 `AUTO_DISCOVER`。
3. 核实 Pi 已加载 npm 包 `pi-subagents` 且发现 `bisheng-scout`、`bisheng-implementer`、`bisheng-verifier`、`bisheng-reviewer`。缺失时 `ENV_BLOCKED`；不得在执行任务中擅自联网安装。
4. 先定位真实运行边界：`BUILD_CONTAINER` 必须在 `triton-build-jcshi`；`HOST` 必须在宿主。子 Agent 继承它启动时的进程/文件系统，**委派不等于容器—宿主切换**。若当前环境不符，按既有跨机器交接协议暂停。
5. 所有工作单元目录写到 `RUN_ROOT/multiagent/<TASK_ID>/`；`RUN_ROOT` 必须位于 Git 仓库外，避免污染基线。不要修改 `.gitignore` 隐藏变化。

## Coordinator 行为

- 父 Pi 即 Coordinator；不再另启一个可递归派生的 Coordinator 子进程。
- 最多拆成 3 个 **有实际依赖、能独立验收** 的 Work Unit；简单任务只用一个。每个单元写 `WU-*.md`：目标、输入 SHA、授权可改文件、命令、成功/失败条件、证据路径、前置依赖。模板见 `references/WORK_UNIT_TEMPLATE.md`。
- 每个工作单元都与本轮 **同一个** `TASK_ID`、`TASK_START_SHA`、`BASE_SHA` 关联，不生成或推进其他 Task ID。
- 保持 **One Writer per Work Unit，仓库中最多一名 Writer**。绝不并发运行多个改同一树的 Implementer；后台 writer 完成/停止且核查 diff 后才能继续。
- Reader 可并行，但只在相同已确认快照、无 writer 同时写入时并行。Verifier/Reviewer 必须在 Implementer 结束、diff 稳定之后使用 **全新上下文**，不能读取其对话历史，也不能仅采纳其 PASS 声明。
- 所有 Subagent 都用 `context: "fresh"`，不调用 `fork`、`resume` 来传递冗长历史。子 Agent 不得再启动子 Agent；不要让 Coordinator 发出无边界 chain/parallel/workflow-script。
- 父 Agent 只接收各角色的结构化小回执（首错、真实日志路径、SHA/退出码），避免拷贝编译日志、完整 diff 和模型思考文本回父上下文。
- 一次子 Agent 无进展、重复同一句或触发超时：中止，保存状态与可能的局部源码改动，**禁止自动无限重试**。最多经人工确认后用新子 Agent 进行一次定向恢复；不以原任务成功覆盖中途失败。

## 推荐执行顺序

1. `bisheng-scout`（按需）：只读定位最小相关文件、函数、初始 Git 状态及最早风险；输出 1 页以内的事实/证据路径。
2. `bisheng-implementer`（仅原 Task 授权修改时）：消费 WU 卡与 Scout 精简报告，只执行本 WU，可编辑指定源文件；不得修改 Reference、Golden、TargetMachine、Process/Direct 既定合同。
3. `bisheng-verifier`：独立执行授权测试命令，记录 cwd、BUILD_CONTAINER/HOST、退出码、首错和日志；不许用容器验证冒充 Host E2E。
4. `bisheng-reviewer`：从 `TASK_START_SHA`、当前 `git diff` 及原始证据独立审查，必要时报告 `REQUEST_CHANGES`；不是外部最终 Gate 裁决。只读 Task 可省略 Implementer。
5. Coordinator 整合真实证据，写好 `ROUND_REPORT.md`，调用原 `bisheng-export-evidence --report-file ...` 并用 `verify_review_bundle.py` 检验哈希。人工检查数据出域合规后才能决定是否传递外部模型。
6. **停止**。即使内部 reviewer APPROVE，也不能自动进入下一轮或下一 Gate。

## 插件调用（参数示例；由 Pi 调用真实工具）

对 `bisheng-scout`：

```json
{"agent":"bisheng-scout","task":"只读执行 /RUN_ROOT/multiagent/TASK/WU-01.md；读取真实文件并返回证据路径，不继承父对话。","async":false,"options":{"context":"fresh","timeoutMs":600000}}
```

对 `bisheng-implementer`：

```json
{"agent":"bisheng-implementer","task":"只执行 /RUN_ROOT/multiagent/TASK/WU-02.md；一次只修改授权源码，记录真实结果。","async":false,"options":{"context":"fresh","timeoutMs":1200000}}
```

这里的 `/RUN_ROOT/...` 只是占位符，必须替换为内网真实绝对路径。`timeoutMs` 是总时长保险丝，不是重复输出检测器；长时间容器构建需在明确授权后适度提高。

## 结果与验收

- WU 的 `DONE` 只是子任务完成，不等于 G0–G4 的 `PASS`。
- 最终仍只能使用 `bisheng-executor` 定义的 `PASS`、`FAIL`、`ENV_BLOCKED`、`INCONCLUSIVE`、`NOT_RUN`、`BASELINE_REVIEW_REQUIRED`；运行器的子进程 `completed` 不等于完整验收成功。
- 任何日志缺失、Git 身份不明、进程/设备证据错误、后端 fallback、额外变更、Reviewer `REQUEST_CHANGES` 均不可宣称 Gate PASS。
- 写入 WU 回执后调用 `scripts/check_work_unit.py` 做字段、路径、角色、Git 身份和命令退出码的静态核对；它不能证明代码正确性。
- 最终 ROUND_REPORT 必须包含 `TASK_ID`、`BASE_SHA`、`TASK_START_SHA`、`FINAL_HEAD`、实际命令/退出码、首错、环境、证据路径、未运行项。

详细编排和异常恢复规则参见 `references/ORCHESTRATION.md`。不得自行添加其他模型、网络权限、后台循环或计划任务。
