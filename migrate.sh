#!/usr/bin/env bash
# ==============================================================================
# pi-agent 1.2.0 自定义配置迁移脚本
#
# 用途：在新机器安装 pi agent 1.2.0 之后，把本目录（agent/ 镜像布局）中的
#       自定义配置迁移到 ~/.pi/agent/。
#
# 迁移内容：
#   AGENTS.md  settings.json  models.json  pi-permissions.jsonc
#   agents/    prompts/       extensions/   skills/
#
# 安全措施：
#   1. 校验 ~/.pi/agent/install/current-version 是否为 1.2.0（或 --force 跳过）
#   2. 覆盖前先备份目标到 ~/.pi/agent/.backup-<时间戳>/，--no-backup 可跳过
#   3. 默认 dry-run 只打印将要执行的动作，--apply 才真正写入
#   4. ascendnpu-ir-expert 以软链形式重建（指向 SOURCE_SKILL_ROOT）
#
# 用法：
#   ./migrate.sh                # dry-run，打印动作清单
#   ./migrate.sh --apply        # 真正执行迁移（含备份）
#   ./migrate.sh --apply --no-backup
#   ./migrate.sh --apply --force   # 跳过版本校验
#   ./migrate.sh --apply --source-skill-root /path/to/ascendnpu-ir-expert
# ==============================================================================
set -euo pipefail

# ------------------------------------------------------------------------------
# 参数与默认值
# ------------------------------------------------------------------------------
APPLY=0
BACKUP=1
FORCE=0
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$SCRIPT_DIR/agent"
DEST="${HOME}/.pi/agent"
# 目标机器上 ascendnpu-ir-expert skill 源码根目录（软链目标）
SOURCE_SKILL_ROOT="${SOURCE_SKILL_ROOT:-$HOME/workspace/ascendnpu-ir-expert}"
EXPECTED_VERSION="1.2.0"

# ------------------------------------------------------------------------------
# 小工具
# ------------------------------------------------------------------------------
log()  { printf '[migrate] %s\n' "$*"; }
warn() { printf '[migrate][warn] %s\n' "$*" >&2; }
err()  { printf '[migrate][error] %s\n' "$*" >&2; }

die() { err "$*"; exit 1; }

usage() {
  sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)       APPLY=1 ;;
    --no-backup)   BACKUP=0 ;;
    --force)       FORCE=1 ;;
    --source-skill-root) SOURCE_SKILL_ROOT="$2"; shift ;;
    -h|--help)     usage ;;
    *) die "未知参数: $1（用 --help 查看用法）" ;;
  esac
  shift
done

# ------------------------------------------------------------------------------
# 前置校验
# ------------------------------------------------------------------------------
[[ -d "$SRC/agents" ]] || die "缺少迁移源码目录: $SRC/agents（本脚本应放在 agent/ 的同级目录运行）"

if [[ -f "$DEST/install/current-version" ]]; then
  INSTALLED="$(cat "$DEST/install/current-version")"
  log "检测到已安装版本: $INSTALLED (期望 $EXPECTED_VERSION)"
  if [[ "$INSTALLED" != "$EXPECTED_VERSION" ]]; then
    if [[ "$FORCE" == "1" ]]; then
      warn "版本不匹配但 --force，继续执行"
    else
      die "已安装版本 $INSTALLED 与迁移目标 $EXPECTED_VERSION 不一致；确认后加 --force 执行"
    fi
  fi
else
  warn "未找到 $DEST/install/current-version，无法校验版本"
  if [[ "$FORCE" != "1" ]]; then
    die "请先确认 pi agent 已安装（或加 --force 跳过校验）"
  fi
fi

# ------------------------------------------------------------------------------
# 目标目录存在性检查
# ------------------------------------------------------------------------------
[[ -d "$DEST" ]] || die "目标目录不存在: $DEST（请先确认 pi agent 已安装）"

# ------------------------------------------------------------------------------
# 备份（仅 --apply 且 --no-backup 未指定时执行）
# ------------------------------------------------------------------------------
BACKUP_DIR=""
if [[ "$APPLY" == "1" && "$BACKUP" == "1" ]]; then
  BACKUP_DIR="${DEST}/.backup-$(date +%Y%m%d-%H%M%S)"
  log "备份现有配置到: $BACKUP_DIR"
  mkdir -p "$BACKUP_DIR"
  for item in AGENTS.md settings.json models.json pi-permissions.jsonc agents prompts extensions skills; do
    if [[ -e "$DEST/$item" ]]; then
      cp -a "$DEST/$item" "$BACKUP_DIR/"
    fi
  done
