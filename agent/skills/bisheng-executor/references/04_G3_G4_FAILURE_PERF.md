# 04｜G3 负向验收、生命周期与 G4 性能（宿主机）

**执行位置：Docker 宿主机，不是构建容器。** 所有真实异常注入、`bishengir-compile` 运行、NPU E2E 与性能测量都在宿主执行。先核查 `08_CONTAINER_HOST_HANDOFF.md`。下文的 `$RUN_ROOT` 表示宿主本轮验收证据目录，不是容器源码目录。


## G3 前置条件

**警告：故障注入不得修改正式验收安装包。** 复制一份可以删除、破坏的隔离部署。负例有意失败；只要满足预期 terminal failure，测试层可以判 PASS，但编译器返回码仍应为非零。

G3 前，至少四个用例的 G2 Direct 正向 Smoke 应真实通过。无法运行的负例报告 `ENV_BLOCKED`，不能用静态文本检查替代。

## 1. 故障矩阵

| 用例 | 注入位置 | 应证明 |
| --- | --- | --- |
| F1 Missing Bridge | 仅从隔离部署中移走固定 `lib/libbisheng_bridge.so`；保留两个 Runtime SO | 如果已经决策为 Direct，后续加载失败应终止；无 Process 运行、无残留产物 |
| F2 Missing LLVM15 Runtime | 隔离部署中缺少 `libLLVM-15.so` 或 `libclang-cpp.so.15` | 决策前按源码支持的规则转成 Process；不得宣称实际 Direct 成功 |
| F3 ABI Mismatch | 隔离安装 Fake Bridge（仓库 `Inputs` 自带样例优先） | ABI 校验在 Lane Init/Session 之前拒绝 |
| F4 Missing Symbol | 独立测试用 Stub 缺少一个应导出的符号 | 运行时拒绝，不触发 Process 偷偷成功 |
| F5 Init Failure | `BISHENG_TEST_FAIL_LANE_INIT=AIC`；另运行 `AIV` | 另一 Lane Worker Join/Drain；Terminal failure |
| F6 Prepare Failure | 控制用例 Final Aux 缺文件 | Prepare Ticket 失败后终止；无 Process 回退 |
| F7 CodeGen Failure | 当前源码支持时设置 `BISHENG_TEST_FAIL_COMPILE=any` | CodeGen 非零终止；清除部分 Object；不复用原 IR 走 Process |
| F8 Mix Link Failure | 在隔离 PATH 放置受控失败 Linker | 退出失败、两 Lane 完成、清除 Link 与 Lane 产物 |
| F9 Post-backend Failure | 当前源码支持时设 `BISHENG_TEST_FAIL_AFTER_BACKEND_ONCE=1` | 只有一个 Backend Attempt；外层不自动重试掩盖失败 |
| F10 Cleanup Failure | 在隔离目录构造不可删除的计划产物 | 不调用 Process；保留根因及 Cleanup 失败证据 |
| F11 Repeated Aux | `core, extra, extra`；`core, extra, core`；两个别名路径；Base/Final 重复 | 保留顺序与 occurrence，真实 LLVM15 Direct 不漏链、不重复消耗同一 Module |
| F12 A3 Core/Mix BC | Core 缺失、有 Extra；Mix Debug/Shmem 按需缺失 | A3 的旧 Process 规则不被 Extra BC 绕过；A5 不套用 A3 特例 |
| F13 A5 Unsupported / Retry | Direct 不支持的配置、Lowering Retry、Backend 失败分别构造 | 明确区分决策前选择 Process、算法级 Retry 与执行后终止 |
| F14 Session Lifecycle | 连续多次独立 CLI 编译；有条件再测长驻进程 | `create == destroy + abandon`，Namespace 与 Ticket 无未解释泄漏 |

**注意：** 表中的环境变量来自现有仓库文档，但 Agent 应先 `rg -n` 定位生产或测试代码的实际支持条件，不能在不起作用时依然报告注入成功。

## 2. 每项负例都应记录这些事实

1. 独立部署的原始 SHA、复制方法、破坏点。
2. 实际注入方式和生效证据（不能只有设置环境变量这一项）。
3. 编译器退出码、stderr 和 `[BISHENG_BACKEND_RESULT]`。
4. 是否发生了外部 `execve` 调用 Bisheng，何时发生。
5. `[ATTEMPT]` 次数、Worker 创建/退出、Ticket 提交/完成记录。
6. 计划输出集合 `allPlannedOutputs()` 与失败后残留文件列表。
7. Namespace/Session 生命周期记录；允许源码定义的 `abandon`，但不解释为长期无泄漏证明。

对于 F2，允许 `requested=inprocess_session effective=process executed=process fallback=1 success=1` 的**决策时降级**。该记录不能计入 Direct 成功样本。对于 F1/F3–F10，在已经执行 Direct 的场景不允许 Process 回退。

运行仓库自带集成测试：

