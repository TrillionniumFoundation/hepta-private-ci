#!/usr/bin/env python3
"""Freeze committed native sources and refresh only native identity metadata.

The one-time source migration is already committed. This command does not
create implementation, alter owner authority, or turn test sources into passes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / 'apps/hepta-native'
BASE = '7ddbfac88525196e7a4b31387ceae194958275f5'
BRANCH = 'work/ui-native-current-source-20260925'


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def require_branch():
    if git('branch', '--show-current') != BRANCH:
        raise RuntimeError('metadata writes are restricted to the named native candidate')


def prepare():
    require_branch()
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
        require_branch()
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


def native_row(data, collection):
    rows = [row for row in data[collection] if row.get('module') == 'ui.native']
    if len(rows) != 1:
        raise RuntimeError(f'expected exactly one ui.native row in {collection}')
    return rows[0]


def rewrite_retired_navigation(value):
    replacements = {
        'apps/hepta-native/src/native.js': 'apps/hepta-native/src/runtime.rs',
        'apps/hepta-native/src/shell-runtime.js': 'apps/hepta-native/src/runtime.rs',
        'apps/hepta-native/test/native.test.js': 'apps/hepta-native/tests/journal_regressions.rs',
        'apps/hepta-native/test/shell-runtime.test.js': 'apps/hepta-native/tests/runtime.rs',
        'buildNativeIntent': 'request_platform_capability',
        'observeNativeOutcome': 'reconcile_pending',
    }
    if isinstance(value, str):
        if value.startswith('node --test apps/hepta-native/'):
            return 'cargo test --manifest-path apps/hepta-native/Cargo.toml --locked --all-targets'
        return replacements.get(value, value)
    if isinstance(value, list):
        return [rewrite_retired_navigation(child) for child in value]
    if isinstance(value, dict):
        return {key: rewrite_retired_navigation(child) for key, child in value.items()}
    return value


def sync_registry_metadata():
    changes = {}
    relative = 'docs/modules/CARGO_BINDINGS.json'
    data = json.loads((ROOT / relative).read_text(encoding='utf-8'))
    matching = [row for row in data['bindings'] if row['packagePath'] == 'apps/hepta-native']
    if len(matching) > 1 or any(row['module'] != 'ui.native' for row in matching):
        raise RuntimeError('native Cargo package has conflicting owner bindings')
    if not matching:
        data['bindings'].append({'packagePath': 'apps/hepta-native', 'module': 'ui.native'})
        data['bindings'].sort(key=lambda row: row['packagePath'])
    changes[relative] = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
    for relative, collection in [
        ('docs/modules/SOURCE_BINDINGS.json', 'bindings'),
        ('docs/modules/MODULE_DOCS.json', 'modules'),
    ]:
        data = json.loads((ROOT / relative).read_text(encoding='utf-8'))
        row = native_row(data, collection)
        updated = rewrite_retired_navigation(row)
        row.clear()
        row.update(updated)
        if relative.endswith('MODULE_DOCS.json'):
            text = (ROOT / row['path']).read_text(encoding='utf-8')
            row.update(sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                       bytes=len(text.encode('utf-8')), words=len(re.findall(r'\b[\w.-]+\b', text)))
            if any(heading not in text for heading in row['requiredSections']):
                raise RuntimeError('native technical guide is missing a registered section')
        changes[relative] = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
    relative = 'qualification/module-execution-dossiers/DETAILS.json'
    data = json.loads((ROOT / relative).read_text(encoding='utf-8'))
    rows = [row for row in data['rows'] if row.get('path') ==
            'qualification/module-execution-dossiers/detail/ui.native.md']
    if len(rows) != 1:
        raise RuntimeError('native dossier index coverage mismatch')
    text = (ROOT / rows[0]['path']).read_text(encoding='utf-8')
    rows[0]['sha256'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
    changes[relative] = json.dumps(data, separators=(',', ':'), ensure_ascii=False) + '\n'
    for relative, text in changes.items():
        (ROOT / relative).write_text(text, encoding='utf-8')
    # The freeze workflow commits these exact scoped registry changes with the
    # native map; no unrelated owner source or authority registry is staged.
    subprocess.run(['git', 'add', '--', *changes], cwd=ROOT, check=True)


def sync_metadata():
    require_branch()
    source = git('rev-parse', 'HEAD')
    tree = git('rev-parse', 'HEAD^{tree}')
    path = ROOT / 'docs/modules/ui.native/IMPLEMENTATION_MAP.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    entries = {
        'connect_runtime': ('runtime.rs', 'pub fn connect_runtime(', 'tests/runtime.rs'),
        'render_runtime_view': ('runtime.rs', 'pub fn refresh_runtime_view(', 'tests/backend.rs'),
        'request_platform_capability': ('runtime.rs', 'pub fn request_platform_capability(', 'tests/runtime.rs'),
        'apply_shell_update': ('updater.rs', 'pub fn verify_and_stage(', 'tests/security_updater.rs'),
    }
    data['sourceBase'] = {'commit': source, 'tree': tree}
    for op in data['operations']:
        filename, symbol, test = entries[op['designOperation']]
        source_path = f'apps/hepta-native/src/{filename}'
        op['ownerEntrypoint'].update(path=source_path, symbol=symbol, buildTarget='hepta-native')
        op['nativeSymbol'] = symbol
        op['sourcePath'] = source_path
        op['sourcePathExists'] = True
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
    sync_registry_metadata()
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
