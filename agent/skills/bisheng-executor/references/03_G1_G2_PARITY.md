# 03｜G1/G2：宿主机真实 Process 与 Direct 验收

## 1. 先满足 Host 前提

**警告：本页所有编译、Parity、设备运行命令应在 Docker 宿主机执行。** 不得在 `triton-build-jcshi` 内跑 G1/G2 后宣称已完成正式验收。

先读取 `08_CONTAINER_HOST_HANDOFF.md`，从通过 SHA 核对的 Host stage 得到：

```bash
HOST_ROOT=/path/to/host/bisheng-async-acceptance-20261014
export CURRENT_BUILD_BIN="$HOST_ROOT/current/bin/bishengir-compile"
export REFERENCE_PKG_BIN="$HOST_ROOT/reference/bin/bishengir-compile"
export BISHENG_BRIDGE_PATH="$HOST_ROOT/current/lib/libbisheng_bridge.so"
export BISHENG_TEST_CASES=/path/to/real/host/fixtures/cases.json
export BISHENG_ARTIFACT_DIR="$HOST_ROOT/evidence/runtime"
export CCEC_BIN=/path/to/host/ccec_compiler/bin
export PATH="$CCEC_BIN:$PATH"

# TEST_REPO 是宿主可访问、对应冻结 HEAD 的源码/测试快照。
TEST_REPO=/path/to/host/AscendNPU-IR-Dev-or-frozen-checkout
cd "$TEST_REPO"
```

`REFERENCE_PKG_BIN` 与 `CURRENT_BUILD_BIN` 应是不同来源的真实构建文件。宿主需要有可执行的 `bisheng`、CANN 运行库、真实案例输入和对应设备。严禁直接将构建容器内的 `/home/...` 路径当作 Host 路径。

## 2. 四个真实用例

保持仓库 `cases.example.json` 的字段和严格名称：

```json
[
  {"name":"A5_PureAIV","source":"/path/on/host/a5-pure.bcmlir","target":"Ascend950PR_9579","args":["--enable-hfusion-compile=true","--enable-triton-kernel-compile=true"],"libdevice":"/path/on/host/libdevice.10.bc","output_flag":"-o","output_name":"a5-pure.o"},
  {"name":"A5_MixCV","source":"/path/on/host/a5-mix.bcmlir","target":"Ascend950PR_9579","args":["--enable-hfusion-compile=true","--enable-mixed-cv=True"],"output_flag":"-o","output_name":"a5-mix.o"},
  {"name":"A3_PureAIV","source":"/path/on/host/a3-pure.bcmlir","target":"Ascend910_9382","args":["--enable-hivm-compile=true"],"output_flag":"-o","output_name":"a3-pure.o"},
  {"name":"A3_MixCV","source":"/path/on/host/a3-mix.bcmlir","target":"Ascend910_9382","args":["--enable-hivm-compile=true"],"output_flag":"-o","output_name":"a3-mix.o","parity_mode":"fixed_ir_replay"}
]
```

**注意：上面只演示 Schema。** `/path/on/host/` 不是可执行 fixture；Target 字符串是仓库示例，不代表宿主已连接 A3/A5 两种设备。应从原来 Process 成功的真实用例中提取全部编译选项、Aux 和数值校验脚本。`A5_PureAIV.libdevice` 是现有运行时 fixture 所需字段。

首次正式验证前：

```bash
python3 /path/to/package/scripts/preflight_check.py \
  --cases "$BISHENG_TEST_CASES" \
  --head-bin "$CURRENT_BUILD_BIN" \
  --baseline-bin "$REFERENCE_PKG_BIN" \
  --out "$HOST_ROOT/evidence/host-runtime-preflight.json"
```

这条脚本可能在缺容器 SDK 参数时只报告 runtime 子项，而非完整 P0。阅读 JSON 的 `fixtures` 和 `binaries` 状态，不要把单一总状态用于 Host Gate。

## 3. G1：Reference Process vs Current Process

对四个用例分别设置实际命令参数，运行 R 和 P。**不得在同一输出目录中重用文件。**

下面仅是已知 A5 MixCV 格式的 Bash 示例，不代表真实输入：

```bash
CASE=A5_MixCV
CASE_ARGS=(--target=Ascend950PR_9579 \
  --enable-hfusion-compile=true --enable-mixed-cv=True \
  /path/on/host/a5-mix.bcmlir)

for role in R P; do
  if [ "$role" = R ]; then BIN="$REFERENCE_PKG_BIN"; else BIN="$CURRENT_BUILD_BIN"; fi
  OUT="$HOST_ROOT/evidence/G1/$CASE/$role"
  mkdir -p "$OUT"
  printf '%q ' env BISHENG_BACKEND=process "$BIN" "${CASE_ARGS[@]}" \
    -o "$OUT/device.o" > "$OUT/command.txt"
  strace -f -s 65535 -e trace=execve -o "$OUT/execve.txt" \
    env BISHENG_BACKEND=process BISHENG_TIMING=1 \
      BISHENG_DUMP_FINAL_PLAN=1 \
      "$BIN" "${CASE_ARGS[@]}" -o "$OUT/device.o" \
    > "$OUT/stdout.log" 2> "$OUT/stderr.log"
  rc=$?
  printf '%s\n' "$rc" > "$OUT/exit_code.txt"
  [ "$rc" -eq 0 ] || { echo "G1 $role failed: $OUT"; break; }
  sha256sum "$OUT/device.o" > "$OUT/object-sha256.txt"
done
```

