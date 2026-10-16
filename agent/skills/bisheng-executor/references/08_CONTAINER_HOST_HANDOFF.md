# 08｜Docker 构建与宿主机运行交接

## 1. 不得混淆的两个环境

| 事项 | 构建容器 `triton-build-jcshi` | Docker 宿主机 |
| --- | --- | --- |
| 源码锚点 | `/home/shijingchang/workspace/AscendNPU-IR-Dev` | 不假定存在相同路径 |
| 编译器/Bridge 编译 | 应在这里 | 不运行构建 |
| CANN | `/home/shijingchang/CANN/cann/set_env.sh` | 单独核对宿主机 CANN/驱动环境 |
| Conda | `triton-py311` | 如运行脚本需要 Python 依赖，核实宿主环境 |
| CCEC 前端 | `$BISHENG_FRONTEND` | 重新定位可执行 `bisheng` 与资源文件 |
| SDK `.so` | `$BRIDGE_SDK/lib` | 通过 stage `lib/lib_ccec` 提供，核查完整依赖闭包 |
| Host UT | 可在容器运行 | 不作为设备 E2E |
| G1/G2/G3/G4 实测 | **禁止作为正式验收执行环境** | **应在这里运行** |
| NPU | 不要求容器可见 | 通过 `npu-smi` 与真实 E2E 脚本验证 |

## 2. 先辨认 mount，不猜路径

宿主执行：

```bash
docker inspect triton-build-jcshi \
  --format '{{range .Mounts}}{{println .Type .Source "=>" .Destination}}{{end}}'
```

例：若报告 `bind /host/workspace => /home/shijingchang/workspace`，那么容器的 `$RUN_ROOT/stage/current` 可能直接对应宿主下的 `/host/workspace/.../stage/current`。应通过同一个小校验文件在两端算 SHA，确认可见性和内容一致。**示例不是该机器的已知真实 mount。**

如果 stage 不可共享，宿主可以通过 `docker cp` 复制，而不是运行容器二进制路径：

```bash
# 宿主机：先确认目标是新目录、可写，并有足够空间
CONTAINER=triton-build-jcshi
CONTAINER_STAGE=/home/shijingchang/workspace/bisheng-async-acceptance-20261014/stage
HOST_ROOT=/path/to/host/bisheng-async-acceptance-20261014
mkdir -p "$HOST_ROOT"
# 复制整个 stage 目录，包括 bin、lib、lib_ccec 与 Template BC。
docker cp "$CONTAINER:$CONTAINER_STAGE/." "$HOST_ROOT/"
```

**警告：** 命令中的 `/path/to/host/...` 应替换为宿主新建的独立路径。不要把 stage 覆盖到 CANN 安装目录或现有项目运行目录。`docker cp` 使用完整 stage，避免只复制主二进制漏掉 LLVM15/BC/依赖。

复制后，分别检查：

```bash
sha256sum "$HOST_ROOT/current/bin/bishengir-compile" \
  "$HOST_ROOT/current/lib/libbisheng_bridge.so" \
  "$HOST_ROOT/current/lib/lib_ccec/libLLVM-15.so" \
  "$HOST_ROOT/current/lib/lib_ccec/libclang-cpp.so.15"
sha256sum "$HOST_ROOT/reference/bin/bishengir-compile"
```

将这些 SHA 与容器源 stage 的同名文件逐一比较；不只比较压缩包 SHA。若 ELF RPATH 依赖绝对路径，重新定位后的运行可能失败，应报告真实错误，不要直接用 `LD_LIBRARY_PATH` 临时掩盖而宣布可部署。

## 3. 宿主单独建立运行环境

```bash
# 在宿主机，先诊断，不能复用容器的 source/conda 状态
bash /path/to/package/scripts/check_host_ready.sh \
  /path/to/host/evidence/host-preflight.txt

# 根据宿主实际安装位置，而非容器示例，加载 CANN
# source /path/on/host/CANN/cann/set_env.sh
# command -v bisheng
# npu-smi info
```

宿主实际外部 Bisheng 版本、`execve` 的程序绝对路径及 SHA，应登记到 `manifest.json`。同一硬件 Case 的 R/P/D 应使用可比的工具链。注意 `REFERENCE_PKG_BIN` 在宿主不一定能沿用容器中的绝对路径。

若宿主已有代码仓且挂载了被测 HEAD 源码，可直接在此运行 HEAD 版 `run_tests.py`。若宿主没有同一源码，需在内网导入已冻结 SHA 的测试仓快照和其依赖（至少 `AGENTS.md`、测试树、测试脚本需要读取的源码路径）。**只拷贝 `run_tests.py` 单文件不够，它会从含 `AGENTS.md` 的仓库根解析代码和相对路径。**

## 4. Host Env 统一变量（只在宿主设置）

```bash
HOST_ROOT=/path/to/host/bisheng-async-acceptance-20261014
export CURRENT_BUILD_BIN="$HOST_ROOT/current/bin/bishengir-compile"
export REFERENCE_PKG_BIN="$HOST_ROOT/reference/bin/bishengir-compile"
export BISHENG_BRIDGE_PATH="$HOST_ROOT/current/lib/libbisheng_bridge.so"
export BISHENG_TEST_CASES=/path/to/real/fixtures/cases.json
export BISHENG_ARTIFACT_DIR="$HOST_ROOT/evidence/runtime"
export CCEC_BIN=/path/to/host/ccec_compiler/bin
export PATH="$CCEC_BIN:$PATH"

# 只读检查，不运行设备 Kernel
python3 /path/to/package/scripts/check_install_layout.py \
  --prefix "$HOST_ROOT/current" --out "$HOST_ROOT/evidence/host-current-layout.json"
python3 /path/to/package/scripts/preflight_check.py \
  --vendor-sdk /path/to/host/vendor_sdk_if_available \
  --cases "$BISHENG_TEST_CASES" \
  --head-bin "$CURRENT_BUILD_BIN" \
  --baseline-bin "$REFERENCE_PKG_BIN" \
  --out "$HOST_ROOT/evidence/host-fixtures.json"
```

若宿主没有 LLVM15 开发头文件 SDK，`--vendor-sdk` 可不传。**宿主 Direct Runtime 主要依据已部署的 Bridge 与 `lib_ccec`**，不是要求在宿主重建 Bridge。`BISHENG_BRIDGE_PATH` 仅供测试侧能力 Probe；Production Loader 路径由 `$CURRENT_BUILD_BIN` 的安装位置确定。

## 5. Host 最小 Smoke

1. 核查 `CURRENT_BUILD_BIN`、`REFERENCE_PKG_BIN` 是两个独立文件，且 SHA 与容器 stage 相同。
2. 核查 `readelf -d` 的 ELF 依赖，运行 `ldd`；不允许有未解释的 `not found`。
3. 确认 `CCEC_BIN/bisheng` 实际可执行。验证厂商 Bisheng 资源目录、Target 和工具链版本。
4. 确认真实 `cases.json` 的四个输入均存在于**宿主机**，而非仅在容器可见。
5. 对宿主的真实 A3/A5 设备分别核查。只有当前设备可用才运行对应 E2E。容器是否可见设备不影响宿主判断。
6. 先用 G1 的 Process Smoke 验证部署与输入，再用 G2 的 Direct Smoke 验证真实 Bridge。

任何失败应保留原始 stderr、退出码、ELF 及文件 SHA。不得因想让测试通过而将 Host 的 `BISHENG_BACKEND` 改成 Process 再称 Direct 通过。
