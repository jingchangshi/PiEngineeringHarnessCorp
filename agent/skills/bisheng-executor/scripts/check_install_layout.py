#!/usr/bin/env python3
"""Audit an installed compiler/Bridge layout without running codegen.

Checks path closure, SHA, readelf and ldd (when available). It is NOT an E2E test.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


def sha(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            d.update(chunk)
    return d.hexdigest()


def command(*args: str) -> dict:
    p = subprocess.run(args, capture_output=True, text=True)
    return {"exit": p.returncode, "stdout": p.stdout, "stderr": p.stderr[:1200]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--process-only", action="store_true")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    prefix = Path(args.prefix).expanduser().resolve()
    paths = {
        "host": prefix / "bin/bishengir-compile",
        "bridge": prefix / "lib/libbisheng_bridge.so",
        "llvm15": prefix / "lib/lib_ccec/libLLVM-15.so",
        "clang15": prefix / "lib/lib_ccec/libclang-cpp.so.15",
    }
    required = ["host"] if args.process_only else list(paths)
    report = {"collected_utc": datetime.now(timezone.utc).isoformat(), "prefix": str(prefix),
              "process_only": args.process_only, "paths": {}, "errors": [], "warnings": []}
    for key, path in paths.items():
        report["paths"][key] = {"path": str(path), "exists": path.is_file(),
                                "sha256": sha(path) if path.is_file() else None}
        if key in required and not path.is_file():
            report["errors"].append(f"missing required {key}: {path}")
    templates = sorted(p for p in (prefix / "lib").glob("*.bc") if p.is_file())
    report["templates"] = [{"file": x.name, "sha256": sha(x)} for x in templates]
    if not templates:
        report["errors"].append("installed lib directory contains no .bc templates")
    if not any(re.search(r"\.O[02]\.bc$", p.name) for p in templates):
        report["warnings"].append("no .O2.bc/.O0.bc template found; verify resolveTemplateBitcodeOptLevel")
    if not shutil.which("readelf"):
        report["errors"].append("readelf is unavailable")
    else:
        for key in ("host", "bridge"):
            if key == "bridge" and args.process_only:
                continue
            path = paths[key]
            if not path.is_file():
                continue
            res = command("readelf", "-d", str(path))
            report[key + "_readelf"] = res
            if res["exit"]:
                report["errors"].append(f"readelf failed for {key}")
                continue
            data = res["stdout"]
            if key == "host" and any(x in data for x in ("libLLVM-15.so", "libbisheng_bridge.so")):
                report["errors"].append("host has direct DT_NEEDED for LLVM15 or Bridge")
            if key == "bridge" and "$ORIGIN/lib_ccec" not in data:
                report["errors"].append("Bridge lacks $ORIGIN/lib_ccec RPATH/RUNPATH")
            if key == "bridge" and not any(x in data for x in ("libLLVM-15.so", "libclang-cpp.so")):
                report["warnings"].append("Bridge NEEDED entries did not show expected LLVM15 libs; inspect linkage")
    if not args.process_only and paths["bridge"].is_file():
        if not shutil.which("ldd"):
            report["errors"].append("ldd unavailable")
        else:
            report["bridge_ldd"] = command("ldd", str(paths["bridge"]))
            res = report["bridge_ldd"]
            if res["exit"] or "not found" in res["stdout"]:
                report["errors"].append("Bridge ldd failed or unresolved dependencies detected")
    report["status"] = "FAIL" if report["errors"] else "INCONCLUSIVE" if report["warnings"] else "PASS"
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": report["status"], "prefix": str(prefix),
                      "errors": report["errors"], "warnings": report["warnings"], "report": str(out)}, indent=2))
    return 0 if report["status"] == "PASS" else 2 if report["status"] == "INCONCLUSIVE" else 1


if __name__ == "__main__":
    sys.exit(main())
