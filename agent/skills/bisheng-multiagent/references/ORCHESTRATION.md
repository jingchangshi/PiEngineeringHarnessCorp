# Pi 1.2 + npm:pi-subagents 编排实施细则

## 固定分工

| 角色 | 子上下文 | 允许操作 | 回执定位 |
| --- | --- | --- | --- |
| 父 Coordinator | 原会话，仅存 WU 清单与状态 | 原 Task 校验、调度、归档脚本 | `ROUND_REPORT.md` |
| `bisheng-scout` | fresh | 只读定位源码/Git/环境；bash 仅允许无副作用查询 | `<RUN_ROOT>/multiagent/.../receipts/*-scout.json` |
| `bisheng-implementer` | fresh | 唯一 writer；仅授权文件 | `*-implementer.json` |
| `bisheng-verifier` | fresh | 授权构建/UT/Host 测试；可生成 RUN_ROOT 日志，不编辑产品源码 | `*-verifier.json` |
| `bisheng-reviewer` | fresh | 只读检查 Git diff/日志/验收缺口 | `*-reviewer.json` |

## 调度规则

1. 先调用 `subagent({action:"list"})` 或让 Pi 列出可用角色，确认配置已加载。
2. 原外部 Task 有 `RUN_ROOT`、`TASK_START_SHA` 和不可变变更范围。调用 `scripts/check_task_contract.py` 取得真实 Git 身份；如果失败则停止。
3. Scout/Verifier/Reviewer 在本轮同一 repo 的授权机器启动。不要因为 Agent 独立进程就假定它能访问宿主硬件、不同容器或其他 Home。
4. Worker 与任何会改动构建目录/安装目录的 Verifier **不能并行**。只读 reviewer 尽量在写入任务完成后启动。
5. 每个 WU 卡是唯一输入路径；回执和日志保存在 Git 仓库以外。无日志、无真实测试退出码不得写 PASS。读到 `REQUEST_CHANGES` 不能直接重试源任务：先让 Coordinator 比对原授权范围。
6. 如子 Agent 进入句子复读，立即通过 Pi 交互停止该运行，保存现有 diff；停止状态是 STOPPED/INCONCLUSIVE，不得把模型的最后一句当作回执。单次总 deadline 只是兜底。
7. `pi-permission-system`、`pi-lsp` 等父进程扩展**不一定在 foreground 子 Agent 中加载**。首次仅用无副作用任务检测是否可用；不要把 `tools: read,bash` 视为真正的只读沙箱。需要强制安全控制时在容器权限/文件系统层面实施并复测。
8. 最终只由 Coordinator 调用已安装的 `bisheng-export-evidence`，并执行包内 `verify_review_bundle.py`。不要让多个孩子并发对同一 zip 做修改。
9. 不复用前一个 Subagent 的会话；下一个 WU 只接收经过筛选的证据路径和最多 20 行摘要，不传历史对话全文。

## 异步模式

- 默认 `async:false`：更容易监督与停止，适合刚接入内网模型时冒烟。
- 确认子进程/SDK/认证/扩展兼容后，独立 **只读** Scout 可以改 `async:true`，但不要与 writer 争用同一 repo 或构建输出。
- 长耗时 G0/G2/G4 测试应划为单独 WU，明确授权完整命令和时间预算；不是自动增加 Agent 轮数。

## 成功标准

- WU 1 个 `DONE` ≠ Task PASS。验证只有原始命令/真实退出码；Reviewer 只是内部意见。
- Task 输出必须包含原始 `TASK_START_SHA`；P0 的 `AUTO_DISCOVER` 只在 P0 使用。
- 内网 evidence 包必须经人工审查公司数据出域规范，绝不自动上传。
