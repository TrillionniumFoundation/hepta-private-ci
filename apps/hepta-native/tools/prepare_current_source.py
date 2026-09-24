#!/usr/bin/env python3
"""Freeze committed native sources; never generate a second implementation.

The one-time #830/current-owner migration is already committed. Subsequent
changes are ordinary reviewed source commits. Only formatting, dependency
locking and identity metadata may be refreshed by the candidate workflow.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / 'apps/hepta-native'
BASE = '7ddbfac88525196e7a4b31387ceae194958275f5'
BRANCH = 'work/ui-native-current-source-20260925'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def prepare():
    if git('branch', '--show-current') != BRANCH:
        raise RuntimeError('source preparation is restricted to the named native candidate')
    subprocess.run(['git', 'merge-base', '--is-ancestor', BASE, 'HEAD'], cwd=ROOT, check=True)
    if git('status', '--porcelain'):
        raise RuntimeError('source preparation requires a clean committed candidate')
    for retired in ['src/native.js', 'src/shell-runtime.js']:
        if (APP / retired).exists():
            raise RuntimeError(f'retired product entrypoint reappeared: {retired}')
    if not (APP / 'Cargo.lock').is_file():
        raise RuntimeError('the prepared candidate must retain its reviewed native Cargo lock')
    print('committed native candidate', git('rev-parse', 'HEAD'))


def fingerprint(write):
    path = APP / 'CURRENT_SOURCE.json'
    names = sorted(p for p in APP.rglob('*') if p.is_file()
        and not any(part in {'target', '__pycache__'} for part in p.relative_to(APP).parts)
        and p.name != 'CURRENT_SOURCE.json')
    observed = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in names}
    if write:
        path.write_text(json.dumps({
            'schema': 'hepta.ui.native.current-source.v1',
            'baselineCommit': BASE,
            'historicalSourceCommit': '3198549d80d6c59887b82e2c50018ab818217c53',
            'canonicalBranch': BRANCH,
            'files': observed,
            'productionQualified': False,
            'releaseAuthorized': False,
        }, indent=2) + '\n', encoding='utf-8')
    else:
        expected = json.loads(path.read_text(encoding='utf-8'))['files']
        if observed != expected:
            changed = sorted(set(observed) ^ set(expected) | {
                key for key in set(observed) & set(expected) if observed[key] != expected[key]
            })
            raise RuntimeError('native source identity mismatch: ' + ', '.join(changed))
        print(f'verified {len(observed)} native source identities')


def sync_metadata():
    source = git('rev-parse', 'HEAD')
    tree = git('rev-parse', 'HEAD^{tree}')
    path = ROOT / 'docs/modules/ui.native/IMPLEMENTATION_MAP.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    entries = {
        'connect_runtime': ('runtime.rs', 'pub fn connect_runtime(', 'tests/runtime.rs',
            'Validates endpoint/session identity and reconciles durable pending operations; authenticated gateway composition remains a product gate.'),
        'render_runtime_view': ('runtime.rs', 'pub fn refresh_runtime_view(', 'tests/backend.rs',
            'Consumes backend runtime observations and validates session/view monotonicity; fixture observations are not physical product evidence.'),
        'request_platform_capability': ('runtime.rs', 'pub fn request_platform_capability(', 'tests/runtime.rs',
            'Binds owned payload and session identity, durably journals dispatch, consumes current kernel final-use authority and preserves uncertain effects without replay.'),
        'apply_shell_update': ('updater.rs', 'pub fn verify_and_stage(', 'tests/security_updater.rs',
            'Verifies signed staging and predecessor-bound activation; serializes update transitions and refuses rollback over unrelated installed state.'),
    }
    data['sourceBase'] = {'commit': source, 'tree': tree}
    for op in data['operations']:
        filename, symbol, test, semantics = entries[op['designOperation']]
        source_path = f'apps/hepta-native/src/{filename}'
        op['ownerEntrypoint'].update(path=source_path, symbol=symbol, buildTarget='hepta-native')
        op['nativeSymbol'] = symbol
        op['sourcePath'] = source_path
        op['sourcePathExists'] = True
        op['sourceSemantics'] = semantics
        op['tests'] = [{'path': f'apps/hepta-native/{test}', 'kind': 'rust_integration',
            'command': 'cargo test --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets'}]
    for key in ['repositoryControlledSourceBoundaryGapsClosed', 'productExecutionComplete',
                'deploymentQualificationComplete', 'independentAcceptanceComplete',
                'productionImplementation', 'productExecutionProved', 'independentAcceptance',
                'activation', 'release']:
        data['claimBoundary'][key] = False
    data['productionImplementation'] = False
    data['productCallerState'] = 'not_composed'
    path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    path = ROOT / 'qualification/module-execution-dossiers/NATIVE_BINDINGS.json'
    bindings = json.loads(path.read_text(encoding='utf-8'))
    changed = []
    def visit(value):
        if isinstance(value, dict):
            if value.get('module') == 'ui.native' and 'blobSha' in value:
                native = 'apps/hepta-native/src/runtime.rs'
                value['path'] = native
                value['blobSha'] = git('hash-object', native)
                value['exports'] = ['NativeShellRuntime', 'connect_runtime', 'refresh_runtime_view',
                                    'request_platform_capability', 'reconcile_pending']
                changed.append(native)
            else:
                for child in value.values():
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(bindings)
    if len(changed) != 1:
        raise RuntimeError(f'expected one native source binding, found {len(changed)}')
    path.write_text(json.dumps(bindings, indent=2) + '\n', encoding='utf-8')
    print('bound native mapping to committed source', source)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--write-fingerprints', action='store_true')
    group.add_argument('--sync-metadata', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        prepare()
    elif args.write_fingerprints:
        fingerprint(True)
    elif args.sync_metadata:
        sync_metadata()
    else:
        fingerprint(False)
