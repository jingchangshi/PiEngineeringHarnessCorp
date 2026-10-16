# 06｜GLM 5.2 分阶段执行提示词

使用方式：首次仅发 `START_PROMPT.txt`。此后用户逐次发送对应的 Task ID 与本文件中的短提示词。Agent 每次应先读本 Task 指定的材料和上阶段报告；一次只做一个任务。**不能直接发送本文件后要求“全部完成”。**

## 0. 每轮共用规则

> 你是 AscendNPU-IR 的内网验证执行者，不是系统重新设计者。首次阶段只读，后续按 Task 卡执行。你应在每次答复中列出实际执行环境（`BUILD_CONTAINER` 或 `HOST`）、本轮冻结的 Base/Head SHA、命令、退出码、证据绝对路径、最早失败点、是否准许继续。未执行的事项写 `NOT_RUN`；缺运行条件写 `ENV_BLOCKED`；证据不充分写 `INCONCLUSIVE`。不存在的目录或 flag 不得猜测或虚构。不得同时执行多个 Task，不得自行修改源码、重编 LLVM15、重写架构或推送代码。每次只执行一个 Task，然后停止。

### P0-C：构建容器与 Git 基线冻结

> 仅执行 `P0-C`，不得构建。读取 `00_CONTRACT.md`、`02_G0_BUILD.md`、`08_CONTAINER_HOST_HANDOFF.md`。在宿主使用 `docker exec -it triton-build-jcshi bash` 进入容器。在容器按给定路径 `source /home/shijingchang/CANN/cann/set_env.sh`、`conda activate triton-py311`，并进入 `/home/shijingchang/workspace/AscendNPU-IR-Dev`。先检查 Git status、HEAD、`master`、四提交结构，使用 `scripts/freeze_baseline.py` 生成新鲜 `frozen.json`。再核查两个不同 CCEC 路径：前端 `.../default/ccec_compiler/bin`；Bridge 根 `.../bisheng-install-llvm-dylib/ccec_compiler`。检查 LLVM15 headers、3 个预期链接文件、CMakeCache、`build.sh` flags、CPU/内存、子模块。记录已有 `./build` 能否安全复用。若 Git 不满足四提交或有 dirty 源码，禁止宣称可重复构建；提出干净 worktree 方案并停止。报告 `P0-C-report.md`、`frozen.json`、`container-preflight.json`。到此停止。

### P0-H：宿主机与容器产物路径盘点

> 仅执行 `P0-H`，不调用构建或正式编译。读取 `08_CONTAINER_HOST_HANDOFF.md`。在 Docker 宿主机 `docker inspect triton-build-jcshi`，记录 `.Mounts` 与容器源码、RUN_ROOT 到宿主的实际映射。执行 `scripts/check_host_ready.sh`，定位 Host CANN、`bisheng`、`strace`、`readelf`、`npu-smi` 与运行用 Python。核查是否有 A3/A5 真实设备、四个真实输入和原有数值校验用例。不存在时记录缺件，不得使用容器结果冒充宿主。报告 `P0-H-report.md`，指出 Host 后续 stage 是共享访问还是需要 `docker cp`。到此停止。

### P0-GATE：裁决是否开始 G0

> 仅复核 P0-C/H。核对 `frozen.json` 中四个线性提交、Git 工作树、Vendor LLVM15 SDK、容器 CANN/Conda、宿主挂载与设备的来源证据。Fixture 缺失不妨碍 G0 构建，但阻止 G1；Host 当前缺设备不阻止 G0，但阻止对应设备 E2E。只输出 `G0_ALLOWED`、证据、未满足项，停止。

### G0A：Reference Process 独立构建

> 仅执行 G0A。读取 `02_G0_BUILD.md` 和冻结 SHA。应在 `triton-build-jcshi` 内，从源码锚点创建独立、干净的 `BASE_SHA` worktree；先核实其 `third-party`/submodule 依赖与冻结源一致。用与现有内网一致的 `build-tools/build.sh` 命令构建，保留 `clang/clang++`、`-DLLVM_ENABLE_LLD=ON`、`Release`、`--disable-werror`、`--disable-bishengir-werror`、`--build-triton`、`--build-shmem-template`、`-t`、前端 CCEC 路径和 `-j64`；Reference 应选择 Process-only/禁用 Bridge。构建输出应与 Current 隔离。保留完整命令、`PIPESTATUS[0]`、CMakeCache、二进制 SHA 和真实最早错误。失败只诊断，不自动修改源码。停止。

### G0B：Current 编译器与 Bridge 构建

> 仅执行 G0B。应在构建容器的 `/home/shijingchang/workspace/AscendNPU-IR-Dev`，或由其相同冻结 HEAD 创建的干净 worktree 内构建。优先使用用户提供的原始 `build.sh` 参数，不遗漏 `--bridge-bisheng-compiler=/home/shijingchang/workspace/ccec-toolkits/bisheng-install-llvm-dylib/ccec_compiler`。在选择 `--build ./build` 前先检查该 build 的 CMakeCache 是否对应这次 SHA；否则使用新隔离 build，并相应更新 Ninja 路径。验证 `bisheng_bridge` target 实际存在且完成构建。把 `ninja -C build -j64 install-bishengir-publish-products` 的结果标记为发布安装，不准因此宣布 Bridge 部署完成。交付 Host/Bridge SHA、完整日志、退出码；停止。

### G0C：隔离安装与容器/宿主校验