```bash
cd "$TEST_REPO"
python3 bishengir/test/Acceptance/BishengDirectBackend/run_tests.py \
  --suite integration \
  --json-output "$RUN_ROOT/evidence/G3/integration.json"
```

**重要：** `session_lifecycle.py` 等脚本可以帮助验证行为，但实际厂商 LLVM15 的 Consumed Session 安全析构及长驻进程资源回收，需要真实长期运行证据。若只测一次性 CLI，结论应限定为 CLI。

## 3. G3 Gate 裁决

- 正向 Direct 不能被故障场景的 Mock 或 Fake 结果覆盖。
- 任意一项真实 terminal failure 出现 Process 回退，判 FAIL。
- 任意一次 CodeGen 后因错误进入下一 Backend Attempt 并成功，判 FAIL。
- 输出未清理且实际代码要求清理，判 FAIL。
- 某项缺少可用的厂商 hook 或无法重现，判 `ENV_BLOCKED` 或 `INCONCLUSIVE` 并列出原因。

## 4. G4：严格在正确性之后测性能

使用同一台设备、同一厂商 CANN/Bisheng SDK、同一模板 BC、同一编译参数和真实输入。每个用例分别测试 Process/Direct。

最小采样合同：

- 每个 Backend/用例先预热 **3 次**。预热不算正式样本。
- 每个 Backend/用例收集至少 **20 次有效编译**。结果无故障且每次都匹配正向 BackendResult。
- 推荐按轮次交替 Process/Direct 运行，记录顺序，减少系统负载漂移。
- 计时期间不要开启 `strace`、额外重型 profiling 和 IR Dump 等大开销观察；另做诊断运行。
- 记录每次编译的 Binary/Object SHA。确保后端输出符合已证明的 Parity 契约。
- 记录 CPU 使用率、有效 CPU 配额、内存、系统负载、CANN SDK、设备负载和编译器版本。

示例命令：

```bash
# 以 Bash 数组表示真实编译参数；每个模式使用不同输出路径。
CASE_ARGS=(--target=Ascend950PR_9579 --enable-hfusion-compile=true \
           --enable-mixed-cv=True /private/fixtures/a5-mix.bcmlir)

for repetition in $(seq 1 20); do
  for backend in process inprocess_session; do
    dir="$RUN_ROOT/evidence/G4/A5_MixCV/$repetition/$backend"
    mkdir -p "$dir"
    /usr/bin/time -f 'wall_seconds=%e' \
      env BISHENG_BACKEND="$backend" BISHENG_TIMING=1 \
      BISHENG_TIMING_DIR="$dir" \
      "$CURRENT_BUILD_BIN" "${CASE_ARGS[@]}" -o "$dir/device.o" \
      > "$dir/stdout.log" 2> "$dir/stderr.log"
    # 上一命令失败则记录失败样本；不计入有效分位数。
  done
done
```

这段示例缺少预热 3 次及退出码记录，Agent 应补齐。不应直接把示例输出当作验收证据。`/usr/bin/time` 的 `wall_seconds` 是完整编译器进程耗时，不等同于 Device Backend E2E。后者应从具有相同起止边界的产品 Timing 事件读取。

计时字段：

| 关键项 | 解释 |
| --- | --- |
| Device Backend E2E | 相同边界定义的 Device 编译完整耗时 |
| Base Aux 预热 | 早期可与 Host Lowering 交叠的 Aux 准备 |
| Final Aux Delta | 最终 Plan 中新增的 Aux 准备工作 |
| `serialize_cpu_work_ms` | AIC + AIV 实际 LLVM19 序列化工作时间之和 |
| `serialize_envelope_ms` | AIC serialize begin 到最后 serialize end 跨度，可包含等待，不等于 CPU 工作 |
| LLVM15 Aux Link / CodeGen | Vendor LLVM15 的真实 Backend 工作量 |
| Namespace / Init / Session | `dlmopen`、Init、Session 建立成本 |
| AIC/AIV overlap | 实际并发重叠区间与临界路径变化 |
| Mix Link / Relocation | 混合 Kernel 合并与最终处理时间 |

确定性示例：AIC Serialize 10 ms + 中间等待 100 ms + AIV Serialize 20 ms，`serialize_cpu_work_ms=30 ms`，Envelope 可以是 130 ms。不能把 Envelope 写成序列化成本。

### 统计口径

`p50` 使用 20 个有效样本的中位数；`p90` 可用 nearest-rank（20 样本时第 18 个有序样本），在报告标明定义。加速比计算为 `Process p50 / Direct p50`。同时给出 p90、重复次数、异常值处理和配对原始数据。不要依据历史日志或单次样本报告加速结论。

如果四场景没有完整 Parity 或设备正确性证据，可以保留测得的诊断计时，但 G4 正式状态应是 `ENV_BLOCKED`/`INCONCLUSIVE`，不能给出正式优化收益结论。
