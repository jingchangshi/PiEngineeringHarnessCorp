# 07｜GLM 5.2 小任务卡（单次只执行一个）

| Task ID | 执行环境 | 唯一目标 | 交付证据 | 继续条件 |
| --- | --- | --- | --- | --- |
| `P0-C` | BUILD_CONTAINER | 冻结四提交栈，核查 SDK/CANN/Conda/build.sh 与构建缓存 | `frozen.json`、`container-preflight.json`、P0-C 报告 | 版本可证明且 SDK 可构建 |
| `P0-H` | HOST | 核查 Docker 挂载、宿主 CANN/CCEC、A3/A5 设备、输入 | Host 探针、mount、fixture 目录证据 | 拿到真实 Host 运行边界 |
| `P0-GATE` | HOST/READONLY | 汇总 P0-C/H，批准 G0 | P0 报告、阻塞矩阵 | Git frozen，构建前提符合 |
| `G0A` | BUILD_CONTAINER | 独立构建 `BASE_SHA` Process | Reference build log、exit、SHA | Reference 成功 |
| `G0B` | BUILD_CONTAINER | 构建 `HEAD_SHA` Host/Bridge；发布安装日志 | Build/Ninja log、Bridge target、exit/SHA | Current 和 Bridge 编译成功 |
| `G0C` | BUILD_CONTAINER + HOST 检查 | 完整 stage 安装、容器/宿主逐文件 SHA、ELF、Template、Host UT | `G0-report.md`、安装审计、Host ELF | 完整 G0 PASS |
| `G1-CASE-A3_PureAIV` | HOST | R/P A3 单 Lane 对照 | IR/Aux/argv/Object、设备输出 | Case 通过 |
| `G1-CASE-A3_MixCV` | HOST | R/P A3 双 Lane 对照 | 同上双 Lane | Case 通过 |
| `G1-CASE-A5_PureAIV` | HOST | R/P A5 PureAIV 对照 | 同上 + libdevice | Case 通过 |
| `G1-CASE-A5_MixCV` | HOST | R/P A5 双 Lane 对照 | 同上双 Lane | Case 通过 |
| `G1-GATE` | READONLY | 四场景 R/P 证据裁决 | `G1-report.md` | 四个 Case 合格 |
| `G2-CASE-A3_PureAIV` | HOST | Current Process/Direct 正向验收 | Marker、Object、数值 | Case 通过 |
| `G2-CASE-A3_MixCV` | HOST | 双 Lane Direct CodeGen | 同上 + Lane SHA | Case 通过 |
| `G2-CASE-A5_PureAIV` | HOST | PureAIV Topology/Direct | 同上 + 无非预期 AIC | Case 通过 |
| `G2-CASE-A5_MixCV` | HOST | 双 Lane Direct CodeGen | 同上 + Lane SHA | Case 通过 |
| `G2-ORACLE` | HOST | Integration/Parity + A3 Mix 固定 pre-link IR | `integration.json`、`parity.json`、Replay evidence | 同源可验证 |
| `G2-GATE` | READONLY | 四场景 Direct 与三路验证裁决 | `G2-report.md` | G2 PASS |
| `G3-F1` 到 `G3-F14` | HOST 独立故障 stage | 每次只执行一个故障 | 注入+退出码+Marker+清理 | 单项裁决 |
| `G3-GATE` | READONLY | 无 fallback/无错误 Retry/生命周期 | `G3-report.md` | G3 PASS |
| `G4-CASE-<case>` | HOST | 某场景 3 预热 + 20 有效样本/Backend | Raw CSV/JSONL、exit/SHA | 单项可统计 |
| `G4-GATE` | READONLY | p50/p90/速度比、资源条件 | `G4-report.md` | 用户最终裁决 |

## 每轮通用收尾格式

```text
TASK_ID:
EXECUTION_ENV: BUILD_CONTAINER / HOST / READONLY
BASE_SHA:
HEAD_SHA:
STATUS: PASS / FAIL / ENV_BLOCKED / INCONCLUSIVE / BASELINE_REVIEW_REQUIRED
ACTUAL_COMMANDS_AND_EXIT_CODES:
EVIDENCE_PATHS:
FIRST_BLOCKER:
NEXT_TASK_ALLOWED: YES / NO
NEXT_TASK_ID:
本 Task 已结束，未运行后续 Task。
```

**注意：** 不允许在一个 GLM 5.2 会话里连续将 G0–G4 都自动执行。第二会话或另一名验证者应独立审查 Gate 证据；同一会话的自查不能称作独立复核。
