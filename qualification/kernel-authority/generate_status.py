#!/usr/bin/env python3
"""Generate authority state and target-port projections from one canonical manifest.

The non-self-referential source anchor must be an ancestor with the exact tree,
and every mapped source/evidence file must be unchanged. Existence, source
composition, execution, target-host qualification and independent acceptance
are separate facts. No projection grants production or release authority.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
MANIFEST = ROOT / 'qualification/kernel-authority/status_manifest.json'
DOCS = ROOT / 'docs/modules/kernel.authority'
OUTPUTS = {
    'implementationMap': DOCS / 'IMPLEMENTATION_MAP.json',
    'currentState': DOCS / 'CURRENT_STATE.json',
    'currentImplementation': DOCS / 'CURRENT_IMPLEMENTATION.md',
    'traceability': DOCS / 'TRACEABILITY.md',
    'status': DOCS / 'STATUS.md',
    'dossierStatus': ROOT / 'qualification/module-execution-dossiers/detail/kernel.authority.status.json',
    'portMatrix': DOCS / 'PORT_MATRIX.json',
    'portMatrixMarkdown': DOCS / 'PORT_MATRIX.md',
}
SHA1 = re.compile(r'[0-9a-f]{40}')
SYMBOL = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*')
EXECUTION_CLAIMS = ('productionImplementation', 'productExecutionProved', 'independentAcceptance', 'activation', 'release')
PORT_FIELDS = ('contractDefined', 'sourceCompositionPresent', 'normalProductInvocationProved',
               'exactCandidateExecutionProved', 'targetHostQualified', 'independentAcceptance')


class StatusError(RuntimeError):
    """Canonical state, source binding or projection is invalid/stale."""


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise StatusError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def load_manifest():
    try:
        value = json.loads(MANIFEST.read_text(encoding='utf-8'), object_pairs_hook=unique_pairs)
    except (OSError, json.JSONDecodeError) as error:
        raise StatusError(f'invalid status manifest: {error}') from error
    if not isinstance(value, dict):
        raise StatusError('status manifest must be an object')
    return value


def git(*args):
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_REPLACE_OBJECTS='1',
               GIT_NO_LAZY_FETCH='1', GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0')
    return subprocess.run(['git', '--literal-pathspecs', '-c', 'core.fsmonitor=false', *args],
                          cwd=ROOT, env=env, check=True, text=True, capture_output=True).stdout.strip()


def canonical_json(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode()


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,127}', value) is not None


def native_symbol(value, name):
    if not isinstance(value, str) or SYMBOL.fullmatch(value) is None:
        raise StatusError(f'{name} must name one atomic code symbol')
    return value


def string_list(value, name, *, nonempty=True):
    if not isinstance(value, list) or (nonempty and not value):
        raise StatusError(f'{name} must be a list with the required entries')
    if any(not isinstance(item, str) or not item for item in value) or len(set(value)) != len(value):
        raise StatusError(f'{name} entries must be unique non-empty strings')
    return value


def relative_file(value, name):
    if not isinstance(value, str) or not value:
        raise StatusError(f'{name} must name a file')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or str(path) != value:
        raise StatusError(f'{name} is not a canonical repository-relative path')
    resolved = (ROOT / value).resolve()
    if not resolved.is_relative_to(ROOT.resolve()) or not resolved.is_file():
        raise StatusError(f'{name} is absent or escapes the repository: {value}')
    return value


def operation_paths(row):
    paths = {relative_file(row.get('sourcePath'), 'operation sourcePath')}
    for field in ('tests', 'delegatedCallees'):
        paths.update(relative_file(path, field) for path in string_list(row.get(field, []), field, nonempty=False))
    return paths


def caller_paths(row):
    paths = {relative_file(row.get('sourcePath'), 'caller sourcePath')}
    paths.update(relative_file(path, 'caller test') for path in string_list(row.get('tests', []), 'caller tests', nonempty=False))
    return paths


def validate_port_rows(rows, declared):
    if not isinstance(rows, list) or not rows:
        raise StatusError('targetPorts must enumerate the declared technical target contracts')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'id', 'sourcePaths', 'note', *PORT_FIELDS}:
            raise StatusError('target port fields must be exact')
        port = row['id']
        if not isinstance(port, str) or port not in declared or port in seen:
            raise StatusError('unknown or duplicate target port')
        seen.add(port)
        for name in PORT_FIELDS:
            if type(row[name]) is not bool:
                raise StatusError(f'{port}.{name} must be boolean')
        if row['contractDefined'] is not True:
            raise StatusError('a declared target must retain its contract-defined fact')
        # Executed/accepted evidence is not supplied by this source manifest.
        if any(row[name] for name in PORT_FIELDS[2:]):
            raise StatusError('source-only target matrix cannot self-grant execution or acceptance')
        paths = string_list(row['sourcePaths'], 'port sourcePaths', nonempty=False)
        if bool(paths) != row['sourceCompositionPresent']:
            raise StatusError('source composition must name its actual mapped caller')
        if not isinstance(row['note'], str) or not row['note']:
            raise StatusError('each target needs its protocol/scope explanation')
    if seen != declared:
        raise StatusError('target port matrix omits a declared contract')


def validate_manifest(manifest):
    if manifest.get('schema') != 'hepta.kernel-authority-status-manifest.v1' or type(manifest.get('schemaVersion')) is not int or manifest['schemaVersion'] != 1:
        raise StatusError('unsupported status manifest schema/version')
    for field in ('module', 'laneId', 'owner', 'deputy', 'status'):
        if not identifier(manifest.get(field)):
            raise StatusError(f'invalid {field}')
    if manifest['module'] != 'kernel.authority':
        raise StatusError('this generator owns only kernel.authority')
    anchor = manifest.get('sourceAnchor')
    if not isinstance(anchor, dict) or set(anchor) != {'commit', 'tree'} or any(not isinstance(v, str) or SHA1.fullmatch(v) is None for v in anchor.values()):
        raise StatusError('sourceAnchor requires exact lowercase commit/tree ids')
    if git('cat-file', '-t', anchor['commit']) != 'commit' or git('rev-parse', f"{anchor['commit']}^{{tree}}") != anchor['tree']:
        raise StatusError('sourceAnchor commit/tree mismatch')
    git('merge-base', '--is-ancestor', anchor['commit'], 'HEAD')
    claims = manifest.get('claimBoundary')
    if not isinstance(claims, dict):
        raise StatusError('claimBoundary must be an object')
    for name in ('nativeSourceMappingComplete', 'sourceRootPresent', 'implementedOperationMappingComplete', *EXECUTION_CLAIMS):
        if type(claims.get(name)) is not bool:
            raise StatusError(f'claimBoundary.{name} must be boolean')
    if any(claims[name] for name in EXECUTION_CLAIMS):
        raise StatusError('repository projections cannot self-grant execution claims')
    for root in string_list(manifest.get('declaredRoots'), 'declaredRoots'):
        resolved = (ROOT / root).resolve()
        if not resolved.is_dir() or not resolved.is_relative_to(ROOT.resolve()):
            raise StatusError(f'invalid declared root: {root}')
    technical = relative_file(manifest.get('technicalGuide'), 'technicalGuide')
    paths = {technical}
    operations = manifest.get('operations')
    if not isinstance(operations, list) or not operations:
        raise StatusError('operations must be nonempty')
    seen = set()
    for row in operations:
        if not isinstance(row, dict) or not identifier(row.get('operation')) or row['operation'] in seen:
            raise StatusError('invalid or duplicate operation')
        seen.add(row['operation'])
        native_symbol(row.get('nativeSymbol'), 'operation nativeSymbol')
        for name in ('state', 'authority', 'designOperation', 'mappingClass'):
            if not isinstance(row.get(name), str) or not row[name]:
                raise StatusError(f'invalid operation {name}')
        paths.update(operation_paths(row))
    callers = manifest.get('productCallers')
    if not isinstance(callers, list) or not callers:
        raise StatusError('productCallers must be nonempty')
    seen = set()
    for row in callers:
        if not isinstance(row, dict) or not identifier(row.get('id')) or row['id'] in seen:
            raise StatusError('invalid or duplicate product caller')
        seen.add(row['id'])
        native_symbol(row.get('nativeSymbol'), 'caller nativeSymbol')
        if not isinstance(row.get('state'), str) or not row['state']:
            raise StatusError('invalid caller state')
        paths.update(caller_paths(row))
    paths.update(relative_file(path, 'tracked path') for path in string_list(manifest.get('trackedPaths'), 'trackedPaths'))
    string_list(manifest.get('repositoryControlledGaps'), 'repositoryControlledGaps')
    string_list(manifest.get('externalEvidenceGates'), 'externalEvidenceGates')
    declared = set(re.findall(r'`(ModulePort::kernel\.authority::[a-z.]+)`', (ROOT / technical).read_text()))
    validate_port_rows(manifest.get('targetPorts'), declared)
    for row in manifest['targetPorts']:
        paths.update(relative_file(path, 'port source') for path in row['sourcePaths'])
    recovery = manifest.get('recoveryEvidence')
    if not isinstance(recovery, dict) or set(recovery) != {'sameProcessOwnerReopen', 'twoFreshProductProcesses', 'targetHostCrashDrill'}:
        raise StatusError('recovery evidence must separate three execution scopes')
    if any(not isinstance(value, str) or not value for value in recovery.values()):
        raise StatusError('recovery scopes require explicit evidence states')
    tracked = sorted(paths)
    for path in tracked:
        if git('cat-file', '-t', f'HEAD:{path}') != 'blob':
            raise StatusError(f'uncommitted status source: {path}')
    changed = git('diff', '--no-ext-diff', '--no-textconv', '--name-only', anchor['commit'], 'HEAD', '--', *tracked)
    dirty = git('diff', '--no-ext-diff', '--no-textconv', '--name-only', 'HEAD', '--', *tracked)
    if changed or dirty:
        raise StatusError('mapped status source changed; rebind the manifest: ' + (changed or dirty).replace('\n', ', '))
    return dict(anchor), tracked


def implementation_map(manifest, anchor):
    operations = [dict(row, sourcePathExists=True, delegatedCallees=row.get('delegatedCallees', [])) for row in manifest['operations']]
    result = {
        'schema': 'hepta.module-implementation-map.v3', 'schemaVersion': 3, 'sourceBase': anchor,
        'mappingSourceIdentityMode': 'path_only', 'exactSourceEvidenceMode': 'lane_a_runtime_wiring_only_no_product_execution_claim',
        **{key: manifest[key] for key in ('laneId', 'module', 'owner', 'deputy', 'technicalGuide', 'declaredRoots')},
        'resolvedRoots': manifest['declaredRoots'], 'sourceRootPresent': manifest['claimBoundary']['sourceRootPresent'],
        'productionImplementation': False, 'productCallerState': manifest['productCallerState'],
        'productionWriterState': manifest['productionWriterState'], 'operations': operations,
        'repositoryControlledGaps': manifest['repositoryControlledGaps'], 'externalEvidenceGates': manifest['externalEvidenceGates'],
        'claimBoundary': manifest['claimBoundary'], 'sourceRoot': manifest['declaredRoots'],
        'traceability': 'docs/modules/kernel.authority/TRACEABILITY.md',
        'trustDecision': 'docs/modules/kernel.authority/ADR-0001-LEASE-TRUST-MODEL.md',
        'linearizationContract': 'docs/modules/kernel.authority/LINEARIZATION.md',
        'productionTrustProfile': 'docs/modules/kernel.authority/PRODUCTION_TRUST_PROFILE.md',
        'productionClosure': 'docs/modules/kernel.authority/PRODUCTION_CLOSURE.md',
        'capacityQualification': 'docs/modules/kernel.authority/CAPACITY_QUALIFICATION.md',
        'statusManifest': 'qualification/kernel-authority/status_manifest.json',
        'statusGenerator': 'qualification/kernel-authority/generate_status.py',
        'productCallers': manifest['productCallers'], 'evidencePrograms': manifest['evidencePrograms'],
    }
    # Share the verifier's evidence inventory; a projection must not erase exact
    # tree/blob bindings added by map migration. Load with this invocation's
    # root so temporary-Git regressions exercise real objects too.
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location('authority_source_maps', SCRIPTS / 'hepta-implementation-maps.py')
    maps = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(maps)
    maps.ROOT = ROOT
    try:
        result['sourceObjects'] = maps.current_source_objects(result)
    except ValueError as error:
        raise StatusError(f'invalid implementation-map source binding: {error}') from error
    return result


def current_state(manifest, anchor):
    return {
        'schema': 'hepta.kernel-authority-current-state.v1', 'schemaVersion': 1,
        'generatedFrom': 'qualification/kernel-authority/status_manifest.json',
        'generatedBy': 'qualification/kernel-authority/generate_status.py', 'sourceBase': anchor,
        **{key: manifest[key] for key in ('module', 'status', 'claimBoundary', 'productionTrustBundle', 'productPilots',
                                         'qualification', 'performanceAndScale', 'repositoryControlledGaps', 'externalEvidenceGates')},
        'activationGranted': False, 'releaseGranted': False,
    }


def markdown_table(headers, rows):
    return ['| ' + ' | '.join(headers) + ' |', '|' + '|'.join(['---'] * len(headers)) + '|',
            *['| ' + ' | '.join(str(cell).replace('|', '\\|') for cell in row) + ' |' for row in rows]]


def preamble(title, anchor):
    return [f'# kernel.authority {title}', '', '<!-- Generated by qualification/kernel-authority/generate_status.py; do not edit. -->', '',
            f"Source anchor: `{anchor['commit']}` / tree `{anchor['tree']}`.", '']


def current_implementation_md(manifest, anchor):
    lines = preamble('current implementation', anchor)
    lines += [f"Status: **{manifest['status']}**.", '',
              'Mapped source and tests exist; only a successful exact-candidate check establishes execution. '
              'Source presence does not close the repository-controlled gaps below. Production implementation, '
              'product execution proof, independent acceptance, activation and release remain false.', '', '## Native operations', '']
    lines += markdown_table(['Operation', 'Native symbol', 'Source', 'State'], [[f"`{r['operation']}`", f"`{r['nativeSymbol']}`", f"`{r['sourcePath']}`", r['state']] for r in manifest['operations']])
    lines += ['', '## Product callers', '']
    lines += markdown_table(['Caller', 'Boundary', 'Source', 'State'], [[f"`{r['id']}`", f"`{r['nativeSymbol']}`", f"`{r['sourcePath']}`", r['state']] for r in manifest['productCallers']])
    lines += ['', 'The complete declared target-port maturity matrix and distinct recovery scopes are in `PORT_MATRIX.md`.', '', '## Repository-controlled gaps', '']
    lines += ['- ' + item for item in manifest['repositoryControlledGaps']]
    lines += ['', '## External evidence gates', ''] + ['- ' + item for item in manifest['externalEvidenceGates']]
    lines += ['', 'Detailed contracts: `TECHNICAL.md`, `LINEARIZATION.md`, `PRODUCTION_TRUST_PROFILE.md`, `PRODUCTION_CLOSURE.md` and `REMEDIATION_20260928.md`.', '']
    return '\n'.join(lines)


def traceability_md(manifest, anchor):
    lines = preamble('traceability', anchor) + ['## Operation-to-test mapping', '']
    lines += markdown_table(['Operation', 'Source', 'Tests/evidence', 'Claim'], [[f"`{r['operation']}`", f"`{r['sourcePath']}`", '<br>'.join(f'`{p}`' for p in r.get('tests', [])) or '—', r['state']] for r in manifest['operations']])
    lines += ['', '## Product-call mapping', '']
    lines += markdown_table(['Caller', 'Source', 'Tests/evidence', 'Claim'], [[f"`{r['id']}`", f"`{r['sourcePath']}`", '<br>'.join(f'`{p}`' for p in r.get('tests', [])) or '—', r['state']] for r in manifest['productCallers']])
    lines += ['', 'Every receipt is exact-candidate-bound. `PORT_MATRIX.md` covers all target contracts declared in the technical guide; separate owner protocols are not relabelled as generic authority integration.', '']
    return '\n'.join(lines)


def status_md(manifest, anchor):
    lines = preamble('status', anchor) + [f"**Current state:** `{manifest['status']}`", '', '## Claim boundary', '']
    lines += markdown_table(['Claim', 'Value'], [[f'`{key}`', str(value).lower()] for key, value in manifest['claimBoundary'].items()])
    lines += ['', 'Native validation and target-host evidence remain separate. Missing, queued, skipped, failed or incomplete checks cannot promote this state. See `CURRENT_IMPLEMENTATION.md`, `PORT_MATRIX.md` and `REMEDIATION_20260928.md`.', '']
    return '\n'.join(lines)


def dossier_status(manifest, anchor):
    return {
        'schema': 'hepta.kernel-authority-dossier-status.v1', 'schemaVersion': 1,
        'generatedFrom': 'qualification/kernel-authority/status_manifest.json',
        'generatedBy': 'qualification/kernel-authority/generate_status.py', 'sourceBase': anchor,
        **{key: manifest[key] for key in ('module', 'laneId', 'status', 'claimBoundary')},
        'operationIds': [row['operation'] for row in manifest['operations']],
        'productCallerIds': [row['id'] for row in manifest['productCallers']],
        'evidencePrograms': manifest['evidencePrograms'], 'externalEvidenceGates': manifest['externalEvidenceGates'],
        'activationGranted': False, 'releaseGranted': False,
    }


def port_matrix(manifest, anchor):
    return {'schema': 'hepta.kernel-authority-target-port-matrix.v1', 'schemaVersion': 1,
            'generatedFrom': 'qualification/kernel-authority/status_manifest.json', 'sourceBase': anchor,
            'inventoryScope': 'produced ModulePort target contracts explicitly declared in TECHNICAL.md',
            'ports': manifest['targetPorts'], 'recoveryEvidence': manifest['recoveryEvidence'],
            'activationGranted': False, 'releaseGranted': False}


def port_matrix_md(manifest, anchor):
    lines = preamble('target-port maturity', anchor)
    lines += ['Scope: every produced `ModulePort::kernel.authority::*` declared in `TECHNICAL.md`. Source composition means a named source callsite, not successful compilation or a deployed invocation. Other modules\' independent protocols remain independent.', '']
    lines += markdown_table(['Target', 'Contract', 'Source composition', 'Normal product invocation proved', 'Exact execution proved', 'Target host', 'Independent acceptance'], [[f"`{row['id']}`", *[str(row[field]).lower() for field in PORT_FIELDS]] for row in manifest['targetPorts']])
    lines += ['', '## Source and protocol boundaries', '']
    for row in manifest['targetPorts']:
        source = ', '.join(f'`{path}`' for path in row['sourcePaths']) or 'No mapped generic-authority consumer.'
        lines += [f"### `{row['id']}`", '', row['note'], '', source, '']
    lines += ['## Recovery evidence scope', '']
    lines += markdown_table(['Scope', 'Evidence state'], [[key, value] for key, value in manifest['recoveryEvidence'].items()])
    lines += ['', 'Agentd TaskFlow source composition is listed separately in `TRACEABILITY.md`; it does not silently add or complete a registered target contract. No source/test fixture supplies target-host or independent acceptance.', '']
    return '\n'.join(lines)


def render_projections(manifest, anchor):
    return {
        OUTPUTS['implementationMap']: canonical_json(implementation_map(manifest, anchor)),
        OUTPUTS['currentState']: canonical_json(current_state(manifest, anchor)),
        OUTPUTS['currentImplementation']: current_implementation_md(manifest, anchor).encode(),
        OUTPUTS['traceability']: traceability_md(manifest, anchor).encode(),
        OUTPUTS['status']: status_md(manifest, anchor).encode(),
        OUTPUTS['dossierStatus']: canonical_json(dossier_status(manifest, anchor)),
        OUTPUTS['portMatrix']: canonical_json(port_matrix(manifest, anchor)),
        OUTPUTS['portMatrixMarkdown']: port_matrix_md(manifest, anchor).encode(),
    }


def render():
    manifest = load_manifest()
    anchor, _ = validate_manifest(manifest)
    return render_projections(manifest, anchor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    try:
        rendered = render()
    except (StatusError, subprocess.CalledProcessError) as error:
        print(f'kernel.authority status generation failed: {error}', file=sys.stderr)
        return 1
    failures = []
    for path, content in rendered.items():
        if args.check:
            if not path.is_file() or path.read_bytes() != content:
                failures.append(path.relative_to(ROOT).as_posix())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    if failures:
        print('kernel.authority generated projections are stale: ' + ', '.join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
