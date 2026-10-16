#!/usr/bin/env python3
"""Verify hashes of a local/unpacked Bisheng review bundle (no network)."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args()
    root = args.bundle.expanduser().resolve()
    digest_file = root / 'SHA256SUMS.txt'
    if not root.is_dir() or not digest_file.is_file():
        print('FAIL: missing review directory or SHA256SUMS.txt', file=sys.stderr)
        return 1
    failures = []
    expected = set()
    for line in digest_file.read_text(encoding='utf-8').splitlines():
        match = re.fullmatch(r'([a-f0-9]{64})  (.+)', line)
        if not match:
            failures.append('invalid checksum record')
            continue
        expected_sha, name = match.groups()
        rel = Path(name)
        if rel.is_absolute() or '..' in rel.parts or name in expected:
            failures.append('invalid or duplicate path: ' + name)
            continue
        expected.add(name)
        path = root / rel
        if path.is_symlink() or not path.is_file():
            failures.append('missing or symlink file: ' + name)
        elif sha(path) != expected_sha:
            failures.append('SHA mismatch: ' + name)
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and not p.is_symlink()}
    unexpected = sorted(actual - expected - {'SHA256SUMS.txt'})
    if unexpected:
        failures.append('unlisted files: ' + ', '.join(unexpected[:15]))
    manifest = root / 'manifest.json'
    if manifest.is_file():
        try:
            content = json.loads(manifest.read_text(encoding='utf-8'))
            if content.get('gate_verdict') != 'NOT_EVALUATED_BY_EXPORTER':
                failures.append('exporter verdict mutated from NOT_EVALUATED_BY_EXPORTER')
        except (ValueError, OSError) as ex:
            failures.append('manifest invalid: ' + str(ex))
    else:
        failures.append('manifest missing')
    print(json.dumps({'integrity': 'PASS' if not failures else 'FAIL',
                      'checked_files': len(expected), 'failures': failures},
                     ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(main())
