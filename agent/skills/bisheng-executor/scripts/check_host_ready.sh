#!/usr/bin/env bash
# Read-only host preflight. Do NOT invoke it inside triton-build-jcshi.
set -u
OUT="${1:-}"
if [ -n "$OUT" ]; then
  mkdir -p "$(dirname "$OUT")"
  exec > "$OUT" 2>&1
fi
printf 'HOST_PREFLIGHT_UTC=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'HOSTNAME=%s\n' "$(hostname)"
printf 'KERNEL=%s\n' "$(uname -a)"
printf 'CONTAINER_EXPECTED=triton-build-jcshi\n'
if [ -e /.dockerenv ]; then
  echo 'WARNING: /.dockerenv present; verify this is really the Docker host.'
fi
for bin in docker bash git cmake ninja python3 clang clang++ bisheng strace readelf ldd sha256sum npu-smi conda; do
  if command -v "$bin" >/dev/null 2>&1; then
    printf 'TOOL %-16s %s\n' "$bin" "$(command -v "$bin")"
  else
    printf 'MISSING %-16s\n' "$bin"
  fi
done
if command -v docker >/dev/null 2>&1; then
  docker inspect triton-build-jcshi --format '{{range .Mounts}}{{println .Type .Source "=>" .Destination}}{{end}}' 2>&1 || true
fi
if command -v npu-smi >/dev/null 2>&1; then
  npu-smi info 2>&1 || true
fi
if command -v bisheng >/dev/null 2>&1; then
  printf 'BISHENG_BIN_SHA256='; sha256sum "$(command -v bisheng)" 2>&1 || true
fi
if command -v python3 >/dev/null 2>&1; then
  python3 -V 2>&1 || true
fi
printf 'END_HOST_PREFLIGHT\n'
