# 02｜P0 与 G0：真实容器构建手册

## 1. 已知环境（来自用户提供的内网命令）

```bash
# 宿主机进入容器（交互方式）
docker exec -it triton-build-jcshi bash

# 以下命令只在容器内执行
source /home/shijingchang/CANN/cann/set_env.sh
conda activate triton-py311
cd /home/shijingchang/workspace/AscendNPU-IR-Dev

# 核对工具
command -v cmake || ls -l /opt/cmake/bin/cmake
command -v ninja clang clang++ python3
```

两个厂商路径承担不同职责：

```bash
BISHENG_FRONTEND=/home/shijingchang/workspace/ccec-toolkits/default/ccec_compiler/bin
BRIDGE_SDK=/home/shijingchang/workspace/ccec-toolkits/bisheng-install-llvm-dylib/ccec_compiler
```

若 Agent 的执行环境不允许交互式 TTY，可在宿主使用 `docker exec triton-build-jcshi bash -lc '...'` 运行单个只读命令；该 Shell 仍然属于容器。非交互式 Bash 可能没有 Conda 初始化，应先运行 `eval "$(conda shell.bash hook)"` 再 `conda activate triton-py311`，验证后才能构建。

`--bisheng-compiler` 使用 `$BISHENG_FRONTEND`，服务 Template BC 生成和外部编译器。`--bridge-bisheng-compiler` 使用 `$BRIDGE_SDK`，服务 Bridge LLVM15 头文件和 `.so` 链接。禁止互换。

## 2. P0-C：容器只读检查，先冻结版本

```bash
cd /home/shijingchang/workspace/AscendNPU-IR-Dev
pwd

git status --short
git rev-parse HEAD
git log -6 --oneline

git submodule status --recursive
command -v cmake ninja clang clang++ python3
ls -l "$BISHENG_FRONTEND/bisheng"
ls -l "$BRIDGE_SDK/include/llvm/IR/Module.h" \
  "$BRIDGE_SDK/include/clang/CodeGen/BackendUtil.h" \
  "$BRIDGE_SDK/lib/libLLVM-15.so" \
  "$BRIDGE_SDK/lib/libclang-cpp.so" \
  "$BRIDGE_SDK/lib/libclang-cpp.so.15"
```

先在用户确认可写且宿主可见的位置创建本轮 `RUN_ROOT`，并记录容器绝对路径。`RUN_ROOT` 不应位于原厂商 SDK 或旧安装目录下。示例：

```bash
RUN_ROOT=/home/shijingchang/workspace/bisheng-async-acceptance-20261014
mkdir -p "$RUN_ROOT"/{git,build,stage,logs,evidence,fixtures}

python3 /path/to/package/scripts/freeze_baseline.py \
  --repo /home/shijingchang/workspace/AscendNPU-IR-Dev \
  --master-ref master --expected-commits 4 \
  --out "$RUN_ROOT/git/frozen.json"

python3 /path/to/package/scripts/preflight_check.py \
  --repo /home/shijingchang/workspace/AscendNPU-IR-Dev \
  --freeze "$RUN_ROOT/git/frozen.json" \
  --vendor-sdk "$BRIDGE_SDK" \
  --bisheng-bin-dir "$BISHENG_FRONTEND" \
  --out "$RUN_ROOT/evidence/container-preflight.json"
```

`git status --short` 不为空时先调查是否有本地源码修改、旧 `build.log` 或临时文件。**未冻结的工作树内容不能算作冻结 HEAD。** 可在无损、独立的 `git worktree` 中构建干净 HEAD；不要自动清理工作树。

## 3. P0-H：宿主机只读检查

在宿主机（不是 `docker exec` 的 Shell）执行：

```bash
docker inspect triton-build-jcshi \
  --format '{{range .Mounts}}{{println .Type .Source "=>" .Destination}}{{end}}'

docker exec triton-build-jcshi test -d /home/shijingchang/workspace/AscendNPU-IR-Dev

# Docker 宿主机单独核查 CANN、设备、CCEC、挂载路径
bash /path/to/package/scripts/check_host_ready.sh \
  /path/to/host-readiness-output.txt
```

若容器源码和 `$RUN_ROOT` 是 bind mount，记录宿主的对应路径和 SHA。若不是，使用 `docker cp` 搬移独立 stage；不要将容器绝对路径硬塞到宿主机的 `CURRENT_BUILD_BIN`。详见 `08_CONTAINER_HOST_HANDOFF.md`。

## 4. G0A：构建 Reference Process（独立 Worktree）

**注意：** 下列命令可执行的前提是 P0 冻结已 PASS，且目标 `reference` worktree 不存在。Git worktree 的 `third-party` 或本地补丁可能与主树不同。先核实子模块、软链和编译依赖；不自动联网拉取/改写它们。

