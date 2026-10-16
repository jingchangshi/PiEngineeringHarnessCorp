#!/usr/bin/env python3
"""Quick offline tests for acceptance-package helper scripts; no CANN or NPU required."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def call(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([str(x) for x in args], cwd=cwd, text=True, capture_output=True)


class AcceptancePackageHelperTests(unittest.TestCase):
    def build_repo(self, path: Path) -> None:
        self.assertEqual(call("git", "init", "-q", "-b", "master", path).returncode, 0)
        self.assertEqual(call("git", "-C", path, "config", "user.email", "selftest@example.invalid").returncode, 0)
        self.assertEqual(call("git", "-C", path, "config", "user.name", "Package Selftest").returncode, 0)
        (path / "x.txt").write_text("base\n")
        self.assertEqual(call("git", "-C", path, "add", "x.txt").returncode, 0)
        self.assertEqual(call("git", "-C", path, "commit", "-q", "-m", "base").returncode, 0)
        self.assertEqual(call("git", "-C", path, "checkout", "-q", "-b", "feature").returncode, 0)
        for i in range(4):
            (path / "x.txt").write_text(f"step{i}\n")
            self.assertEqual(call("git", "-C", path, "add", "x.txt").returncode, 0)
            self.assertEqual(call("git", "-C", path, "commit", "-q", "-m", f"feature {i}").returncode, 0)

    def test_freeze_valid_four_commits(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            self.build_repo(repo)
            out = Path(td) / "frozen.json"
            result = call(sys.executable, HERE / "freeze_baseline.py", "--repo", repo, "--out", out)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            data = json.loads(out.read_text())
            self.assertEqual(data["status"], "PASS")
            self.assertEqual(data["commits_between"], 4)

    def test_freeze_rejects_dirty_repo(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            self.build_repo(repo)
            (repo / "untracked.tmp").write_text("dirty")
            out = Path(td) / "frozen.json"
            result = call(sys.executable, HERE / "freeze_baseline.py", "--repo", repo, "--out", out)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(out.read_text())["status"], "BASELINE_REVIEW_REQUIRED")

    def test_freeze_explicit_tooling_ignore_not_source_edit(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            self.build_repo(repo)
            (repo / ".pi").mkdir()
            (repo / ".pi" / "settings.json").write_text("{}")
            out = Path(td) / "frozen.json"
            r = call(sys.executable, HERE / "freeze_baseline.py", "--repo", repo,
                     "--allow-untracked-prefix", ".pi/", "--out", out)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            d = json.loads(out.read_text())
            self.assertEqual(d["status"], "PASS")
            self.assertFalse(d["worktree_clean"])
            self.assertTrue(d["source_worktree_clean"])
            (repo / "x.txt").write_text("uncommitted\n")
            out2 = Path(td) / "bad.json"
            r = call(sys.executable, HERE / "freeze_baseline.py", "--repo", repo,
                     "--allow-untracked-prefix", ".pi/", "--out", out2)
            self.assertEqual(r.returncode, 2)

    def test_marker_direct_success_and_process_fallback_failure(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "out.log"
            p.write_text("[BISHENG_BACKEND_RESULT] requested=inprocess_session effective=inprocess_session executed=direct fallback=0 success=1\n")
            r = call(sys.executable, HERE / "check_backend_marker.py", "--log", p, "--expect", "direct")
            self.assertEqual(r.returncode, 0, r.stdout)
            p.write_text("[BISHENG_BACKEND_RESULT] requested=inprocess_session effective=process executed=process fallback=1 success=1\n")
            r = call(sys.executable, HERE / "check_backend_marker.py", "--log", p, "--expect", "direct")
            self.assertEqual(r.returncode, 1)

    def test_missing_stage_never_passes(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "layout.json"
            r = call(sys.executable, HERE / "check_install_layout.py", "--prefix", Path(td) / "missing", "--out", out)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(json.loads(out.read_text())["status"], "FAIL")


if __name__ == "__main__":
    unittest.main(verbosity=2)
