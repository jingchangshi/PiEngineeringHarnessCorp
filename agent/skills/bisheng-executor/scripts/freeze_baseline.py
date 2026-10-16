#!/usr/bin/env python3
"""Freeze a four-commit rebase stack without modifying the repository.

Never assumes that historical SHAs remain correct after an internal rebase.
This does not by itself prove patch equivalence to an earlier review.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f"git {' '.join(args)}: rc={p.returncode}, stderr={p.stderr.strip()[:700]}")
    return p.stdout.strip()


def present(repo: Path, sha: str) -> bool:
    p = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", sha + "^{commit}"],
                       capture_output=True)
    return p.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="/home/shijingchang/workspace/AscendNPU-IR-Dev")
    parser.add_argument("--master-ref", default="master")
    parser.add_argument("--expected-commits", type=int, default=4)
    parser.add_argument("--old-base")
    parser.add_argument("--old-head")
    parser.add_argument("--range-diff-out")
    parser.add_argument("--allow-untracked-prefix", action="append", default=[],
                        help="Explicit tooling-only untracked prefix, e.g. .pi/; never ignores tracked changes")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    repo = Path(args.repo).expanduser().resolve()
    output = Path(args.out).expanduser().resolve()
    info = {
        "schema_version": "2.0",
        "collected_utc": datetime.now(timezone.utc).isoformat(),
        "repository": str(repo),
        "master_ref": args.master_ref,
        "expected_commits": args.expected_commits,
        "status": "BASELINE_REVIEW_REQUIRED",
        "errors": [],
        "warnings": [],
    }
    try:
        if args.expected_commits <= 0:
            raise ValueError("expected-commits must be positive")
        if not repo.is_dir():
            raise RuntimeError(f"repository does not exist: {repo}")
        toplevel = Path(git(repo, "rev-parse", "--show-toplevel")).resolve()
        if toplevel != repo:
            raise RuntimeError(f"repo must be Git top level; resolved {toplevel}")
        info["head_sha"] = git(repo, "rev-parse", "HEAD")
        info["branch"] = git(repo, "branch", "--show-current")
        info["master_sha_at_freeze"] = git(repo, "rev-parse", "--verify", args.master_ref + "^{commit}")
        info["base_sha"] = git(repo, "rev-parse", f"HEAD~{args.expected_commits}")
        info["merge_base_sha"] = git(repo, "merge-base", "HEAD", args.master_ref)
        info["commits_between"] = int(git(repo, "rev-list", "--count", info["base_sha"] + ".." + info["head_sha"]))
        info["worktree_status_porcelain"] = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
        info["worktree_clean"] = not info["worktree_status_porcelain"]
        prefixes = [p.rstrip("/") + "/" for p in args.allow_untracked_prefix]
        if any(p in ("/", "./", "../") or p.startswith("../") or p.startswith("/") for p in prefixes):
            raise ValueError("invalid allow-untracked-prefix")
        status_lines = info["worktree_status_porcelain"].splitlines()
        ignored = []
        blocking = []
        for item in status_lines:
            code, name = item[:2], item[3:]
            if code == "??" and any(name.startswith(p) for p in prefixes):
                ignored.append(name)
            else:
                blocking.append(item)
        info["tooling_untracked_ignored"] = ignored
        info["source_worktree_clean"] = not blocking
        if ignored:
            info["warnings"].append("explicitly permitted untracked tooling files are excluded from source identity")
        info["commit_stack"] = []
        for n in range(args.expected_commits - 1, -1, -1):
            sha = git(repo, "rev-parse", f"HEAD~{n}")
            parents = git(repo, "show", "-s", "--format=%P", sha).split()
            subject = git(repo, "show", "-s", "--format=%s", sha)
            info["commit_stack"].append({"sha": sha, "subject": subject, "parents": parents})
            if len(parents) != 1:
                info["errors"].append(f"nonlinear commit (parents={len(parents)}): {sha}")
        if info["commits_between"] != args.expected_commits:
            info["errors"].append("rev-list count is not expected commit count")
        if info["merge_base_sha"] != info["base_sha"]:
            info["errors"].append("HEAD~N does not match merge-base(HEAD, master-ref)")
        if not info["source_worktree_clean"]:
            info["errors"].append("source worktree is dirty; HEAD SHA does not cover local changes")
        if info["master_sha_at_freeze"] != info["base_sha"]:
            info["warnings"].append("master tip is different from frozen base; use the frozen base, never moving master tip")
        if bool(args.old_base) != bool(args.old_head):
            info["errors"].append("old-base and old-head must be supplied together")
        if args.old_base and args.old_head:
            if present(repo, args.old_base) and present(repo, args.old_head):
                p = subprocess.run(["git", "-C", str(repo), "range-diff",
                                    args.old_base + ".." + args.old_head,
                                    info["base_sha"] + ".." + info["head_sha"]],
                                   capture_output=True, text=True)
                info["historical_range_diff"] = {"exit_code": p.returncode, "available": p.returncode == 0}
                if args.range_diff_out:
                    path = Path(args.range_diff_out).expanduser().resolve()
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(p.stdout + p.stderr)
                    info["historical_range_diff"]["path"] = str(path)
                if p.returncode:
                    info["warnings"].append("historical range-diff could not run")
                else:
                    info["warnings"].append("range-diff requires manual review of semantic changes")
            else:
                info["historical_range_diff"] = {"available": False, "reason": "historical Git objects missing"}
                info["warnings"].append("historical SHA objects are absent; patch equivalence not proven")
        if not info["errors"]:
            info["status"] = "PASS"
    except (RuntimeError, ValueError, OSError) as exc:
        info["errors"].append(str(exc))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": info["status"], "base_sha": info.get("base_sha"),
                      "head_sha": info.get("head_sha"), "errors": info["errors"],
                      "warnings": info["warnings"], "report": str(output)},
                     ensure_ascii=False, indent=2))
    return 0 if info["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
