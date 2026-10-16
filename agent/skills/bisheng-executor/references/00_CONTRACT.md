# 00｜版本冻结与验收契约

## 1. 本轮不可变事实

| 项目 | 值或规则 |
| --- | --- |
| 源码锚点（容器） | `/home/shijingchang/workspace/AscendNPU-IR-Dev` |
| 构建容器 | `triton-build-jcshi` |
| 构建入口 | `build-tools/build.sh`，CMake + Ninja |
| 测试执行机器 | Docker 宿主机，不是构建容器 |
| 旧审阅 Base/HEAD，仅供历史比对 | `c6d405c50744f476599282b51a3a002e847e798f` / `29fc916bf6ce2c690566536a34b0b4cc208e1303` |
| 历史 Process 行为基线，不是本轮二进制 Golden | `15a14c58b9f7033dfce8db697a51ecccdb217a6f` |
| 本轮 BASE_SHA/HEAD_SHA | **P0 在内网实际 Git 冻结。不得提前猜测或硬编码。** |
| 预期功能提交数 | 恰好 4 个，线性提交 |

**警告：在尚未冻结 Base/HEAD 时，不得启动 G0。** 运行 `scripts/freeze_baseline.py`，检查 `HEAD~4`、本地 `master` 的共同祖先和四个提交标题。P0 证据须保存原始 Git 命令、SHA、工作树状态。`master` 即使后来前进，后续仍应使用本轮冻结的准确 Base Commit；不能把变化后的 master tip 替换 Reference。

若结构不是四个线性提交，或本地 `master` 无法证实功能栈基线，应报告 `BASELINE_REVIEW_REQUIRED`，停止。若同目录含未提交代码，Git SHA 不能代表构建输入；不得在该目录声称可复现。应先生成不修改原目录的干净工作树，并再次核验。

Rebase 产生新 SHA 并不说明代码补丁一定变化。若旧审阅 SHA 仍在本地对象库，宜用 `git range-diff OLD_BASE..OLD_HEAD BASE_SHA..HEAD_SHA` 核对语义差异。`range-diff` 缺失不视作代码一致性 PASS；需交付人工复核结论。

## 2. 三路编译器身份

```text
Reference (R) = BASE_SHA     + BISHENG_BACKEND=process
Current   (P) = HEAD_SHA     + BISHENG_BACKEND=process
Direct    (D) = HEAD_SHA     + BISHENG_BACKEND=inprocess_session

G1: R / P
G2: P / D，并以独立 R/P/D + A3 MixCV 固定 pre-link IR replay 证明来源
```

Reference 和 Current 应是两个独立源树、两个独立构建目录、两个安装 prefix。P/D 只能复用同一 HEAD 编译器，通过环境变量选 Backend。**不得以一个二进制复制两份文件冒充 R/P。**

四个用例名严格为：`A3_PureAIV`、`A3_MixCV`、`A5_PureAIV`、`A5_MixCV`。源码 `cases.example.json` 的设备 Target 仅为示例值。应使用内网真实设备与经验证的 bcmlir/BC 输入。

## 3. 构建与运行边界

1. 只能在 Docker 容器 `triton-build-jcshi` 内执行构建、CMake、Ninja 与 Host-only UT。
2. Host 端负责运行已部署的 `bishengir-compile`、真实 `bisheng` 子进程、Direct 加载、四场景 Runtime Suite 和真实 NPU E2E。
3. 构建用 CCEC 前端路径与 Bridge SDK **不同**。绝不能将 Bridge SDK 指向 `.../default/ccec_compiler/bin`。
4. 不得默认容器路径在宿主机存在。P0 应保存 `docker inspect` mount 证据或 `docker cp` 的复制清单及 SHA。
5. 宿主机需要重新核实 CANN 环境、`bisheng` 路径、动态库和 NPU；容器内 `source set_env.sh` 不会自动改变宿主环境。
6. `BISHENG_BRIDGE_PATH` 是测试侧定位变量；生产加载器使用 `CURRENT_BUILD_BIN` 所在 prefix 下 `lib/libbisheng_bridge.so`。

