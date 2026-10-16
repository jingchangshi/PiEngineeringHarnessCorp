# 跨轮次证据导出契约

## 目标

一轮内部 Pi 任务只产生一个交付包。外部 ChatGPT 根据真实 Patch、版本 SHA、命令及测试证据审阅，再生成下一轮任务。内网 Agent 不负责独立架构裁决。

## 单轮身份

- `BASE_SHA`：P0 冻结的本次 Reference Process 基线。
- `FROZEN_HEAD_SHA`：P0 冻结的四个功能提交 HEAD。
- `TASK_START_SHA`：外部 ChatGPT 本轮任务开始时审阅并授权的准确 Git SHA。
- `FINAL_HEAD`：完成本轮任务后的 Git HEAD。

`TASK_START_SHA` 在后续任务可与 `FROZEN_HEAD_SHA` 不同。严禁用动态 `master` 覆盖 `BASE_SHA`。Patch 导出必须覆盖 commit、index、工作树中的**已跟踪文件**，并单独列出未跟踪文件。

## 标准流程

1. 外部生成 `TASK_ID.md`，写明输入 SHA、修改边界、退出条件和预期证据。
2. 内网人工将任务放入内网工作目录。Pi 校验任务中的 `TASK_START_SHA` 与 `git rev-parse HEAD`，不一致停止。
3. Pi 只执行这一个 Task，不自动继续 G0/G1/G2 等后续任务。
4. 把每条关键实际命令和退出码写入本轮 `commands.jsonl` 或 `command.txt`、`exit_code.txt`。
5. 把日志、Parity、Object SHA、Host 数值结果保存在内网 `RUN_ROOT`。不要调用模型编造 PASS。
6. 运行 `$HOME/.local/bin/bisheng-export-evidence`。导出脚本不会执行测试，也不会宣告 Gate PASS。
7. 人工审查导出包中的源码 Patch、日志、路径、设备信息和凭据。**只有经过公司的数据出域审批，才将批准的内容传到外部 ChatGPT**。
8. 外部 ChatGPT 审核通过后，生成下一轮明确的 Task ID、`TASK_START_SHA` 和门禁。

## 典型命令

```bash
# 工作目录与实际日志路径替换为本轮内网位置
REPO=/home/shijingchang/workspace/AscendNPU-IR-Dev
RUN_ROOT=/home/shijingchang/workspace/bisheng-async-acceptance-20261014
TASK=$RUN_ROOT/tasks/round-001.md
TASK_START_SHA=$(git -C "$REPO" rev-parse HEAD)

# 任务前将 TASK_START_SHA 写入/锁定任务文件，任务结束后使用原值。
# 注意下例假设你已保存 TASK_START_SHA；不能在任务结束后重新计算起点。
bisheng-export-evidence \
  --repo "$REPO" \
  --task-id G0B \
  --task-file "$TASK" \
  --report-file "$RUN_ROOT/reports/G0B-report.md" \
  --task-start "$TASK_START_SHA" \
  --frozen "$RUN_ROOT/git/frozen.json" \
  --allow-root "$RUN_ROOT" \
  --evidence "$RUN_ROOT/logs/G0B-current-build.log" \
  --evidence "$RUN_ROOT/evidence/G0" \
  --out "$RUN_ROOT/review/G0B-round-001" \
  --archive
```

`--untracked <relative-path>` 用于显式导出新建的源文件（以 Patch 形式）。脚本不会自行将整个仓库未跟踪文件外发。输出 ZIP 为**本地文件**，不是已获外发批准的产物。

## 机器生成的核心文件

- `task.md`：原任务说明副本。
- `git/frozen.json`、`git/commits.txt`、`git/status.txt`：版本身份和工作树。
- `patches/from-task-start.patch`：本轮已跟踪文件改动（含 commit 和工作树）。
- `patches/from-frozen-base.patch`：自 Reference Base 以来的已跟踪文件累计差异。
- `patches/untracked-selected.patch`：人工点名的新文件 Patch。
- `git/untracked-all.json`：未跟踪文件清单（默认不自动打包内容）。
- `evidence/`：显式指定且在允许根下的文本日志、IR、JSON 等。Object/BC/可执行文件只保存 SHA 及大小，不复制二进制本体。
- `manifest.json`：包含文件 SHA、警告、证据路径、环境来源；`COLLECTED` 不等于测试 PASS。
- `SHA256SUMS.txt`：导出包内文件哈希。
- `REPORT_FOR_REVIEW.md`：优先使用 `--report-file` 指向 Pi 在导出前写好的真实报告；不传时只有空白模板并产生警告。**不是**脚本生成的验证结论。

## 限制

- 脚本不清理工作树、不调用 Git Add/Commit、不访问网络、不读取 Pi 凭据、不自动上传文件。导出后使用 `scripts/verify_review_bundle.py --bundle <DIR>` 检查包内 SHA；不能在导出之后直接编辑包内文件。
- Binary SHA 与原始日志能支持 provenance，但不能单独证明设备数值正确。需要将数值测试和真实退出码一同交付。
- `COLLECTED_WITH_WARNINGS` 不代表任务失败或通过，必须人工核实警告。
- 本脚本无法保证自动识别所有商业秘密或密钥。即使未出现敏感路径告警，出域前仍应逐个文件审查。
