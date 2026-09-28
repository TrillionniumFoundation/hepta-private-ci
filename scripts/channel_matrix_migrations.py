#!/usr/bin/env python3
"""Generate the migration inventory; --check is strictly read-only."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'docs/modules/channel.matrix/MIGRATIONS.md'


def render(root=ROOT):
    files = sorted((root / 'codex-rs/hepta-matrix-store/migrations').glob('*.sql'))
    versions = [int(p.name[:4]) for p in files]
    if not files or versions != list(range(1, len(files)+1)):
        raise ValueError('migration gap or duplicate')
    rows = ['# Matrix migration inventory', '',
            'Generated from committed SQL filenames; not a migration execution receipt.', '',
            '| Version | SQL source |', '|---|---|']
    rows += [f'| {int(p.name[:4])} | `{p.name}` |' for p in files]
    return '\n'.join(rows)+'\n'


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true')
    args=parser.parse_args();text=render()
    if args.check:
        raise SystemExit(0 if OUTPUT.read_text()==text else 1)
    OUTPUT.write_text(text)
