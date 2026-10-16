---
description: 只读复核一轮 Bisheng 证据（不代替外部独立审阅）
argument-hint: "<BUNDLE_DIR>"
---

先读取已安装的 `bisheng-executor/SKILL.md`（全局或项目级）的 Gate 与证据约束。

仅只读检查 `$1` 的 `manifest.json`、Git SHA、真实日志与测试结果。特别检查：任务起点是否漂移，是否混淆容器与宿主，是否将发布安装视为 Bridge 安装，是否将 Direct Process fallback 视为真实 LLVM15 执行，以及是否遗漏新建源码文件。仅输出证据检查问题，不修复源码、不重复跑 G0–G4、不宣称外部 ChatGPT 已经 APPROVE。
