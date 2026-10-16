---
description: 执行一轮由外部 ChatGPT 授权的 Bisheng Task；完成后停止
argument-hint: "<TASK_FILE_PATH>"
---

先显式读取已安装的 `bisheng-executor/SKILL.md`（优先 `~/.pi/agent/skills/bisheng-executor/SKILL.md`，或项目 `.pi/skills/bisheng-executor/SKILL.md`），然后读取本轮 Task 文件 `$1`。

只执行 Task 指定的一个 `TASK_ID`。开始前核对任务中的 `TASK_START_SHA` 与真实 `git rev-parse HEAD`；P0 只读冻结任务属于例外。记录执行环境、退出码、证据及停止条件。不得扩展范围、自动推进下一个 Task、编造 PASS 或向外网传输任何内网内容。

结束后依据 `references/12_EXPORT_CONTRACT.md` 调用 `bin/bisheng-export-evidence`，或给出可复制的命令，并输出标准任务回执。如果缺少真实环境或资料，报告对应 `ENV_BLOCKED` / `INCONCLUSIVE` 并停止。
