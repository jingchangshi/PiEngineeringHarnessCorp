---
description: 以 Pi subagents 独立短会话完成一轮 Bisheng 外部授权 Task；不自动进入下一 Task/Gate
argument-hint: "<TASK_FILE_ABSOLUTE_PATH>"
---

使用已安装的 `bisheng-multiagent` Skill 作为 **Coordinator 调度协议**，并完整遵守 `bisheng-executor` 原始 Gate/证据契约。

先读取任务文件 `$1`，核对原始 TASK_ID、TASK_START_SHA、BASE_SHA/FROZEN_JSON、EXECUTION_ENV、RUN_ROOT 与允许修改的文件。调用本 Skill 的 `scripts/check_task_contract.py`，不满足则停止。

确认 `pi-subagents` 的 `bisheng-scout`、`bisheng-implementer`、`bisheng-verifier`、`bisheng-reviewer` 可用。只把当前 Task 拆成少量 Work Unit 卡，文件位于 RUN_ROOT（源码仓库外）；每个子任务显式 `context: "fresh"`。

有依赖的步骤串行执行；同一代码树最多一个 Writer。先探索（必要时）→ 最小实现（仅有授权时）→ 独立验证 → 独立审阅。子 Agent 回执只保留 SHA、实际命令/退出码、日志路径、首错及未验证项；不要把完整工具历史或日志回填父上下文。任何风险或失败都停止，不自动推进 Gate。

将真实 ROUND_REPORT 保存到 RUN_ROOT 后，复用原来的 `bisheng-export-evidence` 和 `verify_review_bundle.py` 输出 SHA 可校验的本轮证据包。外发须人工完成审批。

最终只报告本轮 TASK_ID、执行环境、Git 起点/终点、Work Units 结果、内网证据路径、Gate 状态、第一阻塞和待外部裁决项；然后停止。
