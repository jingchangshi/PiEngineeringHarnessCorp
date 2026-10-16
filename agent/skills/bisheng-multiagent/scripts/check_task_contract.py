#!/usr/bin/env python3
"""Read-only preflight for one authorized Bisheng task. No source mutations."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

KEY_RE = re.compile(r'^\s*(?:[-*]\s*)?(TASK_ID|TASK_START_SHA|BASE_SHA|FROZEN_JSON|EXECUTION_ENV|SOURCE_REPO|RUN_ROOT)\s*:\s*(.*?)\s*$')
SHA_RE = re.compile(r'^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$')


def read_contract(path):
    data = {}
    for raw in path.read_text(encoding='utf-8').splitlines():
        match = KEY_RE.match(raw)
        if match:
            key, val = match.groups()
            val = val.strip().strip('`').strip()
            if val and key not in data:
                data[key] = val
    return data


def git(repo, *args):
    p = subprocess.run(['git', '-C', str(repo), *args], text=True,
                       capture_output=True, timeout=15, check=False)
    if p.returncode:
        raise ValueError(f'git {" ".join(args)} failed: {p.stderr.strip()[:300]}')
    return p.stdout.strip()


def below(parent, path):
    return path == parent or parent in path.parents


def analyze(task, repo_override=None, root_override=None):
    contract = read_contract(task)
    errors = []
    warnings = []
    for k in ('TASK_ID', 'TASK_START_SHA', 'SOURCE_REPO', 'RUN_ROOT', 'EXECUTION_ENV'):
        if not contract.get(k):
            errors.append(f'missing {k}')
    tid = contract.get('TASK_ID', '')
    if tid and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', tid):
        errors.append('TASK_ID contains unsafe characters')
    task_repo_raw = contract.get('SOURCE_REPO', '')
    task_root_raw = contract.get('RUN_ROOT', '')
    if task_repo_raw and not Path(task_repo_raw).is_absolute():
        errors.append('SOURCE_REPO must be an absolute path')
    if task_root_raw and not Path(task_root_raw).is_absolute():
        errors.append('RUN_ROOT must be an absolute path')
    repo = Path(repo_override or task_repo_raw or '.').expanduser().resolve()
    run_root = Path(root_override or task_root_raw or '.').expanduser().resolve()
    if repo_override and task_repo_raw and repo != Path(task_repo_raw).expanduser().resolve():
        errors.append('--repo differs from TASK SOURCE_REPO')
    if root_override and task_root_raw and run_root != Path(task_root_raw).expanduser().resolve():
        errors.append('--run-root differs from TASK RUN_ROOT')
    if not repo.is_dir():
        errors.append(f'SOURCE_REPO not found: {repo}')
    if below(repo, run_root):
        errors.append('RUN_ROOT is inside SOURCE_REPO (would dirty Git worktree)')
    if contract.get('EXECUTION_ENV') not in ('BUILD_CONTAINER', 'HOST', 'READONLY'):
        errors.append('EXECUTION_ENV must be exactly BUILD_CONTAINER, HOST or READONLY')
    sha = contract.get('TASK_START_SHA', '')
    p0 = tid.startswith('P0-')
    if sha == 'AUTO_DISCOVER' and not p0:
        errors.append('AUTO_DISCOVER allowed only for P0-* tasks')
    elif sha != 'AUTO_DISCOVER' and not SHA_RE.fullmatch(sha):
        errors.append('TASK_START_SHA must be a full 40/64-digit SHA')
    if not p0 and not contract.get('BASE_SHA') and not contract.get('FROZEN_JSON'):
        errors.append('non-P0 task requires BASE_SHA or FROZEN_JSON')
    head = None
    dirty = None
    if repo.is_dir():
        try:
            head = git(repo, 'rev-parse', 'HEAD')
            if SHA_RE.fullmatch(sha) and head.lower() != sha.lower():
                errors.append(f'Git HEAD drift: {head} != TASK_START_SHA {sha}')
            dirty = git(repo, 'status', '--porcelain=v1', '--untracked-files=normal')
            if dirty:
                warnings.append('working tree not clean; identify pre-existing and authorized edits before execution')
        except (ValueError, OSError, subprocess.TimeoutExpired) as e:
            errors.append(str(e))
    frozen = contract.get('FROZEN_JSON')
    frozen_base = None
    if frozen:
        if not Path(frozen).is_absolute():
            errors.append('FROZEN_JSON must be an absolute path')
        else:
            f = Path(frozen).expanduser().resolve()
            if not f.is_file():
                errors.append(f'FROZEN_JSON not found: {f}')
            else:
                try:
                    data = json.loads(f.read_text(encoding='utf-8'))
                    if data.get('status') != 'PASS':
                        errors.append('FROZEN_JSON status must be PASS')
                    frozen_base = data.get('base_sha')
                    if contract.get('BASE_SHA') and frozen_base != contract['BASE_SHA']:
                        errors.append('BASE_SHA disagrees with frozen.json')
                except (OSError, ValueError) as e:
                    errors.append(f'invalid FROZEN_JSON: {e}')
    return {
        'status': 'PREFLIGHT_OK' if not errors else 'PREFLIGHT_BLOCKED',
        'task_file': str(task), 'task_id': tid,
        'source_repo': str(repo), 'run_root': str(run_root),
        'execution_env_claimed': contract.get('EXECUTION_ENV'),
        'execution_env_attested': False,
        'task_start_sha': sha, 'git_head': head,
        'base_sha': contract.get('BASE_SHA') or frozen_base,
        'dirty_worktree': bool(dirty), 'dirty_sample': (dirty or '').splitlines()[:10],
        'errors': errors, 'warnings': warnings,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--task', required=True, type=Path)
    ap.add_argument('--repo', type=Path)
    ap.add_argument('--run-root', type=Path)
    ap.add_argument('--out', type=Path, help='optional JSON report, only under RUN_ROOT')
    ns = ap.parse_args(argv)
    task = ns.task.expanduser().resolve()
    if not task.is_file():
        ap.error(f'task file not found: {task}')
    result = analyze(task, ns.repo, ns.run_root)
    if ns.out:
        path = ns.out.expanduser().resolve()
        if not below(Path(result['run_root']), path):
            ap.error('--out must be inside RUN_ROOT')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'PREFLIGHT_OK' else 2


if __name__ == '__main__':
    sys.exit(main())