这条 Smoke 命令主要记录 argv。需要保存 pre-driver `.ll` 时，应另外执行支持 `--save-temps` 的诊断调用，并把实际输入 SHA、生成路径与原始运行关联；不能只靠 `strace` 就声称已经保存 LLVM IR。`strace` 不适合正式性能测量；只用于 G1/G2 来源审查与 Replay。实际执行时请在 Shell 中按条件记录退出码，不要因 `set -e` 提前退出而丢掉证据。

每个 Case 应保留：真实输入 bcmlir SHA、`-O2/-O0` 模板选择、Ordered Aux 路径和 SHA、外部 Bisheng 的 `execve` 可执行文件和 argv、AIC/AIV pre-link `.ll` 与 SHA、Lane Object 和最终二进制、真实数值校验与误差阈值。Process R/P 如不一致，应先核查 LLVM IR/argv/Aux 与工具链来源；差异未解释时不能 PASS。

## 4. G2：Current Process vs Direct

沿用同一个 Host Current 安装和同一份真实输入。每次 Direct 应产生：

```text
[BISHENG_BACKEND_RESULT] requested=inprocess_session effective=inprocess_session executed=direct fallback=0 success=1
```

字段顺序不作要求，但 `requested/effective/executed/fallback/success` 值均须符合。决策时降级到 Process 不计入 Direct 成功。单次示例：

```bash
OUT="$HOST_ROOT/evidence/G2/A5_MixCV/D"
mkdir -p "$OUT"

env BISHENG_BACKEND=inprocess_session BISHENG_TIMING=1 \
  BISHENG_DUMP_FINAL_PLAN=1 \
  "$CURRENT_BUILD_BIN" "${CASE_ARGS[@]}" -o "$OUT/device.o" \
  > "$OUT/stdout.log" 2> "$OUT/stderr.log"
rc=$?
printf '%s\n' "$rc" > "$OUT/exit_code.txt"

python3 /path/to/package/scripts/check_backend_marker.py \
  --log "$OUT/stderr.log" --expect direct
```

`check_backend_marker.py` 只验证路由，不验证 Device 正确性。还应检查真实 Bridge `dlmopen`、LLVM15 Aux/Session/CodeGen、Object SHA、AIC/AIV Worker、Mix Link、设备运行数值。

## 5. 权威 Runner（Host 上执行）

应在**宿主可访问的冻结 HEAD 源码/测试目录**调用：

```bash
cd "$TEST_REPO"
TESTS=bishengir/test/Acceptance/BishengDirectBackend
python3 "$TESTS/run_tests.py" --suite offline \
  --json-output "$HOST_ROOT/evidence/offline.json"
python3 "$TESTS/run_tests.py" --suite integration \
  --json-output "$HOST_ROOT/evidence/integration.json"
python3 "$TESTS/run_tests.py" --suite parity \
  --json-output "$HOST_ROOT/evidence/parity.json"
```

应分阶段运行：offline 可以在 P0/G0 之后运行；integration 和 parity 应在宿主满足真实 fixture、Bridge、Process、`strace`、`bisheng` 的前提下执行。每次保存退出码和完整日志，不只依赖单个 JSON 字段。

**Portable 例外：** `portable_process.py` 要求独立的缺失 Bridge/Runtime 部署场景。完整 Direct 安装目录不符合它的测试前提；不要对同一目录运行 `--suite all` 后把 Portable 失败归责 Direct。

## 6. A3 MixCV 的三路固定输入 Replay

按照 `three_way_parity.py`：

```text
真实 Process 捕获 pre-link AIC/AIV .ll + SHA
             |-- R：BASE_SHA Process / 真实外部 Bisheng
             |-- P：HEAD_SHA Process / 真实外部 Bisheng
             `-- D：HEAD_SHA Direct / 真实 LLVM15 Bridge
```

R/P/D Replay 应使用相同的原始 LLVM IR、Ordered Aux 字节、目标后端选项，并证明工具、Lane、输入、输出 SHA 的来源。**不能使用 `--save-linked-ir` 输出冒充 pre-driver `.ll`。** 缺保存接口时，应记录受控的原始 saveToFiles 边界捕获方式。

## 7. Gate 规则

- G1：R/P 四场景均成功、来源可证、产物与设备数值符合契约。
- G2：P/D 四场景 `executed=direct` 且真实 CodeGen/Parity/设备数值通过；A3 MixCV 三路 Replay 可复查。
- 宿主没有对应 A3/A5 设备时，**只将对应设备 E2E 标记 `ENV_BLOCKED`**；代码生成可以单独描述成功，但不代表完整 G1/G2 PASS。
- 任意一项首次失败或缺来源，停止本 Task，保存证据后由用户决定后续动作。