> 仅执行 G0C。首先在容器对 Current 的正确 build 目录显式构建 `bisheng_bridge`，再用 `cmake --install <build> --prefix <fresh-stage>` 在全新 stage 安装。Reference stage 独立；禁止覆盖旧安装和 CANN。检查当前 stage 的 `bin/bishengir-compile`、`lib/libbisheng_bridge.so`、`lib/lib_ccec/libLLVM-15.so`、`lib/lib_ccec/libclang-cpp.so.15`；检查 ELF `DT_NEEDED`、Bridge `$ORIGIN/lib_ccec`、缺失动态库、Template `.O2.bc/.O0.bc` 与 SHA。确认 CMake install 实际完成而非仅发布目标成功。再按 `08_CONTAINER_HOST_HANDOFF.md` 在宿主识别 bind mount 或执行独立 `docker cp`，逐文件比对容器/宿主 SHA，宿主再次执行 readelf/ldd。Host UT 在容器中执行并单独报告。输出 G0 报告并停止；不可运行 G1。

### G1-CASE：某一个真实 Process 用例

> 当前 Task = `G1-CASE-<准确名称>`。只在 Docker 宿主机执行，对同一真实 bcmlir/Target/Ordered Aux 独立运行 `BASE_SHA` 编译器的 Process 与 `HEAD_SHA` 编译器的 Process。读取 `03_G1_G2_PARITY.md`。保存真实 `execve` argv、pre-driver IR SHA、Aux occurrence、AIC/AIV Lane Object、最终 Binary SHA、设备数值与误差规则。输入来源不明时不能 PASS。只交这一用例结果，并停止。

### G1-GATE：四用例 Process 对照裁决

> 仅复核四份 G1-CASE，不重新运行。核对 `A3_PureAIV`、`A3_MixCV`、`A5_PureAIV`、`A5_MixCV` 的 R/P 命令/退出码/输入、Aux、外部 Bisheng SHA、Object 和设备数值。A3/A5 任一宿主设备未真正运行时，标记该子门禁 ENV_BLOCKED，不能宣告 G1 完整 PASS。输出 `G1-report.md`，停止。

### G2-CASE：某一个 Direct 用例

> 当前 Task = `G2-CASE-<准确名称>`。仅在 Docker 宿主执行。使用 G1 已核实的同输入和同一个 HEAD 安装目录，分别运行 P/D。应检查 `requested=inprocess_session effective=inprocess_session executed=direct fallback=0 success=1`；Host 从真实 `<prefix>/lib/libbisheng_bridge.so` 加载 LLVM15 Bridge。保存双 Lane/Session/CodeGen、Aux SHA、Object、数值证据；任何 Process fallback 都不属于 Direct PASS。仅执行一个用例，停止。

### G2-ORACLE：三路与固定 IR Replay

> 四份 G2-CASE 正向 Smoke 均有真实 Direct 证据后，在宿主从冻结 HEAD 仓调用 `run_tests.py --suite integration`、`--suite parity`。四个真实 `cases.json` 需全部在宿主存在。A3 MixCV 需要真正的 pre-link `.ll` 和三路固定输入 Replay；不能拿 `--save-linked-ir` 代替。保存原始 `strace`、Input/Ordered Aux/Executable SHA 和 Replay Object/TargetMachine/options。Runner 0/1/77 逐项保存。失败时定位最早 provenance mismatch，禁止改 Golden 欺骗测试。停止。

### G2-GATE：Direct 正确性裁决

> 仅依据四份 G2-CASE、G2-ORACLE 和独立设备数值记录裁决。进程内 Direct 应真实执行，不能把 `effective=process`、Fake Bridge 或离线测试结果当作 E2E。输出 `G2-report.md` 和差异溯源表，停止。

### G3-Fx：单个故障注入

> 当前 Task = `G3-F编号`。仅在宿主的可丢弃独立 stage 操作。先 `rg` 找真实故障注入 hook、触发条件和预期结果，再执行一个故障。记录注入生效、退出码、BackendResult、Process execve 是否发生、`[ATTEMPT]`、Worker/Ticket drain、Partial Object 清理与 Session 生命周期。禁止破坏 G0/G1/G2 正式 stage。失败不能“修了继续”；保存该项报告并停止。

### G3-GATE：异常与生命周期裁决

> 仅复核已收集的 F1–F14；任何已选择 Direct 的故障若回退 Process 或重新 Backend Attempt 则为 FAIL。缺真实厂商运行时的模拟负例只说明 Host 控制流，不能证明 LLVM15 真实行为。输出 `G3-report.md`，停止。

### G4-CASE：单个场景成对性能

> 当前 Task = `G4-CASE-<准确名称>`。应在宿主，且 G2/G3 门禁已通过。同一 Current 编译器、同输入、同 Host CPU/cgroup/CANN/设备，Process 与 Direct 每种模式分别预热 3 次，至少采集 20 个有效样本；宜交替运行。每次验证终态 Marker、退出码、Object SHA，保留 Timing JSONL、Base/Final Aux、LLVM19 serialization CPU work 与 envelope、LLVM15 backend CodeGen、AIC/AIV overlap。正式计时不带 strace。交付原始数据，停止。

### G4-GATE：统计和报告

> 仅聚合四份已通过的性能任务。计算 Process/Direct p50、p90、速度比、异常数与有效样本数，说明测量边界是整个 Host Device Backend 还是其他时间段。证明同输入、同编译选项、同硬件环境，不能只引用旧历史加速比。输出 `G4-report.md` 与汇总验收报告，停止。

### REVIEW：第二会话独立复核

> 你只读，不执行修复。读取冻结 `frozen.json`、本轮完整原始日志、`manifest.json` 和指定 Gate 的报告。核对六类问题：Git 版本漂移、R/P 其实同一二进制、容器执行冒充宿主、发布安装缺 Bridge、Direct fallback 冒充 CodeGen、无输入/Aux provenance 冒充 parity。报告 `APPROVE` / `REJECT` / `INSUFFICIENT_EVIDENCE`，列出最小可复核路径。不能只复述上个 Agent 的总结。
