#!/usr/bin/env python3
"""Hepta P0 *local-worktree* audit and guarded repair of a verified Rust test drift.

No network, GitHub mutations, model downloads, production permits or CI claims.
Works only on the explicitly supplied local repository checkout. Python 3.11+.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import tomllib

SOURCE = Path('codex-rs/core/src/client_provider_policy_tests.rs')
PRODUCTION = Path('codex-rs/core/src/client.rs')
LOCK = Path('codex-rs/Cargo.lock')
DENY = Path('codex-rs/deny.toml')

OLD_CALL = '''map_response_events(
        /*upstream_request_id*/ None,
        events,
        test_telemetry(),
        InferenceTraceAttempt::disabled(),
        test_provider(),
        Some(owner),
        /*redact_provider_errors*/ false,
        /*encoded_request_observer*/ None,
    )'''
NEW_CALL = '''map_response_events(
        events,
        ResponseEventMapContext {
            upstream_request_id: None,
            session_telemetry: test_telemetry(),
            inference_trace_attempt: InferenceTraceAttempt::disabled(),
            provider: test_provider(),
            provider_attempt: Some(owner),
            redact_provider_errors: false,
            encoded_request_observer: None,
        },
    )'''
OLD_IMPORT = 'use super::map_response_events;'
NEW_IMPORTS = 'use super::ResponseEventMapContext;\nuse super::map_response_events;'
REQUIRED_CALLS = 6


class UnsafeDrift(ValueError):
    pass


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def inspect_core(repo: Path) -> dict:
    path = repo / SOURCE
    prod = repo / PRODUCTION
    if not path.is_file() or not prod.is_file():
        return {'source': str(SOURCE), 'present': False, 'fixable': False,
                'failure': 'source or production declaration unavailable'}
    src = path.read_text(encoding='utf-8')
    declared = prod.read_text(encoding='utf-8')
    old_count = src.count(OLD_CALL)
    new_count = src.count(NEW_CALL)
    expected_prod = 'fn map_response_events<S>(\n    api_stream: S,\n    context: ResponseEventMapContext,'
    valid_prod = expected_prod in declared
    return {'source': str(SOURCE), 'present': True,
            'sha256': sha256(src.encode('utf-8')),
            'old_eight_argument_calls': old_count,
            'new_two_argument_calls': new_count,
            'production_signature_verified': valid_prod,
            'fixable': old_count == REQUIRED_CALLS and new_count == 0
                       and src.count(OLD_IMPORT) == 1
                       and 'use super::ResponseEventMapContext;' not in src
                       and valid_prod,
            'all_six_calls_migrated': old_count == 0 and new_count == REQUIRED_CALLS
                                      and valid_prod}


def transform(src: str, production: str) -> str:
    if 'fn map_response_events<S>(\n    api_stream: S,\n    context: ResponseEventMapContext,' not in production:
        raise UnsafeDrift('actual production function signature differs; do not edit')
    count = src.count(OLD_CALL)
    if count != REQUIRED_CALLS:
        raise UnsafeDrift(f'expected exactly {REQUIRED_CALLS} untouched legacy calls, found {count}; abort')
    if src.count(OLD_IMPORT) != 1:
        raise UnsafeDrift('old map_response_events import not unique; abort')
    if 'use super::ResponseEventMapContext;' in src:
        raise UnsafeDrift('ResponseEventMapContext import already present; abort')
    patched = src.replace(OLD_CALL, NEW_CALL).replace(OLD_IMPORT, NEW_IMPORTS)
    if patched.count(OLD_CALL) or patched.count(NEW_CALL) != REQUIRED_CALLS:
        raise UnsafeDrift('post-transform call count failed; abort')
    return patched


def apply_core(repo: Path, *, apply: bool) -> dict:
    root = repo.resolve(strict=True)
    path = root / SOURCE
    prod_path = root / PRODUCTION
    if not path.is_file() or not prod_path.is_file():
        raise UnsafeDrift(f'expected a complete local worktree containing {SOURCE} and {PRODUCTION}')
    old = path.read_text(encoding='utf-8')
    new = transform(old, prod_path.read_text(encoding='utf-8'))
    diff = ''.join(difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f'a/{SOURCE}', tofile=f'b/{SOURCE}', n=3))
    result = {'file': str(SOURCE), 'mode': 'apply' if apply else 'dry-run',
              'old_sha256': sha256(old.encode('utf-8')),
              'new_sha256': sha256(new.encode('utf-8')),
              'updated_call_count': REQUIRED_CALLS,
              'patch': diff}
    if apply:
        # Avoid leave-behind untracked files inside the Git checkout: write a
        # temporary file with its final mode, fsync, atomic replace and cleanup.
        fd, temporary = tempfile.mkstemp(prefix='.hepta-p0-', dir=path.parent)
        try:
            os.fchmod(fd, path.stat().st_mode & 0o777)
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as writer:
                writer.write(new)
                writer.flush()
                os.fsync(writer.fileno())
            # Fail closed if a concurrent edit took place since the read.
            if path.read_text(encoding='utf-8') != old:
                raise UnsafeDrift('source changed concurrently; refusing overwrite')
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        if not inspect_core(root)['all_six_calls_migrated']:
            raise UnsafeDrift('post-commit structural check failed; inspect working tree')
    return result


def audit(repo: Path) -> dict:
    report = {'schema': 'hepta.local.p0-audit.v1',
              'local_repository': str(repo.resolve()),
              'production_qualified': False,
              'target_hardware_measured': False,
              'rust_compiler_ran': False,
              'github_actions_equivalent': False,
              'source': inspect_core(repo), 'advisories': []}
    lock = repo / LOCK
    if not lock.is_file():
        report['lockfile_error'] = f'{LOCK} missing; cannot claim security pass'
    else:
        packages = tomllib.loads(lock.read_text(encoding='utf-8')).get('package', [])
        indices = {(p['name'], p['version']) for p in packages if 'name' in p and 'version' in p}
        for name, advisory, reason in (
            ('anymap2', 'RUSTSEC-2026-0319', 'unmaintained; replace through upstream matrix-sdk migration'),
            ('unsafe-libyaml', 'RUSTSEC-2024-0449', 'unmaintained; eliminate serde_yaml dependency graph'),
        ):
            for item, version in sorted(indices):
                if item == name:
                    report['advisories'].append({'crate': name, 'locked_version': version,
                        'advisory': advisory, 'blocking': True, 'reason': reason})
        for item, version in sorted(indices):
            if item == 'matrix-sdk-crypto':
                base = [int(x) for x in re.findall(r'\d+', version.split('-')[0])[:3]]
                if base < [0, 19, 0]:
                    report['advisories'].append({'crate': item, 'locked_version': version,
                        'advisory': 'RUSTSEC-2026-0318', 'blocking': True,
                        'reason': 'real vulnerability; update compatible matrix-sdk family to >=0.19.0'})
        report['matrix_versions'] = sorted(
            [{'crate': name, 'version': version} for name, version in indices
             if name.startswith('matrix-sdk')], key=lambda x: (x['crate'], x['version']))
    if (repo / DENY).is_file():
        raw = (repo / DENY).read_text(encoding='utf-8')
        report['advisory_ignores_detected'] = [a for a in
            ('RUSTSEC-2026-0318', 'RUSTSEC-2026-0319', 'RUSTSEC-2024-0449')
            if re.search(r'^\s*[^#\n]*' + re.escape(a), raw, flags=re.M)]
    else:
        report['advisory_ignores_detected'] = []
    report['passed_all_local_structural_checks'] = (
        report['source'].get('all_six_calls_migrated', False)
        and (repo / LOCK).is_file()
        and not report['advisories'] and not report['advisory_ignores_detected'])
    # Even a passing local static check is NOT permission to upgrade production.
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True, help='actual local Hepta checkout root')
    sub = parser.add_subparsers(dest='command', required=True)
    fix = sub.add_parser('fix-core-tests', help='repair 6 confirmed old Rust tests (default dry-run)')
    fix.add_argument('--apply', action='store_true', help='write locally after exact preimage checks')
    stat = sub.add_parser('audit', help='read Cargo.lock and source; fail closed on advisories')
    stat.add_argument('--out', type=Path, help='write JSON outside checkout when possible')
    a = parser.parse_args(argv)
    if not a.repo.is_dir():
        parser.error('local --repo directory does not exist')
    try:
        if a.command == 'fix-core-tests':
            r = apply_core(a.repo, apply=a.apply)
            print(r['patch'], end='')
            print(f"\n{r['mode']}: {r['updated_call_count']} tests, expected SHA256 {r['new_sha256']}")
            return 0
        result = audit(a.repo)
        encoded = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + '\n'
        if a.out:
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text(encoded, encoding='utf-8')
        print(encoded, end='')
        return 0 if result['passed_all_local_structural_checks'] else 2
    except (UnsafeDrift, OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as exc:
        print(f'FAIL-CLOSED: {exc}', file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
