#!/usr/bin/env python3
"""Read-only status checks for frozen source, vendor LLVM15 SDK and real cases.

Independent sections allow use in the build container or on the runtime host.
No PASS here proves that Bisheng Bridge codegen or NPU E2E works.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

CASES = {"A3_PureAIV", "A3_MixCV", "A5_PureAIV", "A5_MixCV"}
SDK_REQUIRED = (
    "include/llvm/IR/Module.h",
    "include/llvm/Config/llvm-config.h",
    "include/clang/CodeGen/BackendUtil.h",
    "lib/libLLVM-15.so",
    "lib/libclang-cpp.so",
    "lib/libclang-cpp.so.15",
)


def hashfile(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(repo: Path, *parts: str) -> dict:
    p = subprocess.run(["git", "-C", str(repo), *parts], capture_output=True, text=True)
    return {"return_code": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()[:600]}


def check_repo(repo_s: str | None, freeze_s: str | None) -> dict:
    if not repo_s:
        return {"status": "NOT_CHECKED"}
    repo = Path(repo_s).expanduser().resolve()
    if not repo.is_dir():
        return {"status": "ENV_BLOCKED", "reason": "repository directory absent", "path": str(repo)}
    head = git(repo, "rev-parse", "HEAD")
    dirty = git(repo, "status", "--porcelain")
    result = {"path": str(repo), "actual_head": head["stdout"], "dirty": bool(dirty["stdout"]),
              "git_error": head["stderr"]}
    if head["return_code"] or dirty["return_code"]:
        result["status"] = "FAIL"
    elif not freeze_s:
        result["status"] = "NOT_CHECKED"
        result["reason"] = "pass --freeze to verify HEAD identity"
    else:
        freeze = Path(freeze_s)
        try:
            item = json.loads(freeze.read_text())
            result["frozen_head"] = item.get("head_sha")
            result["frozen_base"] = item.get("base_sha")
            result["frozen_status"] = item.get("status")
            result["status"] = "PASS" if (item.get("status") == "PASS" and
                                          item.get("head_sha") == head["stdout"] and
                                          not result["dirty"]) else "FAIL"
        except (OSError, ValueError) as exc:
            result.update(status="FAIL", reason=f"cannot read freeze: {exc}")
    return result


def check_sdk(root_s: str | None) -> dict:
    if not root_s:
        return {"status": "NOT_CHECKED"}
    root = Path(root_s).expanduser().resolve()
    found = {}
    for name in SDK_REQUIRED:
        path = root / name
        found[name] = {"exists": path.is_file()}
        if path.is_file() and name.startswith("lib/"):
            found[name]["sha256"] = hashfile(path)
    version = None
    path = root / "include/llvm/Config/llvm-config.h"
    if path.is_file():
        m = re.search(r"^#\s*define\s+LLVM_VERSION_MAJOR\s+(\d+)\b",
                      path.read_text(errors="replace"), re.M)
        version = int(m.group(1)) if m else None
    missing = [k for k, v in found.items() if not v["exists"]]
    return {"path": str(root), "status": "PASS" if not missing and version == 15 else "ENV_BLOCKED",
            "llvm_major": version, "missing": missing, "files": found}


def check_frontend(path_s: str | None) -> dict:
    if not path_s:
        return {"status": "NOT_CHECKED"}
    root = Path(path_s).expanduser().resolve()
    binary = root / "bisheng"
    return {"path": str(binary), "status": "PASS" if binary.is_file() else "ENV_BLOCKED",
            "sha256": hashfile(binary) if binary.is_file() else None}


def check_binary(path_s: str | None) -> dict:
    if not path_s:
        return {"status": "NOT_CHECKED"}
    path = Path(path_s).expanduser().resolve()
    if not path.is_file():
        return {"status": "ENV_BLOCKED", "path": str(path), "reason": "binary missing"}
    return {"status": "PASS", "path": str(path), "sha256": hashfile(path)}


def check_cases(path_s: str | None) -> dict:
    if not path_s:
        return {"status": "NOT_CHECKED"}
    path = Path(path_s).expanduser().resolve()
    if not path.is_file():
        return {"status": "ENV_BLOCKED", "manifest": str(path), "reason": "cases.json missing"}
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError) as exc:
        return {"status": "FAIL", "reason": str(exc)}
    if not isinstance(data, list):
        return {"status": "FAIL", "reason": "cases.json must be list"}
    errors = []
    names = [x.get("name") for x in data if isinstance(x, dict)]
    if len(data) != 4 or len(names) != 4 or set(names) != CASES:
        errors.append(f"exact four case names required; got {names}")
    detail = []
    for case in data:
        if not isinstance(case, dict):
            errors.append("case is not an object")
            continue
        name = case.get("name")
        item = {"name": name, "target": case.get("target"), "source": case.get("source")}
        for key in ("name", "source", "target", "args", "output_flag", "output_name"):
            if key not in case:
                errors.append(f"{name}: missing field {key}")
        if not isinstance(case.get("args"), list):
            errors.append(f"{name}: args must be list")
        source_s = case.get("source")
        source = Path(source_s) if isinstance(source_s, str) and source_s else None
        item["source_sha256"] = hashfile(source) if source and source.is_file() else None
        if item["source_sha256"] is None:
            errors.append(f"{name}: source unavailable on this machine: {source_s}")
        if name == "A5_PureAIV" and not case.get("libdevice"):
            errors.append("A5_PureAIV: libdevice is required")
        if "libdevice" in case:
            lib_s = case.get("libdevice")
            lib = Path(lib_s) if isinstance(lib_s, str) and lib_s else None
            item["libdevice_sha256"] = hashfile(lib) if lib and lib.is_file() else None
            if item["libdevice_sha256"] is None:
                errors.append(f"{name}: libdevice unavailable: {lib_s}")
        detail.append(item)
    return {"status": "PASS" if not errors else "ENV_BLOCKED", "manifest": str(path),
            "cases": detail, "errors": errors}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo")
    p.add_argument("--freeze")
    p.add_argument("--vendor-sdk")
    p.add_argument("--bisheng-bin-dir")
    p.add_argument("--cases")
    p.add_argument("--head-bin")
    p.add_argument("--baseline-bin")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "git": check_repo(args.repo, args.freeze),
        "vendor_sdk": check_sdk(args.vendor_sdk),
        "bisheng_frontend": check_frontend(args.bisheng_bin_dir),
        "fixtures": check_cases(args.cases),
        "head_compiler": check_binary(args.head_bin),
        "baseline_compiler": check_binary(args.baseline_bin),
    }
    checked = [v["status"] for v in report.values() if isinstance(v, dict) and "status" in v]
    report["status"] = "FAIL" if "FAIL" in checked else ("ENV_BLOCKED" if "ENV_BLOCKED" in checked else
                         "PASS" if checked and all(s == "PASS" for s in checked) else "PARTIAL_CHECK")
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": report["status"], "report": str(out),
                      "sections": {k: v["status"] for k, v in report.items() if isinstance(v, dict) and "status" in v}},
                     indent=2, ensure_ascii=False))
    return 1 if report["status"] == "FAIL" else 77 if report["status"] == "ENV_BLOCKED" else 0


if __name__ == "__main__":
    sys.exit(main())
