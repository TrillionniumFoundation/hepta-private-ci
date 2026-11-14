#!/usr/bin/env python3
"""Hepta MemoryCell exact-HEAD local verification runner.

Read-only source verification orchestration for a real locally mounted checkout.
Does not change Git branches, merge, waive checks, promote artifacts or claim CI success.
A passing Linux run never counts as Windows/macOS/remote-model/human qualification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

PROJECT = 'hepta-private-ci'
EXTERNAL = [
    'current exact-SHA GitHub blocking-ci / Architecture / V8 / security checks',
    'Windows native/Bazel permissions, recovery, durable state and Git lifecycle',
    'macOS ARM64/Intel Clippy, Bazel and native integration',
    'authentic owner-issued source, revocation, final-use and independent acceptance evidence',
    'future-time independent heldout gains vs strong baselines, negative transfer and privacy tests',
    'physical cross-node, 64–4096 Cell scaling, latency/RSS/energy and restore observations',
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def command_output(argv: list[str], cwd: Path) -> tuple[int, str]:
    cp = subprocess.run(argv, cwd=cwd, text=True, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, timeout=25, check=False)
    return cp.returncode, cp.stdout.strip()


def checked_repo(path: Path) -> dict:
    if not path.is_dir():
        raise RuntimeError(f'checkout directory absent: {path}')
    code, root = command_output(['git', 'rev-parse', '--show-toplevel'], path)
    if code:
        raise RuntimeError(f'not a Git working tree: {path}\n{root}')
    root_path = Path(root).resolve()
    if not (root_path / 'codex-rs' / 'Cargo.toml').is_file() or not (root_path / 'docs' / 'DEVELOPMENT.md').is_file():
        raise RuntimeError('not the expected Hepta source layout')
    code, head = command_output(['git', 'rev-parse', 'HEAD'], root_path)
    code2, tree = command_output(['git', 'rev-parse', 'HEAD^{tree}'], root_path)
    code3, porcelain = command_output(['git', 'status', '--porcelain'], root_path)
    code4, remote = command_output(['git', 'remote', '-v'], root_path)
    if any((code, code2, code3, code4)):
        raise RuntimeError('cannot establish immutable source identity')
    if PROJECT not in remote:
        raise RuntimeError('remote URL does not identify hepta-private-ci')
    return {'root': str(root_path), 'head': head, 'tree': tree,
            'working_tree_clean': not bool(porcelain), 'git_status': porcelain,
            'remote_names': sorted(set(line.split('\t', 1)[0] for line in remote.splitlines())),
            'recorded_at_utc': utc_now()}


def suite(name: str, cwd: Path, argv: list[str], *, required_files=(),
          tool=None, timeout=3600) -> dict:
    return {'name': name, 'cwd': str(cwd), 'argv': argv, 'required_files': [str(v) for v in required_files],
            'tool': tool or argv[0], 'timeout_seconds': timeout}


def plan(root: Path, full: bool) -> list[dict]:
    w = root / 'codex-rs'
    specs = [
        suite('canonical development contracts', root,
              [sys.executable, 'scripts/hepta-docs.py', 'verify', '--profile', 'development'],
              required_files=['scripts/hepta-docs.py']),
        suite('Rust formatter (non-mutating)', w, ['cargo', 'fmt', '--all', '--', '--check']),
        suite('complete locked Cargo resolution', w, ['cargo', 'metadata', '--locked', '--format-version', '1'], timeout=1200),
        suite('RustSec / licenses', w, ['cargo', 'deny', 'check'], tool='cargo-deny', timeout=1200),
        suite('MemoryCell / Recall / Artifact scoped native suite', root,
              ['just', 'test', '-p', 'codex-hepta-learning-artifacts', '-p', 'codex-hepta-intelligence',
               '-p', 'codex-hepta-memory-retrieval', '--lib', '--locked', '--retries', '0'],
              required_files=['codex-rs/hepta-memory-retrieval/Cargo.toml'], timeout=5400),
        suite('Agentd scoped native tests', root,
              ['just', 'test', '-p', 'codex-hepta-agentd', '--lib', '--locked', '--retries', '0'],
              required_files=['codex-rs/hepta-agentd/Cargo.toml'], timeout=5400),
        suite('MemoryCell Python control and experiment tests', root,
              [sys.executable, '-m', 'unittest', 'discover', '-s', 'scripts/memory_cell', '-p', 'test_*.py', '-v'],
              required_files=['scripts/memory_cell'], timeout=5400),
        suite('Stem learned Cell and process tests', root,
              [sys.executable, '-m', 'unittest', 'discover', '-s', 'qa/stem-bakeoff', '-p', 'test_cell_*.py', '-v'],
              required_files=['qa/stem-bakeoff/test_cell_process_inference.py'], timeout=5400),
    ]
    if full:
        specs.extend([
            suite('whole Rust Clippy', w,
                  ['cargo', 'clippy', '--workspace', '--all-targets', '--locked', '--', '-D', 'warnings'],
                  timeout=7200),
            suite('whole Rust workspace tests', root, ['just', 'test', '--locked', '--retries', '0'],
                  timeout=14400),
        ])
    return specs


def evaluate(spec: dict, root: Path, log_dir: Path) -> dict:
    cwd = Path(spec['cwd'])
    missing = [p for p in spec['required_files'] if not (root / p).exists()]
    basic = {k: spec[k] for k in ('name', 'cwd', 'argv')}
    if missing:
        return {**basic, 'status': 'NOT_PRESENT_ON_THIS_BRANCH', 'missing': missing}
    if shutil.which(spec['tool']) is None:
        return {**basic, 'status': 'TOOL_MISSING', 'tool': spec['tool']}
    started = time.monotonic()
    safe = ''.join(ch if ch.isascii() and ch.isalnum() else '-' for ch in spec['name'])[:72]
    log = log_dir / (safe + '.log')
    status, returncode = 'NOT_RUN', None
    with log.open('wb') as stream:
        stream.write(f"UTC {utc_now()}\nCWD {cwd}\nCOMMAND {spec['argv']}\n\n".encode())
        stream.flush()
        try:
            cp = subprocess.run(spec['argv'], cwd=cwd, stdin=subprocess.DEVNULL,
                                stdout=stream, stderr=subprocess.STDOUT,
                                timeout=spec['timeout_seconds'], check=False)
            returncode = cp.returncode
            status = 'PASS' if cp.returncode == 0 else 'FAIL'
        except subprocess.TimeoutExpired:
            status = 'TIMEOUT'
        except OSError as exc:
            stream.write(f"\nEXEC_ERROR {type(exc).__name__}: {exc}\n".encode())
            status = 'EXEC_ERROR'
    return {**basic, 'status': status, 'returncode': returncode,
            'elapsed_seconds': round(time.monotonic() - started, 3),
            'log': str(log), 'log_sha256': hashlib.sha256(log.read_bytes()).hexdigest()}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', type=Path, default=Path.cwd(), help='mounted checkout path')
    p.add_argument('--output', type=Path, default=None, help='external log directory')
    p.add_argument('--expect-head', default=None, help='exact SHA gate (reject drift)')
    p.add_argument('--full', action='store_true', help='include expensive whole-workspace runs')
    args = p.parse_args()
    try:
        identity = checked_repo(args.repo.resolve())
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'status': 'BLOCKED_NO_CHECKOUT', 'detail': str(exc),
                          'observed_at_utc': utc_now()}, ensure_ascii=False, indent=2))
        return 2
    if args.expect_head and args.expect_head != identity['head']:
        print(json.dumps({'status': 'BASE_DRIFT', 'expected': args.expect_head,
                          'observed': identity['head']}, indent=2))
        return 3
    # Log outside the working tree. No source-file rewrites or branch changes.
    output = args.output or Path('/tmp') / ('hepta-memory-verify-' + identity['head'][:12])
    output = output.resolve()
    if output == Path(identity['root']) or Path(identity['root']) in output.parents:
        print('Refusing to put verification logs inside the source checkout', file=sys.stderr)
        return 3
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for spec in plan(Path(identity['root']), args.full):
        print(f"{utc_now()} {spec['name']}", flush=True)
        results.append(evaluate(spec, Path(identity['root']), output))
        print(f"  -> {results[-1]['status']}", flush=True)
    end_code, end_head = command_output(['git', 'rev-parse', 'HEAD'], Path(identity['root']))
    end_tree_code, end_tree = command_output(['git', 'rev-parse', 'HEAD^{tree}'], Path(identity['root']))
    drift = end_code != 0 or end_tree_code != 0 or end_head != identity['head'] or end_tree != identity['tree']
    failed = any(r['status'] in ('FAIL', 'TIMEOUT', 'EXEC_ERROR') for r in results)
    unresolved = any(r['status'] in ('TOOL_MISSING', 'NOT_PRESENT_ON_THIS_BRANCH') for r in results)
    overall = 'BASE_DRIFT' if drift else 'FAILED' if failed else 'INCOMPLETE' if unresolved else 'LOCAL_CHECKS_PASS_EXTERNAL_GATES_OPEN'
    report = {'schema': 'hepta.local-memorycell-verification.v1',
              'source': identity, 'ended_at_utc': utc_now(), 'platform': platform.platform(),
              'python_version': sys.version, 'full_requested': args.full, 'overall': overall,
              'results': results, 'external_unverified': EXTERNAL,
              'production_qualified': False, 'authority': 'DENY_ALL',
              'notes': 'Local results are not GitHub exact-head CI, independent evaluation, cross-OS validation or a promotion receipt.'}
    filepath = output / 'report.json'
    filepath.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print('report:', filepath, 'overall:', overall)
    return 4 if drift else 1 if failed or unresolved else 0


if __name__ == '__main__':
    raise SystemExit(main())