```bash
SRC=/home/shijingchang/workspace/AscendNPU-IR-Dev
RUN_ROOT=/home/shijingchang/workspace/bisheng-async-acceptance-20261014
BASE_SHA=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["base_sha"])' "$RUN_ROOT/git/frozen.json")

# 再次核对目标不存在
if [ -e "$RUN_ROOT/source/reference" ]; then
  echo 'STOP: reference worktree already exists'; exit 1
fi
mkdir -p "$RUN_ROOT/source"
git -C "$SRC" worktree add --detach "$RUN_ROOT/source/reference" "$BASE_SHA"

cd "$RUN_ROOT/source/reference"
git rev-parse HEAD
git submodule status --recursive
# 在确认 third-party 准备完整后，才启动下面的独立构建。
```

宜使用相同的已验证配置参数，但禁止 Reference 构建 Direct Bridge（具体旧 SHA 的脚本能否接受该开关，应先读实际代码）：

```bash
set -o pipefail
bash ./build-tools/build.sh \
  --c-compiler clang --cxx-compiler clang++ \
  '--add-cmake-options=-DLLVM_ENABLE_LLD=ON -DBISHENGIR_BUILD_BISHENG_BRIDGE=OFF' \
  --build-type Release \
  --disable-werror --disable-bishengir-werror \
  --build-triton --build-shmem-template \
  -t --bisheng-compiler /home/shijingchang/workspace/ccec-toolkits/default/ccec_compiler/bin \
  --build "$RUN_ROOT/build/reference" -j 64 \
  2>&1 | tee "$RUN_ROOT/logs/G0A-reference-build.log"
rc=${PIPESTATUS[0]}
printf '%s\n' "$rc" > "$RUN_ROOT/logs/G0A-reference-build.exit"
[ "$rc" -eq 0 ] || exit "$rc"
```

引用的 build 脚本版本是 `BASE_SHA` 版。若该版本没有相同 flag，应先产生差异与等价配置审查，不得直接删掉强制功能开关后宣称等价。构建后应在独立 `$RUN_ROOT/stage/reference` 安装完整 Host 与所需 Template，检查真正的 compiler/BC 路径；不要复用 Current 已生成的 BC 而不记录来源。

## 5. G0B：Current 编译器构建（源码锚点）

用户提供、内网已使用的命令如下。**只在容器内、源目录 HEAD 已冻结且源码干净时执行。**

```bash
RUN_ROOT=/home/shijingchang/workspace/bisheng-async-acceptance-20261014
cd /home/shijingchang/workspace/AscendNPU-IR-Dev
set -o pipefail
bash ./build-tools/build.sh \
  --c-compiler clang --cxx-compiler clang++ \
  '--add-cmake-options=-DLLVM_ENABLE_LLD=ON' \
  --build-type Release \
  --disable-werror --disable-bishengir-werror \
  --build-triton --build-shmem-template \
  -t --bisheng-compiler /home/shijingchang/workspace/ccec-toolkits/default/ccec_compiler/bin \
  --bridge-bisheng-compiler /home/shijingchang/workspace/ccec-toolkits/bisheng-install-llvm-dylib/ccec_compiler \
  --build ./build -j 64 \
  2>&1 | tee "$RUN_ROOT/logs/G0B-current-build.log"
rc=${PIPESTATUS[0]}
printf '%s\n' "$rc" > "$RUN_ROOT/logs/G0B-current-build.exit"
[ "$rc" -eq 0 ] || exit "$rc"
```

**注意：** 如果 `./build` 已经存在且 CMakeCache/HEAD 不匹配，不能盲目复用。`build.sh` 的 `main()` 会在某些重建条件下清理 CMake 文件。默认宜把 `--build ./build` 改成 `--build "$RUN_ROOT/build/current"`，同时将后面的 `ninja -C build` 改成 `ninja -C "$RUN_ROOT/build/current"`。这只改变构建输出目录，其他参数全部保留。是否复用 `./build` 应以 P0 CMakeCache 和构建时间线证明。

如果源码目录有未提交修改，先准备同一 `HEAD_SHA` 的干净 Current worktree 并在该 worktree 中执行同样命令；不要从脏目录构建后声称是冻结 SHA。

### 增量编译（适用于 `--build ./build`）

```bash
RUN_ROOT=/home/shijingchang/workspace/bisheng-async-acceptance-20261014
cd /home/shijingchang/workspace/AscendNPU-IR-Dev
set -o pipefail
ninja -C build -j64 install-bishengir-publish-products \
  2>&1 | tee "$RUN_ROOT/logs/G0B-incremental-publish.log"
rc=${PIPESTATUS[0]}
printf '%s\n' "$rc" > "$RUN_ROOT/logs/G0B-incremental-publish.exit"
[ "$rc" -eq 0 ] || exit "$rc"
```

**这条增量命令不足以证明 Bridge 已部署。** 还应显式检查目标并构建：

```bash
ninja -C build -t targets all | grep -F 'bisheng_bridge'
ninja -C build -j64 bisheng_bridge
```