## 4. 保持的架构

- Process 保留有序 Aux BC、重复 occurrence，并由外部 Bisheng 链接；不做 LLVM19 Aux 预链接。
- Direct 经 C ABI 的 LLVM15 Bridge 执行 `EmitBackendOutput`；LLVM19 Host 不直接链接 LLVM15。
- Direct 一旦选定后，Init/Prepare/CodeGen/Mix Link/Relocation 失败应终止；不得偷偷回退 Process 或进入新的 Backend Attempt。
- 保留既有的 AIC/AIV Worker、Ticket、Base Aux、Final Aux Delta、Session、AIC/AIV 并行 CodeGen。
- 不增加 NamespaceOnly、低资源调度、新线程池、LLVM19 并行 IR 序列化。
- 不自行改变 LLVM15 选项、TargetMachine/Pass Pipeline、Session 析构。

## 5. 状态与 Gate

| 状态 | 定义 |
| --- | --- |
| `PASS` | 本轮代码、环境、命令、退出码与产物均有直接证据满足合同 |
| `FAIL` | 真实检查运行后违反合同或退出失败 |
| `ENV_BLOCKED` | 缺少工具、厂商依赖、设备或真实输入，未运行到目标行为 |
| `INCONCLUSIVE` | 运行过，但缺少必要 provenance/IR/Aux/数值证据 |
| `NOT_RUN` | 尚未执行 |
| `BASELINE_REVIEW_REQUIRED` | Git 结构不符合预期，须人工确认基线（本包自身状态，非 runner 退出码） |

权威 `run_tests.py` 的退出码是 `0 PASS`、`1 FAIL`、`77 ENV_BLOCKED`。它没有 `INCONCLUSIVE` 退出码。Gate 不得将模拟测试或旧日志冒充真实运行证据。

| Gate | 必需证据 |
| --- | --- |
| P0 | Git 基线冻结、容器 SDK 与 Host 路径、挂载映射、设备与真实 fixture 状态 |
| G0 | 两份编译器独立构建；Current 的真实 LLVM15 Bridge 编译、独立安装；容器/宿主动态链接与 Template BC 检查 |
| G1 | R/P 四场景 Process：输入、Aux、真实 execve、Lane/final Object 与宿主设备数值 |
| G2 | P/D 四场景实际 Direct；三路 Parity + A3 Mix 固定 IR Replay + 宿主 NPU 正确性 |
| G3 | 真正触发的故障注入、无错误回退、Ticket drain、Retry 边界、CLI 生命周期 |
| G4 | G2/G3 门禁满足后，3 次预热 + 至少 20 个有效样本/场景/Backend，p50/p90 与完整测量条件 |

字节级不一致时，不得直接用“数值正常”豁免 Parity；先比较 pre-link IR、Ordered Aux、TargetMachine 和真实优化选项，再定位原因。

## 6. 权限与暂停条件

- 默认只读源码、不改生产文件、不推送 Git、不覆盖现有工作目录和安装包。
- 禁止 `sudo`、`git reset --hard`、`git clean -fdx`，以及覆盖厂商 SDK。
- `build.sh` 在触发重建时可能清理构建目录的 CMake 文件；已有 `./build` 未确认前不得盲目重建。应优先新建隔离 build 目录，或在证据确认后复用。
- `run_tests.py --suite all` 混合多种部署前提，正式门禁分别运行 `offline`、`integration`、`parity`；`portable` 在隔离环境运行。
- P0/G0/G1/G2/G3/G4 任一 Gate 失败或来源不可证明时，停止推进。记录首次失败，不自动修改源码后继续冒称原 SHA。
- 单轮 GLM 5.2 只执行一个 Task ID，完成后保存证据并停止。
