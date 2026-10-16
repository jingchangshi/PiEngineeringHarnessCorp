# 01｜源码与测试入口索引（读取本轮冻结 HEAD）

优先在**构建容器**的源码锚点 `/home/shijingchang/workspace/AscendNPU-IR-Dev` 查看源码。宿主若没有同一份冻结 HEAD 源码快照，应先按 `08_CONTAINER_HOST_HANDOFF.md` 交接，再运行 Host 测试 Runner。

## 1. 首先读取

| 顺序 | 文件 | 任务 |
| --- | --- | --- |
| 1 | `AGENTS.md` | 仓库本地约束与工具链 |
| 2 | `build-tools/build.sh` | **现行已验证的构建入口**、flags、publish install 行为 |
| 3 | `bishengir/bridge/CMakeLists.txt` | LLVM15 Bridge SDK 根、真实 build/install target |
| 4 | `bishengir/test/Acceptance/BishengDirectBackend/README.md` | Suite 与正向/负向运行条件 |
| 5 | `bishengir/test/Acceptance/BishengDirectBackend/cases.example.json` | 四场景的准确名字和 JSON 字段 |
| 6 | `bishengir/test/Acceptance/BishengDirectBackend/run_tests.py` | Suite 真实实现、能力探针和退出码 |
| 7 | `docs/bisheng-backend/build-and-deployment.md` | 仓库历史与辅助说明，需对照本轮内网命令 |
| 8 | `docs/bisheng-backend/runtime-verification-plan.md` | 历史运行时验证方案；旧 SHA 不是本轮基线 |

## 2. 构建链源码要点

- `build-tools/build.sh`：`-t` 开启 Template 构建；`--build-shmem-template` 开启 SHMEM Template；`--build-triton` 开启 Triton 编译功能。默认 `BISHENGIR_PUBLISH=ON`，`cmake_install()` 使用 `install-bishengir-publish-products`。
- `bishengir/bridge/CMakeLists.txt`：使用 `BRIDGE_BISHENG_COMPILER=<SDK root>` 中 LLVM15 headers/libs，通过 LLVM15 独立编译 Bridge；正常 CMake `install(FILES)` 未声明发布组件。因此可能缺少 Bridge 和 `lib_ccec`。
- `bishengir/lib/Tools/Utils/AuxBitcodePaths.cpp`：`resolveAuxBitcodePaths()` 根据实际 `optLevel` 选择 `.O2.bc`/`.O0.bc` 等路径；输出依赖 `<prefix>/lib`。
- `bishengir/lib/Tools/bishengir-compile/regbase/BiShengIRCompileMain.cpp`：A5 RegBase Pipeline 与 Retry 边界。

## 3. Backend 源码

| 生产模块 | 文件 |
| --- | --- |
| LLVM15 Bridge 主实现 | `bishengir/bridge/bisheng_bridge.cpp` |
| LLVM15 C ABI | `bishengir/bridge/bisheng_bridge_c_api.h` |
| Host Worker、Loader、Session | `bishengir/lib/Tools/hivmc/BishengBridge.cpp` |
| Process/Direct 选择和执行 | `bishengir/lib/Tools/hivmc/BackendExecutor.cpp` |
| A3 | `bishengir/lib/Tools/hivmc/A3/HIVMCMainA3.cpp` |
| A5 | `bishengir/lib/Tools/hivmc/A5/HIVMCMainA5.cpp` |
| Backend Config/Plan/argv | `bishengir/lib/Tools/hivmc/Utility.cpp` |

## 4. 验收测试入口

| 入口 | 用途 |
| --- | --- |
| `run_tests.py --suite offline` | Python/Host 控制流离线检查；不是设备 E2E |
| `run_tests.py --suite portable` | 仅独立隔离的 portable/缺 Bridge 部署 |
| `run_tests.py --suite integration` | Runtime、Timeline、Retry、生命周期与故障 |
| `run_tests.py --suite parity` | R/P/D、真实 execve 和 A3 MixCV 固定 pre-link IR |
| `three_way_parity.py` | 三路来源绑定、SHA、Lane 对照 |
| `portable_process.py` | Process/决策前降级与缺 Bridge 环境特例 |
| `goal_1009_runtime.py` | 四个场景 × Process/Direct 与调度策略的真实运行证据 |
| `session_lifecycle.py` | Session destroy/abandon 所有权边界 |
| `timeline_integration.py` | JSONL Timeline 与计时采集 |
| `bridge_lifecycle_unit.py` | Fake LLVM15 C ABI Host 测试；不是真实 LLVM15 结果 |

`run_tests.py` 定义：`0=PASS`、`1=FAIL`、`77=ENV_BLOCKED`；`--suite all` 同时混合不同部署前提，不作为一键正式验收。

## 5. 旧文档冲突的处理

- 旧 `runtime-verification-plan.md` 和 `testing.md` 包含 `dd0d380a`、`fix/bisheng-async-1010-review`、`15a14c58` 等历史身份；这些不是本轮动态 Reference。
- 旧审阅 `c6d405c5`/`29fc916b` 是历史比较锚，不应覆盖本轮 `frozen.json` 的结果。
- 旧文档的通用 CMake 示例不能替代用户已经成功使用的 `build-tools/build.sh` 命令。
- 当前生产 Bridge Path 由 Host 编译器 prefix 推导。`BISHENG_BRIDGE_PATH` 只供测试脚本探测，不可用作生产加载位置切换。
- 若生产文件随内网 Rebase 改变，先核查真实源码及 `git range-diff`；不要靠旧文档默认规则修补新代码。

## 6. 检索命令

```bash
cd /home/shijingchang/workspace/AscendNPU-IR-Dev
rg -n 'install-bishengir-publish-products|BISHENGIR_PUBLISH|BRIDGE_BISHENG_COMPILER|BISHENGIR_BUILD_TEMPLATE' build-tools bishengir
rg -n 'BISHENG_BACKEND_RESULT|BISHENG_BACKEND|dlmopen|directBackendExecuted' bishengir
rg -n 'resolveTemplateBitcodeOptLevel|resolveAuxBitcodePaths|\.O2\.bc|\.O0\.bc' bishengir
rg -n 'FinalCompileBundle|prepare_aux|prepare_aux_delta|serialize_cpu_work_ms' bishengir
```

读取具体函数、条件与输出，不只凭文件存在就判定行为正确。生产源码的真实性需使用本轮 `frozen.json` SHA 与内网实际工作树证明。
