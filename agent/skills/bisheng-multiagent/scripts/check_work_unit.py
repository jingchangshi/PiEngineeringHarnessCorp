#!/usr/bin/env python3
"""Validate short subagent receipts without treating a claimed PASS as proof."""
import argparse
import json
import re
import sys
from pathlib import Path

ROLES = {'bisheng-scout', 'bisheng-implementer', 'bisheng-verifier', 'bisheng-reviewer'}
DISPOSITIONS = {'DONE', 'BLOCKED', 'FAILED', 'STOPPED'}
SHA_RE = re.compile(r'^[0-9a-fA-F]{40}$|^[0-9a-fA-F]{64}$')


def below(parent, path):
    return path == parent or parent in path.parents


def verify(data, task_id, run_root):
    errors = []
    for key in ('task_id', 'work_unit_id', 'role', 'disposition', 'task_start_sha',
                'execution_env', 'summary', 'commands', 'evidence_paths',
                'changed_files', 'first_failure', 'unverified'):
        if key not in data:
            errors.append(f'missing {key}')
    if errors:
        return errors
    if data['task_id'] != task_id:
        errors.append('task_id differs from parent task')
    if not isinstance(data['work_unit_id'], str) or not data['work_unit_id'].startswith(task_id + '-WU'):
        errors.append('work_unit_id must start with TASK_ID-WU')
    if data['role'] not in ROLES:
        errors.append('unknown role')
    if data['disposition'] not in DISPOSITIONS:
        errors.append('unknown disposition')
    if not isinstance(data['task_start_sha'], str) or not SHA_RE.fullmatch(data['task_start_sha']):
        errors.append('task_start_sha must be a full SHA')
    if data['execution_env'] not in ('BUILD_CONTAINER', 'HOST', 'READONLY'):
        errors.append('invalid execution_env')
    if not isinstance(data['summary'], str) or not data['summary'].strip():
        errors.append('missing summary')
    for key in ('commands', 'evidence_paths', 'changed_files', 'unverified'):
        if not isinstance(data[key], list):
            errors.append(f'{key} must be an array')
    if errors:
        return errors
    if data['disposition'] != 'DONE' and (not isinstance(data['first_failure'], str) or not data['first_failure'].strip()):
        errors.append('non-DONE needs first_failure')
    if data['disposition'] == 'DONE' and data['role'] == 'bisheng-verifier' and not data['commands']:
        errors.append('verifier DONE needs real commands')
    if data['role'] == 'bisheng-reviewer' and data.get('verdict') not in ('APPROVE', 'REQUEST_CHANGES', 'BLOCKED', 'UNVERIFIED'):
        errors.append('reviewer needs explicit verdict')
    if data['role'] == 'bisheng-reviewer' and data.get('verdict') != 'APPROVE' and data['disposition'] == 'DONE':
        errors.append('reviewer non-APPROVE cannot claim DONE')
    if data['role'] != 'bisheng-implementer' and data['changed_files']:
        errors.append('non-implementer claims changed source files')
    for rel in data['changed_files']:
        if not isinstance(rel, str) or rel.startswith('/') or '..' in Path(rel).parts or not rel or rel.startswith('~'):
            errors.append(f'unsafe changed file path: {rel}')
    for idx, cmd in enumerate(data['commands']):
        if not isinstance(cmd, dict):
            errors.append(f'commands[{idx}] must be object')
            continue
        if not isinstance(cmd.get('command'), str) or not cmd['command'].strip():
            errors.append(f'commands[{idx}].command required')
        if not isinstance(cmd.get('exit_code'), int) or isinstance(cmd.get('exit_code'), bool):
            errors.append(f'commands[{idx}].exit_code integer required')
        if cmd.get('environment') not in ('BUILD_CONTAINER', 'HOST', 'READONLY'):
            errors.append(f'commands[{idx}].environment required')
        if not isinstance(cmd.get('cwd'), str) or not Path(cmd['cwd']).is_absolute():
            errors.append(f'commands[{idx}].cwd absolute required')
        code = cmd.get('exit_code')
        expected = cmd.get('expected_exit_codes')
        if not isinstance(expected, list) or not expected or any(not isinstance(x, int) or isinstance(x, bool) for x in expected):
            errors.append(f'commands[{idx}].expected_exit_codes required')
        elif data['disposition'] == 'DONE' and code not in expected:
            errors.append(f'commands[{idx}]: exit code {code} not expected {expected}')
        log = cmd.get('log_path')
        if not isinstance(log, str) or not log:
            errors.append(f'commands[{idx}].log_path required')
        else:
            path = Path(log).expanduser().resolve()
            if not below(run_root, path) or not path.is_file():
                errors.append(f'commands[{idx}].log_path missing or outside RUN_ROOT: {log}')
    for f in data['evidence_paths']:
        if not isinstance(f, str):
            errors.append('evidence path not string')
            continue
        path = Path(f).expanduser().resolve()
        if not below(run_root, path) or not path.exists():
            errors.append(f'evidence path missing or outside RUN_ROOT: {f}')
    return errors


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipt', type=Path, required=True)
    p.add_argument('--task-id', required=True)
    p.add_argument('--run-root', type=Path, required=True)
    ns = p.parse_args(argv)
    root = ns.run_root.expanduser().resolve()
    path = ns.receipt.expanduser().resolve()
    if not below(root, path) or not path.is_file():
        p.error('--receipt must be an existing file inside RUN_ROOT')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('receipt JSON root must be object')
        errors = verify(data, ns.task_id, root)
    except (OSError, ValueError) as e:
        errors = [str(e)]
    print(json.dumps({'status': 'SCHEMA_OK_NOT_GATE_PASS' if not errors else 'BLOCKED',
                      'receipt': str(path), 'errors': errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == '__main__':
    sys.exit(main())