fi

# ------------------------------------------------------------------------------
# 复制函数：目录整树复制，文件按需覆盖
# ------------------------------------------------------------------------------
copy_dir() { # $1 相对路径
  local rel="$1"
  log "  复制目录  agent/$rel -> $DEST/$rel"
  mkdir -p "$DEST/$rel"
  cp -a "$SRC/$rel/." "$DEST/$rel/"
}

copy_file() { # $1 相对路径
  local rel="$1"
  log "  复制文件  agent/$rel -> $DEST/$rel"
  cp -a "$SRC/$rel" "$DEST/$rel"
}

# ------------------------------------------------------------------------------
# 动作执行（dry-run 只打印，--apply 才执行）
# ------------------------------------------------------------------------------
log "迁移源: $SRC"
log "迁移目标: $DEST"
log "ascendnpu-ir-expert 软链目标: $SOURCE_SKILL_ROOT"
log "模式: $([[ $APPLY == 1 ]] && echo APPLY || echo DRY-RUN)"
log "动作清单："

for f in AGENTS.md settings.json models.json pi-permissions.jsonc; do
  if [[ -f "$SRC/$f" ]]; then
    [[ $APPLY == 1 ]] && copy_file "$f" || log "  将复制文件  agent/$f -> $DEST/$f"
  fi
done

for d in agents prompts extensions skills; do
  if [[ -d "$SRC/$d" ]]; then
    [[ $APPLY == 1 ]] && copy_dir "$d" || log "  将复制目录  agent/$d -> $DEST/$d"
  fi
done

# extensions/subagent 是子目录，copy_dir extensions 已覆盖；这里单独处理顶层目录内的
# 非目录文件（extensions 下的 *.ts）。extensions 目录整体复制时已包含，无需额外处理。

# ------------------------------------------------------------------------------
# ascendnpu-ir-expert 软链（源里没有此目录，只能重建）
# ------------------------------------------------------------------------------
if [[ "$APPLY" == "1" ]]; then
  if [[ -d "$SOURCE_SKILL_ROOT" ]]; then
    if [[ -e "$DEST/skills/ascendnpu-ir-expert" && ! -L "$DEST/skills/ascendnpu-ir-expert" ]]; then
      warn "$DEST/skills/ascendnpu-ir-expert 已存在且不是软链，跳过重建（如需覆盖请手动处理）"
    else
      rm -f "$DEST/skills/ascendnpu-ir-expert"
      ln -s "$SOURCE_SKILL_ROOT" "$DEST/skills/ascendnpu-ir-expert"
      log "已创建软链: skills/ascendnpu-ir-expert -> $SOURCE_SKILL_ROOT"
    fi
  else
    warn "软链目标不存在: $SOURCE_SKILL_ROOT（跳过 ascendnpu-ir-expert，可用 --source-skill-root 指定）"
  fi
fi

# ------------------------------------------------------------------------------
# 完成提示
# ------------------------------------------------------------------------------
if [[ "$APPLY" == "1" ]]; then
  if [[ -n "$BACKUP_DIR" ]]; then
    log "迁移完成。原配置备份于: $BACKUP_DIR"
  fi
  cat <<EOF

[提示] 迁移完成后的手动确认项：
  1. models.json 的 snapengine provider 中 apiKey 为占位符 "snapengine-local-proxy"，
     请按新机器实际代理配置核对 baseUrl/http 端口。
  2. extensions/credir-status.ts 中硬编码了本机路径：
        DECRYPT="/home/shijingchang/workspace/codeagent-proxy/decrypt-token.py"
        QUOTA_HOST=...prod-szv-y...
     请按新机器实际路径/环境修改。
  3. settings.json 中 packages 会在重启时由 pi 自动安装；
     pi-subagents 的 last-seen-version.json 会由运行时自动重建。
  4. 重启 pi 使 extensions / skills / subagents 生效。
EOF
else
  log "DRY-RUN 完成，未做任何修改。确认无误后执行: ./migrate.sh --apply"
fi

exit 0
