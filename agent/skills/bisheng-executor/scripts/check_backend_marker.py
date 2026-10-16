#!/usr/bin/env python3
"""Verify real backend routing evidence in a compiler log.

Only checks marker fields. Object parity and device correctness are separate gates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

PAT = re.compile(r"\[BISHENG_BACKEND_RESULT\]\s+([^\r\n]+)")
EXPECTED = {
    "direct": {"requested": "inprocess_session", "effective": "inprocess_session",
               "executed": "direct", "fallback": "0", "success": "1"},
    "process": {"requested": "process", "effective": "process",
                "executed": "process", "fallback": "0", "success": "1"},
    "decision_downgrade": {"requested": "inprocess_session", "effective": "process",
                           "executed": "process", "fallback": "1", "success": "1"},
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--expect", choices=sorted(EXPECTED), required=True)
    args = ap.parse_args()
    if not args.log.is_file():
        print(json.dumps({"status": "FAIL", "error": "log missing", "path": str(args.log)}))
        return 1
    content = args.log.read_text(errors="replace")
    markers = []
    for match in PAT.finditer(content):
        pairs = [x.split("=", 1) for x in match.group(1).split() if "=" in x]
        markers.append(dict(pairs))
    if not markers:
        print(json.dumps({"status": "FAIL", "reason": "missing BISHENG_BACKEND_RESULT marker"}))
        return 1
    required = EXPECTED[args.expect]
    last = markers[-1]
    failures = {key: {"expected": value, "actual": last.get(key)}
                for key, value in required.items() if last.get(key) != value}
    # Even if the last marker matches, reject an earlier unexpected Process
    # dispatch in a purported all-Direct log.
    if args.expect == "direct" and any(m.get("executed") == "process" or
                                       m.get("fallback") not in (None, "0") for m in markers):
        failures["unexpected_process_or_fallback"] = True
    status = "PASS" if not failures else "FAIL"
    print(json.dumps({"status": status, "expected_mode": args.expect,
                      "markers_count": len(markers), "last_marker": last,
                      "differences": failures}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
