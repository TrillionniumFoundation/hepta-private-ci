#!/usr/bin/env python3
"""Partition the retained Rust lane and require both current-run observations."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import stat

from verify_ci_source import ROOT, verify

SHARDS = ('runtime', 'quality')
SCHEMA = 'trnm-rust-baseline-shard-v1'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def recipes(root=ROOT):
    # The local full lane remains the only command source. Do not clone or
    # maintain a second native-test list in a hosted shard.
    from check_ci_contract import (MODEL_OBSERVATION_BLOCK, NATIVE_RELEASE_BLOCK,
                                   RUST_DOCS, RUST_CLIPPY, code_lines)
    script = (root / 'scripts/ci/ci_job.sh').read_text()
    bodies = re.findall(r'(?ms)^  rust-baseline\)\n(.*?)(?=^    ;;$)', script)
    require(len(bodies) == 1, 'one retained complete Rust lane required')
    full = bodies[0]
    prefix = ('    cargo fmt --manifest-path trillionnium/Cargo.toml --all -- --check\n'
              '    python3 scripts/ci/run_supply_chain.py\n')
    suffix = RUST_DOCS + RUST_CLIPPY
    require(full.startswith(prefix) and full.endswith(suffix), 'Rust quality command boundary')
    runtime = full[len(prefix):-len(suffix)]
    require(code_lines(runtime) == code_lines(MODEL_OBSERVATION_BLOCK + NATIVE_RELEASE_BLOCK),
            'complete retained Rust runtime commands required')
    header = 'set -euo pipefail\nexport RUST_TEST_THREADS="${RUST_TEST_THREADS:-1}"\n'
    return {'runtime': header + runtime, 'quality': header + prefix + suffix}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def identity(args, root):
    result = verify(args.kind, args.candidate,
                    args.base if args.kind == 'prospective-merge' else None,
                    args.tested if args.kind == 'prospective-merge' else None, root)
    require(result['tested_commit'] == args.tested, 'tested source mismatch')
    return result


def run_context():
    values = {name: os.environ.get(name, '') for name in ('GITHUB_RUN_ID', 'GITHUB_RUN_ATTEMPT')}
    require(all(re.fullmatch(r'[1-9][0-9]*', value) for value in values.values()), 'current run identity required')
    return values


def run_shard(args, root=ROOT):
    require(args.shard in SHARDS, 'unknown Rust shard')
    require(args.output.is_absolute() and not args.output.resolve().is_relative_to(root.resolve()),
            'receipt must be outside source')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    script = recipes(root)[args.shard].encode()
    result = dict(schema=SCHEMA, shard=args.shard, status='running', exit_code=None,
                  command_sha256=digest(script), run=run_context())
    with args.output.open('x') as stream:
        json.dump(result, stream)
    code = 1
    try:
        result['before'] = identity(args, root)
        command = args.output.with_suffix('.sh')
        with command.open('xb') as stream:
            stream.write(script)
        # No extra native-process timeout or retry. The existing 180-minute
        # hosted job owns cancellation; abrupt loss leaves running/absent proof.
        code = subprocess.run(['bash', str(command)], cwd=root, check=False).returncode
        result['exit_code'] = code
        result['after'] = identity(args, root)
        require(result['before'] == result['after'], 'source changed during Rust shard')
        result['status'] = 'passed' if code == 0 else 'failed'
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        result.update(status='failed', error=str(error))
        code = code or 1
    finally:
        # Only the file exclusively created above is completed here. A killed
        # writer or a partial JSON document can never satisfy the fan-in.
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    return code if code >= 0 else 128 - code


def read_bounded(path, limit=65536):
    # A concurrent growing file cannot turn an earlier stat into an unbounded
    # read. Hold one no-follow regular-file descriptor and read at most limit+1.
    require(0 <= limit <= 65536, 'bounded shard material size')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise ValueError('cannot open bounded shard material') from error
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_size <= limit, 'invalid shard material size/type')
        raw = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    fingerprint = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_size,
                                  value.st_mtime_ns, value.st_ctime_ns)
    require(len(raw) == before.st_size and len(raw) <= limit and fingerprint(before) == fingerprint(after),
            'shard material changed during bounded read')
    return raw


def load_bounded(path):
    def unique(items):
        value = {}
        for key, item in items:
            require(key not in value, 'duplicate shard JSON field')
            value[key] = item
        return value
    return json.loads(read_bounded(path), object_pairs_hook=unique)


def validate_fanin(folder, expected, run, dependency, scripts):
    require(dependency == 'success', 'every Rust shard job must succeed')
    prefix = 'rust-shard-' + expected['kind'] + '-' + expected['tested_commit'] + '-' + run['GITHUB_RUN_ATTEMPT'] + '-'
    require(folder.is_dir() and not folder.is_symlink(), 'missing Rust shard artifacts')
    names = []
    with os.scandir(folder) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) == 3:
                break
    require(set(names) == {prefix + shard for shard in SHARDS} and len(names) == 2,
            'exactly two distinct current-source shard artifacts required')
    for shard in SHARDS:
        directory = folder / (prefix + shard)
        require(not directory.is_symlink() and directory.is_dir(), 'invalid shard directory')
        row = load_bounded(directory / 'rust-shard.json')
        require(type(row) is dict, 'Rust shard receipt must be an object')
        command = directory / 'rust-shard.sh'
        expected_command = scripts[shard].encode()
        actual_command = read_bounded(command, len(expected_command))
        require(set(row) == {'schema', 'shard', 'status', 'exit_code', 'command_sha256', 'run', 'before', 'after'}
                and row.get('schema') == SCHEMA and row.get('shard') == shard
                and row.get('status') == 'passed' and type(row.get('exit_code')) is int
                and row['exit_code'] == 0 and row.get('run') == run
                and canonical(row.get('before')) == canonical(row.get('after')) == canonical(expected),
                'failed, incomplete or mismatched Rust shard receipt')
        require(actual_command == expected_command
                and row.get('command_sha256') == digest(actual_command),
                'Rust shard commands differ from retained complete lane')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('run', 'check'))
    parser.add_argument('--kind', choices=('head', 'prospective-merge'), required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--tested', required=True)
    parser.add_argument('--base')
    parser.add_argument('--shard', choices=SHARDS)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inputs', type=Path)
    parser.add_argument('--dependency-result')
    args = parser.parse_args()
    if args.mode == 'run':
        return run_shard(args)
    result = dict(status='failed', all_shards_required=list(SHARDS))
    try:
        require(args.inputs is not None and args.output.is_absolute()
                and not args.output.resolve().is_relative_to(ROOT.resolve()), 'fan-in paths required outside source')
        before = identity(args, ROOT)
        validate_fanin(args.inputs, before, run_context(), args.dependency_result, recipes())
        require(identity(args, ROOT) == before, 'fan-in source changed')
        result.update(status='passed', source=before)
        return 0
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as stream:
            json.dump(result, stream, indent=2)


if __name__ == '__main__':
    raise SystemExit(main())
