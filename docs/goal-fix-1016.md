# 任务：PiEngineeringHarnessCorp 工具调用可靠性最小修复

你是当前 PiEngineeringHarnessCorp 仓库的 Coding Agent。请直接审阅代码、实现修复、编写必要测试并完成验证。除确实无法访问的运行环境外，不要只给出实施计划。

## 1. 目标与约束

仓库：https://github.com/jingchangshi/PiEngineeringHarnessCorp

基准：master 分支，起始参考 commit 为 `87e5511`。先检查当前 HEAD、分支及工作树，允许仓库已有新的提交，不要覆盖用户修改。

运行环境：公司内网 Linux，Pi Agent 1.2.0，使用本地 `127.0.0.1:8787/v1` 代理接入 DeepSeek V4 Flash CodeAgent 和 GLM 5.2。

历史故障：2026-10-14 至 2026-10-16 的 23 个 Pi 会话中，报告有约 101 次工具参数校验失败、34 次 Bash 非零退出，以及引号、权限、依赖和 Subagent 故障。

核心目标：

1. 对确定可恢复的工具参数包装错误，在 Schema 校验前完成修复。
2. 消除现有参数修复 Extension 的实现缺陷。
3. 修复子代理模型路由和并发配置问题。
4. 降低常见 Bash、容器权限和工具缺失错误。
5. 保持现有 Pi/Bisheng 工作流正确性。

必须遵守：

- 保留 `credir-status.ts` 中 `rejectUnauthorized: false`，这是内网实测所需行为。
- 不处理仓库公开性或内网信息公开问题。
- 不修改 `agent/models.json` 的 Provider、模型 ID、Base URL、API Key 和协议。
- 不升级 Pi Agent、`pi-subagents` 或其他 npm 插件，除非发现无法通过现有版本实现的确切兼容性缺陷；此时先报告，不直接升级。
- 不修改 Pi Agent 核心源码。
- 不重构 Bisheng Executor、Multiagent、One Writer、Git SHA/Gate、容器构建/宿主执行及证据交接协议。
- 不开发通用 Tool Call Linter、复杂 Shell 解析器、自动 chown 框架、自动安装器、动态 Prompt 注入系统或新多 Agent 调度系统。
- 不使用 `git reset --hard`、`git clean -fdx`，不自动推送远端。
- 只修改为完成本任务所必需的文件。

## 2. 阶段 A：核对实际故障与 Pi 工具调用机制

先读取：

- `agent/extensions/arg-frame-fix.ts`
- `agent/settings.json`
- `agent/models.json`
- `agent/extensions/subagent/config.json`
- `agent/AGENTS.md`
- `agent/agents/*.md`
- `migrate.sh`

确认本机安装的 Pi 版本以及 `pi-subagents` 版本，以**实际安装源码**为最终依据。

Pi 1.2.0 上游参考：

- `packages/agent/src/agent-loop.ts`
- `packages/coding-agent/src/core/tools/{bash,edit,write,read}.ts`
- `packages/coding-agent/src/core/agent-session.ts`
- `packages/coding-agent/src/core/extensions/types.ts`

已知 Pi 1.2.0 的调用顺序为：

`prepareArguments → validateToolArguments → beforeToolCall/tool_call → execute`

因此现有 `arg-frame-fix.ts` 在 `tool_call` Event 中修复已触发 Schema 校验失败的参数，挂载位置是不正确的。

如可访问 `~/.pi/agent/sessions/`，使用一次性脚本抽样检查 2026-10-14 至 2026-10-16 的相关 JSONL。

重点确定：

- 错误调用中多余 `arguments` 的具体形态。
- 错误发生在哪些工具、模型、父/子 Agent。
- 错误是否可能来自本地 8787 代理。
- 历史故障是否已经发生在当前 Extension 部署之前。
- 使用 session/toolCallId 去重，区分参数错误、命令非零退出和其他错误，避免重复统计。

如可访问代理源码或原始响应，核对模型响应在进入 Pi 之前是否已被错误包装。没有证据时不得直接断言代理有缺陷，也不能宣称已完成端到端根因证明。

诊断使用临时脚本即可，不要为了这一步新建长期日志框架。

## 3. 阶段 B：实现 P0 最小修复

### B1. 修正参数包装

优先修复经阶段 A 确认的最早出错层。

如果是代理重复包装工具参数，且代理代码不属于当前仓库：

- 不擅自修改其他仓库；
- 记录最小复现和代理侧应修改的位置；
- 继续完成本仓库独立可实施的修复。

如果是模型原始工具参数已经多包一层，或本仓库需要兼容该形态：

改造 `agent/extensions/arg-frame-fix.ts`，使规范化发生在 Schema 校验之前。

Pi 1.2.0 已有 `ToolDefinition.prepareArguments` 机制，工具定义也可通过 `createBashToolDefinition`、`createEditToolDefinition`、`createWriteToolDefinition` 等工厂创建。

先验证通过 Extension 注册同名工具定义覆盖内置工具的真实效果。

可以复用原始工具定义，通过其 `prepareArguments` 增加一次有限归一化；必须保留原有的执行实现、Schema、渲染、超时、原生 edit 兼容及本机已生效的 Shell 选项。

仅对完全无歧义的形态解包：

- `{arguments: '{"command":"pwd"}'}` → `{command:"pwd"}`
- `{arguments: {command:"pwd"}}` → `{command:"pwd"}`

约束：

