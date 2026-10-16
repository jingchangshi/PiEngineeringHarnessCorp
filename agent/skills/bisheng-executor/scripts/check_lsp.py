#!/usr/bin/env python3
"""Read-only clangd/compile_commands preflight; no clangd process is started."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', default='/home/shijingchang/workspace/AscendNPU-IR-Dev')
    p.add_argument('--sample', type=int, default=20)
    p.add_argument('--out', type=Path)
    args = p.parse_args()
    r = Path(args.repo).expanduser().resolve()
    db = r / 'compile_commands.json'
    report = {'repo': str(r), 'db_symlink': db.is_symlink(),
              'db_path': str(db), 'clangd_path': shutil.which('clangd'),
              'status': 'ENV_BLOCKED', 'warnings': [], 'errors': []}
    if report['clangd_path']:
        try:
            cp = subprocess.run(['clangd', '--version'], capture_output=True, text=True, timeout=10)
            report['clangd_version'] = cp.stdout.splitlines()[0] if cp.stdout else cp.stderr[:200]
        except (OSError, subprocess.TimeoutExpired) as exc:
            report['warnings'].append(f'clangd version unavailable: {exc}')
    else:
        report['errors'].append('clangd not on PATH in Pi execution environment')
    if not db.exists():
        report['errors'].append('compile_commands.json missing or dangling symlink')
    else:
        real = db.resolve()
        report['db_target'] = str(real)
        try:
            entries = json.loads(db.read_text(encoding='utf-8'))
            if not isinstance(entries, list) or not entries:
                report['errors'].append('compile_commands.json is not a nonempty JSON array')
            else:
                report['entry_count'] = len(entries)
                existence = []
                for entry in entries[:max(0, args.sample)]:
                    if not isinstance(entry, dict):
                        report['errors'].append('invalid compilation entry')
                        break
                    file = Path(entry.get('file', ''))
                    directory = Path(entry.get('directory', ''))
                    if not file.is_absolute():
                        file = directory / file
                    existence.append({'file': str(file), 'exists': file.is_file(),
                                      'directory': str(directory), 'directory_exists': directory.is_dir()})
                report['samples'] = existence
                missing = sum(not x['exists'] or not x['directory_exists'] for x in existence)
                report['sample_missing'] = missing
                if missing:
                    report['errors'].append(f'{missing}/{len(existence)} sample paths cannot be accessed from Pi runtime')
                if not report['errors']:
                    report['status'] = 'PASS'
        except (OSError, ValueError) as exc:
            report['errors'].append(f'cannot parse database: {exc}')
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'PASS' else 77


if __name__ == '__main__':
    sys.exit(main())
