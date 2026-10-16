# Pi LSP 与 FFF：AscendNPU-IR 内网配置

## Pi LSP

- 用户已安装 `@narumitw/pi-lsp`。该扩展主要提供 `lsp_diagnostics` / `lsp_fix`；不应承诺它提供定义/引用跳转工具。
- 在 Pi 实际运行的系统执行：`command -v clangd && clangd --version`。安装 Extension **不**会自动安装 clangd。
- 在源码根执行 `ls -l compile_commands.json`、`readlink -f compile_commands.json`、`python3 "$HOME/.pi/agent/skills/bisheng-executor/scripts/check_lsp.py" --repo .`（若项目级安装，替换为其真实目录）。
- 已有根目录 `compile_commands.json -> build/compile_commands.json`，且内部编译数据库的绝对 `directory`/`file` 在 Pi 所在进程内存在，则不必额外配置。
- 若 Pi 在宿主机，数据库记录容器内 `/home/shijingchang/...` 路径，则仅仅有软链接仍不够。优先在**有该源码路径和依赖头文件的容器内**运行 Pi；不能把 Host 的 clangd 诊断作为容器构建通过的证据。
- `@narumitw/pi-lsp` 在不同版本可能使用不同配置文件。当前版本优先读取 `.pi/pi-lsp.json`，旧版本文档曾称 `.pi/lsp.json`。不要在未确认插件版本前自动覆盖项目配置。正式诊断由 Pi 调用 `lsp_diagnostics`，不以 `lsp_fix` 代替仓库真实构建。
- 若希望显式仅启用 clangd，在核实 `pi-lsp` 的本机 README 后，把 `templates/pi-lsp.example.json` 的内容按当前版本放到指定配置路径。自定义服务映射可能整体覆盖内置配置，因此默认不安装这份配置。
- clangd 不一定正确理解 MLIR 的 generated headers、TableGen 生成文件和混合 LLVM15/LLVM19 目标。出现误报时核对目标 entry、生成目录和实际编译命令。

## pi-fff

`@ff-labs/pi-fff` 用于 fuzzy 文件查找及源码搜索，不代替 clangd 语义诊断。它在代码仓文件多、文件名记不清、反复调查调用路径时可能有收益。**建议可选安装**，先测试 `tools-only`，避免直接覆盖 Pi 内置 grep/find/多模式搜索工具。

```bash
pi install -l npm:@ff-labs/pi-fff
# 配置在 Pi 启动前（仅当前终端）
export PI_FFF_MODE=tools-only
pi
```

若版本支持 `/fff-mode`，可用 `/fff-mode tools-only`；先查看 `/fff-health`。若在源码目录外启动 Pi 或索引仅覆盖宿主机少量文件，FFF 的收益有限。不要用模糊命中替代 Git 精确文件路径、commit SHA、测试输入 SHA。