- 顶层应当只有 `arguments` 这个包装字段。
- 字符串必须是合法 JSON 对象。
- 不猜测缺失字段，不处理任意深度嵌套。
- 不支持任意别名推断，如 `payload`、`args`、`input`，除非真实日志证明必要。
- 正确参数必须保持不变。
- `write.content` 必须保持字符串，允许空字符串和看似 JSON 的文本。
- `edit` 的单对象、JSON 字符串及 legacy 兼容必须保留 Pi 原生行为。
- 真正缺少必需字段的调用，仍交给正常 Schema 校验返回失败。
- 不打印完整 Tool Call 参数以免泄露命令中的凭证。

可以根据真实失败范围优先覆盖 bash、edit、write、read，不必盲目覆盖所有工具。

如果无法安全保留原始内置工具语义，则不要强行注册同名工具；在本仓库先停用旧 Extension 的有害修复逻辑，并输出该技术阻塞和最小替代方案。

### B2. 修正配置

在 `agent/settings.json` 中，按 `models.json` 已有真实 ID，将：

`bisheng-verifier` 和 `bisheng-reviewer`

映射为：

`snapengine/DeepSeek-V4-Flash-0731-CodeAgent`

不修改 `models.json`。

在 `agent/extensions/subagent/config.json` 中，将：

`globalConcurrentcyLimit`

修正为：

`globalConcurrencyLimit`

保持数值 2。

验证配置能被已安装的 `pi-subagents` 正确读取，检查 `/subagents-models` 和 `/subagents-doctor`。若现场模型路由另有覆盖，应报告最终生效值，而不能仅依据 JSON 判断。

### B3. 覆盖实际运行的子 Agent

确认 `bisheng-scout`、`bisheng-implementer`、`bisheng-verifier`、`bisheng-reviewer` 的前台子进程是否加载参数修复。

如果没有，参考已安装 `pi-subagents` 对 `extensions`、`subagentOnlyExtensions` 或 `defaultSubagentOnlyExtensions` 的支持方式，增加最少的显式加载配置。

只加载必要的兼容 Extension，不让子 Agent 无条件继承全部父级插件。

确认父 Agent 与四个子 Agent 的相关调用都能通过同样的回归测试。

## 4. 阶段 C：Bash 与环境问题的轻量修复

编辑 `agent/AGENTS.md`，补充短小的操作规范：

- 普通 Bash 命令继续直接执行。
- 复杂 `docker exec ... bash -lc`、多行 Python、存在多层引号的组合脚本，优先使用 `docker exec -i ... bash -s` 配合 heredoc，或事先生成 `.sh`/`.py` 文件。
- 首次使用某个非必备命令时，通过 `command -v` 检测是否安装。
- 只有语义等价时才允许使用替代命令。
- 对需要写入的 RUN_ROOT，开始任务前检查真实 UID/GID 与可写权限。
- 发生权限错误时不自动 `chown -R`，只在已授权目录和权限范围内修复。
- 同样的错误重复出现时，最多做一次有根据的针对性重试，随后报告阻塞。

不要开发 Bash 命令拦截器、依赖管理器或通用环境修复器。

对于报告里的 Subagent 超时和非 Git 目录故障，只做源码/日志核查。若无法复现，不修改 `pi-subagents` 内部恢复实现。

## 5. 阶段 D：必要测试和实际验证

为参数归一化补充简单、可直接执行的自动测试。

必须覆盖：

1. 正确参数保持不变。
2. `arguments` 为合法 JSON 字符串时可解包。
3. `arguments` 为对象时可解包。
4. `arguments` 字符串非法时不执行工具。
5. `{}`、缺少 path/command 等真实非法参数不被猜测补全。
6. 顶层存在字段冲突时不自动覆盖。
7. `write.content=""` 合法。
8. `write.content='{"a":1}'` 保持字符串。
9. `edit.edits` 单对象、JSON 字符串和 legacy 格式不退化。
10. 参数在 Schema 校验之前归一化，而非校验失败之后。
11. 实际工具执行没有被意外调用多次。
12. 父 Agent、需要修复的前台子 Agent 都能正确使用该功能。

优先使用现有 Node/TypeScript 测试环境，不引入测试框架或新依赖。测试应使用临时文件和无副作用命令，不使用真实生产源码作为修改对象。

如公司网关可访问，分别使用 GLM 5.2 和 DeepSeek V4 Flash CodeAgent 进行最小真实 Tool Calling Smoke Test。

如果模型、代理或容器环境不可用，明确标记 `NOT_RUN` 或 `ENV_BLOCKED`，不要用 Mock 成功冒充真实 E2E PASS。

检查现有 Bisheng SKILL、Prompt、Subagent Agent 定义和迁移脚本是否保持正常。

## 6. 交付要求

只保留完成上述目标必需的修改与测试。

完成后输出：

- 修改文件列表及每项修改目的。
- 参数错误根因：已证实部分与尚未证实部分分别说明。
- `arg-frame-fix` 最终实现位置及实际生效证据。
- 修正后的模型路由和并发配置。
- 自动测试结果。
- 父/子 Agent 真实 Smoke Test 结果。
- 目前仍然存在的环境阻塞。
- 配置迁移与重启 Pi 的最小操作命令。
- `git diff --check` 结果和最终 Git diff 摘要。

如果需要部署到 `~/.pi/agent/`，先运行 `migrate.sh` 的 dry-run，确认覆盖范围并保留已有配置备份。不得未经检查直接覆盖本机配置。

不要擅自执行 Git push、重置工作树或修改其他仓库。

完成实际实现与测试后停止，不自行开展新的架构重构或第二轮优化。

最终判断以这四个目标为核心：

**可恢复错误减少、不产生误修复、不损害原工具语义、父子 Agent 行为一致。**

