#!/usr/bin/env python3
"""Offline exporter tests; uses temporary Git repos, never internal source code."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent


def run(*cmd, cwd=None):
    return subprocess.run([str(x) for x in cmd], cwd=cwd, capture_output=True, text=True)


def must(*cmd, cwd=None):
    p = run(*cmd, cwd=cwd)
    if p.returncode:
        raise AssertionError(f'command failed {cmd}: {p.stdout}\n{p.stderr}')
    return p.stdout.strip()


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.repo = self.base / 'repo'
        self.repo.mkdir()
        must('git', 'init', '-q', '-b', 'master', self.repo)
        must('git', '-C', self.repo, 'config', 'user.name', 'Evidence Tests')
        must('git', '-C', self.repo, 'config', 'user.email', 'test@invalid.example')
        (self.repo / 'a.cpp').write_text('int a=0;\n')
        must('git', '-C', self.repo, 'add', 'a.cpp')
        must('git', '-C', self.repo, 'commit', '-q', '-m', 'baseline')
        must('git', '-C', self.repo, 'checkout', '-q', '-b', 'bisheng-feature')
        for i in range(4):
            (self.repo / 'a.cpp').write_text(f'int a={i + 1};\n')
            must('git', '-C', self.repo, 'commit', '-aq', '-m', f'feature-{i}')
        self.start = must('git', '-C', self.repo, 'rev-parse', 'HEAD')
        self.frozen = self.base / 'frozen.json'
        must(sys.executable, HERE / 'freeze_baseline.py', '--repo', self.repo, '--out', self.frozen)
        self.task = self.base / 'task.md'
        self.task.write_text('TASK_ID: SMOKE\nTASK_START_SHA: ' + self.start + '\n')
        self.evd = self.base / 'source-evidence'
        self.evd.mkdir()
        (self.evd / 'build.log').write_text('build rc=0\n')
        (self.evd / 'object.o').write_bytes(b'\0\1\2binary')
        (self.repo / 'a.cpp').write_text('int a=73;\n')

    def exporter(self, *extra, out=None):
        out = out or (self.base / 'collected')
        return run(sys.executable, HERE / 'export_evidence.py',
                   '--repo', self.repo, '--task-id', 'SMOKE', '--task-file', self.task,
                   '--task-start', self.start, '--frozen', self.frozen,
                   '--out', out, *extra)

    def test_core_export_and_manifest(self):
        (self.repo / 'new.cpp').write_text('int new_thing=1;\n')
        result = self.exporter('--allow-root', self.evd, '--evidence', self.evd,
                               '--untracked', 'new.cpp', '--archive')
        self.assertEqual(result.returncode, 0, result.stderr)
        info = json.loads((self.base / 'collected' / 'manifest.json').read_text())
        self.assertEqual(info['task_start_sha'], self.start)
        self.assertEqual(info['final_head_sha'], self.start)
        self.assertIn('new.cpp', info['untracked_included'])
        tracked_patch = (self.base / 'collected' / 'patches' / 'from-task-start.patch').read_text()
        self.assertIn('+int a=73;', tracked_patch)
        new_patch = (self.base / 'collected' / 'patches' / 'untracked-selected.patch').read_text()
        self.assertIn('+int new_thing=1;', new_patch)
        self.assertTrue((self.base / 'collected' / 'evidence' / 'root-01' / 'build.log').is_file())
        self.assertFalse((self.base / 'collected' / 'evidence' / 'root-01' / 'object.o').exists())
        self.assertEqual(next(x for x in info['evidence'] if x['source'].endswith('object.o'))['sha256'], hashlib.sha256(b'\0\1\2binary').hexdigest())
        self.assertTrue((self.base / 'collected.zip').is_file())
        self.assertEqual(info['gate_verdict'], 'NOT_EVALUATED_BY_EXPORTER')
        check = run(sys.executable, HERE / 'verify_review_bundle.py',
                    '--bundle', self.base / 'collected')
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        (self.base / 'collected' / 'task.md').write_text('tampered')
        check = run(sys.executable, HERE / 'verify_review_bundle.py',
                    '--bundle', self.base / 'collected')
        self.assertEqual(check.returncode, 1, check.stdout + check.stderr)
        # Export does not mutate Git index or working tree.
        st = must('git', '-C', self.repo, 'status', '--porcelain')
        self.assertIn('M a.cpp', st)
        self.assertIn('?? new.cpp', st)

    def test_refuse_outside_evidence_without_allow_root(self):
        r = self.exporter('--evidence', self.evd)
        self.assertEqual(r.returncode, 2)
        self.assertIn('outside repo', r.stderr)

    def test_refuse_output_inside_source(self):
        r = self.exporter(out=self.repo / 'review-bundle')
        self.assertEqual(r.returncode, 2)
        self.assertIn('outside source', r.stderr)

    def test_task_sha_drift_is_blocked(self):
        r = run(sys.executable, HERE / 'export_evidence.py',
                '--repo', self.repo, '--task-id', 'SMOKE', '--task-file', self.task,
                '--task-start', must('git', '-C', self.repo, 'rev-parse', 'master'),
                '--frozen', self.frozen, '--out', self.base / 'wrong')
        self.assertEqual(r.returncode, 2)
        self.assertIn('does not match --task-start', r.stderr)

    def test_untracked_omitted_is_visible(self):
        (self.repo / 'brand-new.cpp').write_text('int z=1;\n')
        r = self.exporter()
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads((self.base / 'collected' / 'manifest.json').read_text())
        self.assertIn('brand-new.cpp', d['untracked_omitted'])
        self.assertEqual(d['collection_status'], 'COLLECTED_WITH_WARNINGS')

    def test_committed_round_changes_in_patch(self):
        must('git', '-C', self.repo, 'add', 'a.cpp')
        must('git', '-C', self.repo, 'commit', '-q', '-m', 'round change')
        new_head = must('git', '-C', self.repo, 'rev-parse', 'HEAD')
        r = self.exporter()
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads((self.base / 'collected' / 'manifest.json').read_text())
        self.assertEqual(data['final_head_sha'], new_head)
        self.assertIn('+int a=73;', (self.base / 'collected' / 'patches' / 'from-task-start.patch').read_text())

    def test_copy_human_report(self):
        report = self.base / 'report.md'
        report.write_text('Actual test exit code: 77\nSTATUS: ENV_BLOCKED\n')
        r = self.exporter('--report-file', report)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = (self.base / 'collected' / 'REPORT_FOR_REVIEW.md').read_text()
        self.assertIn('STATUS: ENV_BLOCKED', data)

    def test_refuse_existing_output(self):
        target = self.base / 'exists'
        target.mkdir()
        r = self.exporter(out=target)
        self.assertEqual(r.returncode, 2)
        self.assertIn('exists', r.stderr)

    def test_symlink_evidence_is_rejected(self):
        link = self.base / 'evidence-link'
        link.symlink_to(self.evd, target_is_directory=True)
        r = self.exporter('--allow-root', self.base, '--evidence', link)
        self.assertEqual(r.returncode, 2)
        self.assertIn('symlink', r.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
