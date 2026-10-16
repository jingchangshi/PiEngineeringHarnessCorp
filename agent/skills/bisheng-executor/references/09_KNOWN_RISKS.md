# 09｜GLM 5.2 必查误判与诊断顺序

## 1. Git

- 错：继续使用旧 `c6d405c5`/`29fc916b` 当本轮正式 SHA。对：P0 从容器的 `/home/shijingchang/workspace/AscendNPU-IR-Dev` 冻结本轮四提交栈。
- 错：新 `master` tip 前进后直接改成它。对：构建本轮固定 `BASE_SHA = HEAD~4`，验证与 rebase 的共同祖先一致。
- 错：HEAD 是固定 SHA 就忽略 dirty tree。对：Git SHA 不包含未提交修改；应用洁净源树构建，或提供完整源码变更快照并停止本轮原 SHA 验收。
- 错：新 SHA 代表旧四个补丁未变化。对：必要时用 `git range-diff` 或源码审查证明没有 rebase 改动。

## 2. 构建

- 错：在宿主机执行 `build.sh`。对：只在 `triton-build-jcshi` 中构建。
- 错：自动根据旧文档改为 `cmake -S third-party/llvm-project/llvm` 构建。对：优先调用已使用的 `build-tools/build.sh`，保留 `--build-triton --build-shmem-template -t` 和编译器选项。
- 错：将 `--bisheng-compiler` 指向 LLVM15 Bridge SDK 根或反过来。对：两个路径职责不同。
- 错：把 `ninja -C build ... install-bishengir-publish-products` 的成功等同于 Bridge 已部署。对：额外构建 Bridge，完整安装到隔离 stage 并检查 `lib_ccec` 两个 `.so`。
- 错：从旧 `./build/install` 偷拷贝缺失文件补齐。对：所有文件应来自本轮构建、显式安装和 SHA 记录。
- 错：因容器内 `ldd` 成功就视为宿主已安装。对：宿主再运行 ELF/依赖/加载检查。
- 错：在原 build 目录盲跑 `build.sh`。对：先核实 CMakeCache 和构建上下文；默认使用独立 build，不破坏既有内容。

## 3. Runtime

- 错：复制容器路径到 Host shell 后执行。对：用 `docker inspect` 确认挂载，或使用 `docker cp` 全量 stage。
- 错：容器 `source CANN/set_env.sh` 就认为宿主生效。对：Host 单独配置 CANN 和 CCEC。
- 错：Host 没有 `bisheng` 时，改用容器里跑 E2E。对：标记 Host `ENV_BLOCKED`，先补齐 Host 前提。
- 错：在宿主没有 A3 设备时把 A3 编译成功写成完整 E2E PASS。对：分别报告 CodeGen 和 Device E2E 状态。
- 错：`BISHENG_BRIDGE_PATH` 指到任意文件就证明生产 Bridge 能加载。对：真实路径是 `<current-prefix>/lib/libbisheng_bridge.so`。
- 错：Direct `effective=process` + exit 0 就算 Direct 成功。对：应检查 `executed=direct fallback=0 success=1`。
- 错：用 `--suite all` 汇总当前 Direct 部署。对：Portable/Integration 的环境前提不同，各自隔离运行。
- 错：用 `--save-linked-ir` 输出代替三路 Replay 的 pre-driver IR。对：保持真正输入的 SHA/argv/Aux provenance。

## 4. 诊断次序

对于任何失败，**先确认最早的失败边界**：

```text
Git SHA / dirty tree
   -> 容器 CMakeCache / Vendor headers/libs
   -> Bridge Build / install prefix
   -> Host mount/copy / ELF/RPATH
   -> Host CANN / bisheng / fixture
   -> Process Source/argv/Aux/IR
   -> Direct BackendResult/namespace/worker
   -> Object & Device numerical parity
   -> Retry/lifecycle
   -> Performance
```

某个节点缺证据，停止并输出 `ENV_BLOCKED` 或 `INCONCLUSIVE`。不得越级跑性能以证明正确性。
