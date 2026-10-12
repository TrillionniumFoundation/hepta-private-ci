#!/usr/bin/env python3
"""Fail-closed, read-only detector for ONE disposable Matrix SDK Cargo lock conflict.

This script never runs Cargo or modifies Cargo source/lock files; its only
write is the requested diagnostic JSON. The fixed Cargo update version is
admitted only for an independently verified disposable worktree. A successful resolver is NOT a crypto/security acceptance.
"""

import argparse
import json
from hashlib import sha256
from pathlib import Path
import tomllib

# Literal upstream and downstream constraints observed in a real pinned probe.
SOURCE_SHA = 'b3c07ea6ba6e8e46e30811c0500b04505c4be9f9'
MINIMUM_ASYNC_TRAIT = '0.1.92'
OBSOLETE_ASYNC_TRAIT = '0.1.89'
CANDIDATE_SDK_VERSION = '0.19.1'
RESULT_SCHEMA = 'hepta.matrix-disposable-async-trait-repin.v1'


def inspect_lock_conflict(stderr: str, manifest_bytes: bytes, lock_bytes: bytes) -> dict:
    """Refuse all other Cargo failures and changed package or feature graphs."""
    reasons = []
    if not isinstance(stderr, str) or len(stderr) > 500_000:
        reasons.append('invalid_or_oversized_cargo_stderr')
        stderr = ''
    requirements = (
        ('exact_dependency', 'error: failed to select a version for `async-trait`.'),
        ('upstream_candidate', f'matrix-sdk v{CANDIDATE_SDK_VERSION}'),
        ('old_selected_version', f'previously selected package `async-trait v{OBSOLETE_ASYNC_TRAIT}`'),
        ('required_range', f'requirements `^{MINIMUM_ASYNC_TRAIT}`'),
        ('previous_tonic_lock', f'(locked to {OBSOLETE_ASYNC_TRAIT}) of package `tonic v0.14.3`'),
    )
    for reason, exact in requirements:
        if exact not in stderr:
            reasons.append(f'missing_{reason}')
    try:
        manifest = tomllib.loads(manifest_bytes.decode('utf-8'))
        sdk = manifest['workspace']['dependencies']['matrix-sdk']
        if not isinstance(sdk, dict) or sdk != {
            'git': 'https://github.com/matrix-org/matrix-rust-sdk',
            'rev': SOURCE_SHA,
            'version': CANDIDATE_SDK_VERSION,
            'default-features': False,
            'features': ['e2e-encryption', 'sqlite'],
        }:
            reasons.append('unregistered_or_weakened_matrix_candidate')
    except (UnicodeDecodeError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError):
        reasons.append('invalid_disposable_matrix_manifest')
    try:
        lock = tomllib.loads(lock_bytes.decode('utf-8'))
        previous = [p['version'] for p in lock.get('package', [])
                    if isinstance(p, dict) and p.get('name') == 'async-trait']
        if previous != [OBSOLETE_ASYNC_TRAIT]:
            reasons.append('not_the_exact_obsolete_async_trait_lock')
    except (UnicodeDecodeError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError):
        reasons.append('invalid_disposable_cargo_lock')
    return {
        'schema': RESULT_SCHEMA,
        'exact_obsolete_lock_conflict': not reasons,
        'rejection_reasons': reasons,
        'fixed_package': 'async-trait',
        'old_version': OBSOLETE_ASYNC_TRAIT,
        'new_version': MINIMUM_ASYNC_TRAIT,
        'upstream_revision': SOURCE_SHA,
        'staged_manifest_sha256': sha256(manifest_bytes).hexdigest(),
        'original_cargo_lock_sha256': sha256(lock_bytes).hexdigest(),
        'modifies_original_checkout': False,
        'advisory_ignored': False,
        'security_advisories_resolved': False,
        'sqlite_wal_recovery_verified': False,
        'e2ee_qualified': False,
        'production_authorized': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stderr', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--lock', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    # Never replace an input manifest/lock/log with an apparently valid report,
    # including symlink aliases of those inputs.
    if args.output.resolve() in {
        args.manifest.resolve(), args.lock.resolve(), args.stderr.resolve()
    }:
        parser.error('diagnostic output must not overwrite any input file')
    result = inspect_lock_conflict(
        args.stderr.read_text(encoding='utf-8', errors='replace'),
        args.manifest.read_bytes(), args.lock.read_bytes(),
    )
    # Write only operator-selected evidence location, not any Cargo artifact.
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, sort_keys=True))
    return 0 if result['exact_obsolete_lock_conflict'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
