# 05｜证据目录、Manifest 与报告模板

**原则：证据分为构建容器与宿主机两部分。** 同一个 Gate 引用的 SHA 应绑定相同冻结源码与对应安装产物。日志与厂商二进制仅保存在公司内网。

## 1. 宜目录

```text
bisheng-async-acceptance-YYYYMMDD/
  git/
    frozen.json                         # BASE_SHA、HEAD_SHA、master_ref、4 commit list
    range-diff.txt                      # 可获得时
  source/reference/                    # 容器内独立 worktree；不改原 Dev 源码
  build/reference/                     # 容器构建目录
  build/current/                       # 只有不复用 ./build 时才使用
  stage/reference/                     # 容器隔离安装
  stage/current/
  logs/
    G0A-reference-build.log
    G0B-current-build.log
    G0B-incremental-publish.log
    G0C-current-full-install.log
  evidence/
    container-preflight.json
    host-preflight.txt
    docker-mounts.txt
    transfer-sha256.txt
    manifest.json
    G0/{source,cmake,build,install,host-elf,template,ut}/
    G1/{A3_PureAIV,A3_MixCV,A5_PureAIV,A5_MixCV}/{R,P}/
    G2/{A3_PureAIV,A3_MixCV,A5_PureAIV,A5_MixCV}/{P,D,parity}/
    G3/{F1,F2,F3,F4,F5,F6,F7,F8,F9,F10,F11,F12,F13,F14}/
    G4/{A3_PureAIV,A3_MixCV,A5_PureAIV,A5_MixCV}/
    P0-report.md
    G0-report.md
    G1-report.md
    G2-report.md
    G3-report.md
    G4-report.md
```

`RUN_ROOT` 的具体路径应由本轮用户确认。宿主和容器根路径可能不同，需在 `manifest.json` 分别登记；不要假设 Docker 自动共享两个目录。每个任务单独保存 `command.txt`、`exit_code.txt`、`stdout.log`、`stderr.log`。含 `tee` 的构建命令应保存 `PIPESTATUS[0]`。

## 2. Manifest 示例（值由本轮证据填充）

```json
{
  "schema_version": "2.0",
  "status": "NOT_RUN",
  "source": {
    "anchor_container": "/home/shijingchang/workspace/AscendNPU-IR-Dev",
    "base_sha": null,
    "head_sha": null,
    "master_ref_sha_at_freeze": null,
    "commit_count": 4,
    "git_clean": null,
    "source_equivalence_review": null
  },
  "build_container": {
    "name": "triton-build-jcshi",
    "cann_script": "/home/shijingchang/CANN/cann/set_env.sh",
    "conda_env": "triton-py311",
    "bisheng_frontend_bin": "/home/shijingchang/workspace/ccec-toolkits/default/ccec_compiler/bin",
    "bridge_sdk_root": "/home/shijingchang/workspace/ccec-toolkits/bisheng-install-llvm-dylib/ccec_compiler",
    "cmake_flags": null,
    "reference_binary_sha256": null,
    "current_binary_sha256": null,
    "bridge_sha256": null,
    "llvm15_sha256": null,
    "clang15_sha256": null,
    "template_bc_sha256": null
  },
  "container_to_host": {
    "docker_mounts_log": null,
    "transfer_method": null,
    "host_stage_root": null,
    "per_file_sha_comparison": null
  },
  "host_runtime": {
    "host_os": null,
    "cann_version": null,
    "bisheng_executable_sha256": null,
    "host_ldd_readelf": null,
    "a3_device": null,
    "a5_device": null,
    "driver": null,
    "cpu_quota": null,
    "memory_limit": null
  },
  "cases": [
    {"name": "A3_PureAIV", "source_sha256": null, "aux_ordered": [], "device_result": null},
    {"name": "A3_MixCV", "source_sha256": null, "aux_ordered": [], "device_result": null},
    {"name": "A5_PureAIV", "source_sha256": null, "aux_ordered": [], "device_result": null},
    {"name": "A5_MixCV", "source_sha256": null, "aux_ordered": [], "device_result": null}
  ],
  "gates": {"P0": "NOT_RUN", "G0": "NOT_RUN", "G1": "NOT_RUN", "G2": "NOT_RUN", "G3": "NOT_RUN", "G4": "NOT_RUN"}
}
```

空值应代表尚无证据，不能由 Agent 填入猜测。`aux_ordered` 应按真实调用顺序保存路径、Lane、occurrence、SHA；重复 BC 的 occurrence 不得合并。

## 3. 单任务输出模板

```markdown
# TASK_ID 报告

- STATUS: PASS / FAIL / ENV_BLOCKED / INCONCLUSIVE / BASELINE_REVIEW_REQUIRED
- EXECUTION_ENV: BUILD_CONTAINER / HOST
- FROZEN_BASE_SHA:
- FROZEN_HEAD_SHA:
- SOURCE_STATUS: CLEAN / DIRTY / UNKNOWN
- FIRST_FAILED_COMMAND:
- LOG_PATHS:
- EXIT_CODES:
- BINARY_AND_INPUT_SHAS:
- VERIFIED_FACTS:
- UNVERIFIED_FACTS:
- NEXT_TASK_ALLOWED: YES / NO
- NEXT_TASK_ID:

| Check | Actual command/log | Return code | Observed result | Decision |
| --- | --- | --- | --- | --- |
| ... | ... | ... | ... | ... |

最后写：已停止，未执行下一 Task。
```

## 4. 最终 Gate 表

| Gate | 状态 | 核心证据 | 尚不能证明的内容 | 是否允许下一阶段 |
| --- | --- | --- | --- | --- |
| P0 | NOT_RUN | Git、SDK、Docker mount、Host CANN/NPU | ... | NO |
| G0 | NOT_RUN | R/P/Bridge 构建、安装、Host ELF、Template | ... | NO |
| G1 | NOT_RUN | R/P 四场景真实运行、Object/数值 | ... | NO |
| G2 | NOT_RUN | Direct Marker、Parity/Replay、NPU | ... | NO |
| G3 | NOT_RUN | 故障注入、无回退、Session 生命周期 | ... | NO |
| G4 | NOT_RUN | 四场景 20 次有效样本、p50/p90 | ... | NO |

**注意：** 每个 PASS 应引用本轮新生成的日志、退出码和 SHA。`SOURCE_READY`、Fake Bridge、离线测试、旧文档中的 Freeze/Parity 结果均不能代替本轮真实 E2E。
