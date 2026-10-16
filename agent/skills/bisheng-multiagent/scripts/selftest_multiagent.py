#!/usr/bin/env python3
"""Offline deterministic selftest; no model, network, device, or real repo access."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from check_task_contract import analyze  # noqa: E402
from check_work_unit import verify  # noqa: E402


def cmd(*args):
    p = subprocess.run(args, text=True, capture_output=True, check=False, timeout=15)
    if p.returncode:
        raise AssertionError(f'failed {args}: {p.stderr}')
    return p.stdout.strip()


def main():
    checks = 0
    with tempfile.TemporaryDirectory(prefix='bisheng-multiagent-test-') as temp:
        root = Path(temp)
        repo = root / 'repo'
        run = root / 'run'
        repo.mkdir()
        run.mkdir()
        cmd('git', '-C', str(repo), 'init', '-q')
        (repo / 'sample.cpp').write_text('int x = 1;\n')
        cmd('git', '-C', str(repo), 'add', 'sample.cpp')
        cmd('git', '-C', str(repo), '-c', 'user.name=test', '-c', 'user.email=test@example.invalid',
            'commit', '-qm', 'base')
        sha = cmd('git', '-C', str(repo), 'rev-parse', 'HEAD')
        frozen = run / 'frozen.json'
        frozen.write_text(json.dumps({'status': 'PASS', 'base_sha': sha, 'head_sha': sha}))
        task = root / 'task.md'
        def writetask(task_sha, task_root, task_id='G0B'):
            task.write_text(f'''# TASK_ID: {task_id}
- TASK_ID: {task_id}
- TASK_START_SHA: {task_sha}
- BASE_SHA: {sha}
- FROZEN_JSON: {frozen}
- SOURCE_REPO: {repo}
- RUN_ROOT: {task_root}
- EXECUTION_ENV: BUILD_CONTAINER
''')
        writetask(sha, run)
        got = analyze(task)
        assert got['status'] == 'PREFLIGHT_OK', got
        checks += 1
        writetask('f' * 40, run)
        got = analyze(task)
        assert got['status'] == 'PREFLIGHT_BLOCKED' and any('Git HEAD drift' in s for s in got['errors']), got
        checks += 1
        writetask(sha, repo / 'nested')
        got = analyze(task)
        assert got['status'] == 'PREFLIGHT_BLOCKED' and any('inside SOURCE_REPO' in s for s in got['errors']), got
        checks += 1
        writetask('AUTO_DISCOVER', run)
        got = analyze(task)
        assert got['status'] == 'PREFLIGHT_BLOCKED', got
        checks += 1
        writetask('AUTO_DISCOVER', run, 'P0-C')
        got = analyze(task)
        assert got['status'] == 'PREFLIGHT_OK', got
        checks += 1
        log = run / 'test.log'
        log.write_text('real output placeholder for an offline synthetic test\n')
        receipt = {
            'task_id': 'G0B', 'work_unit_id': 'G0B-WU01',
            'role': 'bisheng-verifier', 'disposition': 'DONE',
            'task_start_sha': sha, 'execution_env': 'BUILD_CONTAINER',
            'summary': 'Synthetic offline success (not device verification)',
            'commands': [{'command': 'echo test', 'cwd': str(repo), 'environment': 'BUILD_CONTAINER',
                          'exit_code': 0, 'expected_exit_codes': [0], 'log_path': str(log)}],
            'evidence_paths': [str(log)], 'changed_files': [],
            'first_failure': '', 'unverified': [],
        }
        errors = verify(receipt, 'G0B', run)
        assert not errors, errors
        checks += 1
        receipt['commands'][0]['exit_code'] = 1
        errors = verify(receipt, 'G0B', run)
        assert any('not expected' in e for e in errors), errors
        checks += 1
        receipt['commands'][0]['exit_code'] = 0
        receipt['commands'][0]['log_path'] = str(repo / 'missing.log')
        errors = verify(receipt, 'G0B', run)
        assert any('outside RUN_ROOT' in e for e in errors), errors
        checks += 1
        receipt['commands'][0]['log_path'] = str(log)
        receipt['role'] = 'bisheng-reviewer'
        receipt['verdict'] = 'REQUEST_CHANGES'
        errors = verify(receipt, 'G0B', run)
        assert any('non-APPROVE' in e for e in errors), errors
        checks += 1
        receipt['verdict'] = 'APPROVE'
        errors = verify(receipt, 'G0B', run)
        assert not errors, errors
        checks += 1
    print(json.dumps({'status': 'SELFTEST_PASS', 'checks': checks,
                      'meaning': 'only local parser/contract tests; not Pi SDK, LLVM15, NPU, or model execution'},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