如果使用了隔离构建目录，上述 `build` 一律替换为对应的 `$RUN_ROOT/build/current`，严禁使用两份 build 目录中的残留产物混淆来源。

## 6. G0C：在容器中隔离安装，并在宿主机复核

当前 `build.sh` 默认 `BISHENGIR_PUBLISH=ON`，安装目标是 `install-bishengir-publish-products`。但 `bishengir/bridge/CMakeLists.txt` 的 Bridge 和 LLVM15 两库使用普通 `install(FILES)`，**没有指定发布组件**。因此发布目录可能没有：

```text
<prefix>/lib/libbisheng_bridge.so
<prefix>/lib/lib_ccec/libLLVM-15.so
<prefix>/lib/lib_ccec/libclang-cpp.so.15
```

在**全新、明确可写的验收 stage** 中运行完整 CMake install：

```bash
RUN_ROOT=/home/shijingchang/workspace/bisheng-async-acceptance-20261014
# CURRENT_BUILD 指向本次真实使用的 ./build 或隔离 build 目录
CURRENT_BUILD=/home/shijingchang/workspace/AscendNPU-IR-Dev/build
HEAD_STAGE="$RUN_ROOT/stage/current"
cmake --build "$CURRENT_BUILD" --target bisheng_bridge
if cmake --install "$CURRENT_BUILD" --prefix "$HEAD_STAGE" \
  > "$RUN_ROOT/logs/G0C-current-full-install.log" 2>&1; then
  install_rc=0
else
  install_rc=$?
fi
printf 'full-install exit=%s\n' "$install_rc" >> "$RUN_ROOT/logs/G0C-install-exit.txt"
[ "$install_rc" -eq 0 ] || exit "$install_rc"

python3 /path/to/package/scripts/check_install_layout.py \
  --prefix "$HEAD_STAGE" --out "$RUN_ROOT/evidence/container-stage-audit.json"
```

`cmake --install` 可能安装 LLVM/MLIR 的大量产物；严禁指向系统目录、CANN 或其他同事的安装 prefix。应先读 `CMakeCache.txt`、`cmake_install.cmake`，确认 target 和 prefix 覆盖符合当前构建实际行为。**若实际编译器安装路径与预期不同，应先核实，而不是从旧 build 目录复制一个同名二进制凑齐。**

Reference 同理使用独立 `$RUN_ROOT/stage/reference`；仅要求 Process 编译器与对应 Template，不要求 Bridge。参考命令：`cmake --install "$RUN_ROOT/build/reference" --prefix "$RUN_ROOT/stage/reference"`，随后调用 `check_install_layout.py --process-only --prefix "$RUN_ROOT/stage/reference" --out "$RUN_ROOT/evidence/reference-stage-audit.json"`。若 Reference 版本的完整 CMake 安装语义不同，应在报告中列出。**安装源和安装日志是来源证据的一部分。**

在容器内检查：

```bash
readelf -d "$HEAD_STAGE/bin/bishengir-compile"
readelf -d "$HEAD_STAGE/lib/libbisheng_bridge.so"
ldd "$HEAD_STAGE/lib/libbisheng_bridge.so"
sha256sum "$HEAD_STAGE/bin/bishengir-compile" \
  "$HEAD_STAGE/lib/libbisheng_bridge.so" \
  "$HEAD_STAGE/lib/lib_ccec/libLLVM-15.so" \
  "$HEAD_STAGE/lib/lib_ccec/libclang-cpp.so.15"
```

Host 不得有直接依赖 LLVM15/Bridge 的 `DT_NEEDED`。Bridge 应可用 `$ORIGIN/lib_ccec` 解析 vendor LLVM15 依赖；还应检查所需其他依赖是否缺失、`ldd` 是否出现 `not found`。`readelf`/`ldd`/Bridge Build 不足以替代 G2 实际 `dlmopen` 与 CodeGen。

检查模板实际优化等级：`resolveTemplateBitcodeOptLevel(config)` 对应 `.O2.bc`/`.O0.bc`，并记录每个所用 BC 的真实 SHA。因为使用了 `-t --build-shmem-template`，不应再沿用上版「模板默认不构建」的假设。

## 7. Host UT 与退出码

在容器构建目录运行当前真实存在的 Host UT 目标：

```bash
ninja -C "$CURRENT_BUILD" -t targets all | grep -E 'check-mlir|check-bishengir'
# 核实有效后再运行：
ninja -C "$CURRENT_BUILD" -j64 check-mlir check-bishengir
```

保存 `PIPESTATUS`；不得让 `tee` 将真实失败覆盖为成功。只运行一份 A5 UT，不能冒称已经分别验证不同配置下的 A3/A5。

**G0 完成条件：** 双版本独立、真实编译器与 Bridge 构建、stage 安装闭包、BC 优化等级和 SHA、容器 UT 状态可核对；再将 stage 移交宿主机并执行 Host 动态链接核查。不得在容器里完成 G1/G2 的运行步骤。
