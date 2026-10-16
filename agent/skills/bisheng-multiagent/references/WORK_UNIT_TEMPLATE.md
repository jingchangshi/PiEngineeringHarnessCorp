# Work Unit: <TASK_ID>-WU01

- PARENT_TASK_ID: <已授权的 TASK_ID>
- WORK_UNIT_ID: <TASK_ID>-WU01
- TASK_START_SHA: <外部授权原始 SHA，不随本轮更新>
- BASE_SHA: <P0 已冻结的 Reference SHA>
- EXECUTION_ENV: BUILD_CONTAINER / HOST / READONLY
- SOURCE_REPO: <绝对路径>
- RUN_ROOT: <必须位于源码 Git 工作树外的绝对路径>
- DEPENDS_ON: NONE / <WU ID + 已验收的回执文件>
- OWNER_ROLE: bisheng-scout / bisheng-implementer / bisheng-verifier / bisheng-reviewer

## 唯一目标

<一个可验证子目标，不拆成额外的 GATE 或 Task>

## 必要输入

- 已授权外部 TASK 文件绝对路径：
- 冻结 Git、日志或前置 WU 精简回执路径：
- 必要源码文件与符号：

## 授权范围

- 允许修改的源码文件（读写 Agent）：
- 不得修改的源码/Golden/安装目录：
- 允许执行的命令、运行环境与具体 cwd：

## 验收边界

- 预期结果及可核验退出码：
- 真实日志/对象/IR/测试证据路径：
- 停止条件与首个失败点：

## 最小回执

将回执写在 `RUN_ROOT/multiagent/TASK_ID/receipts/WORK_UNIT_ID-ROLE.json`。
不要将大日志粘贴回父 Agent；确保命令和文件实际存在。
