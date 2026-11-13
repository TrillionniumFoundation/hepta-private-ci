#!/usr/bin/env python3
"""Freeze exact a489 inputs for offline actual-maintenance fence preparation."""
import ast
import hashlib
import json
import re
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
GRAPH_ROOT = Path('/tmp/hepta-36fa-coordinator-final-candidate-graph-v1')
FROZEN = Path('/tmp/hepta-36fa-coordinator-f905-registration-frozen-v1')
ORIGINAL = Path('/tmp/hepta-36fa-coordinator-f905-registration-v1')
QA = 'qa/b4-no-bypass/'
SEVEN = [
    '.github/blob-size-allowlist.txt',
    '.github/workflows/hepta-daemon-learning-native.yml',
    'CALLERS.toml',
    QA + 'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json',
    QA + 'test_evaluated_published_read_source_closure.py',
    QA + 'test_resident_provider_local_read_source_closure.py',
    QA + 'test_resident_root_source_closure.py',
]


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def put(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        with path.open('xb') as stream:
            stream.write(raw)


def assignment(text, name):
    found = [n for n in ast.parse(text).body if isinstance(n, ast.Assign)
             and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
             and n.targets[0].id == name]
    assert len(found) == 1, name
    return ast.literal_eval(found[0].value)


def main():
    graph_raw = (GRAPH_ROOT / 'CANDIDATE_FILE_GRAPH.json').read_bytes()
    graph = json.loads(graph_raw)
    assert graph['tree'] == 'a489b394666b8141840275128a780605b024cde0'
    rows = {r['path']: r for r in graph['files']}
    assert len(rows) == len(graph['files']) == 15243
    inventory_path = GRAPH_ROOT / 'expected-inventory-v1/EXPECTED_CLEAN_INVENTORY.json'
    inventory_raw = inventory_path.read_bytes()
    assert pin(inventory_raw) == {
        'bytes': 5631947,
        'sha256': '0463522b45970d8ae9dbf5f4560e1b15e61768ec7c9ec164848019009c4643f0',
        'git_blob': 'f1e2d72f99093581403a2dcc91b55da22a33f905'}
    inventory = json.loads(inventory_raw)
    assert inventory['source'] == {
        'head': 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f',
        'tree': graph['tree'], 'status': ''}
    assert len(inventory['files']) == len(rows)
    for r in inventory['files']:
        g = rows[r['path']]
        assert (r['index_mode'], r['working_blob'], r['bytes'], r['sha256']) == (
            g['mode'], g['git_blob'], g['bytes'], g['sha256']), r['path']
    inputs, missing = {}, []
    roots = [GRAPH_ROOT / 'overlay', FROZEN / 'after', ORIGINAL / 'view',
             ORIGINAL / 'before', FROZEN / 'before']
    def obtain(relative):
        if relative in inputs:
            return (HERE / 'before' / relative).read_bytes()
        expected = rows[relative]
        for root in roots:
            source = root / relative
            if source.is_file():
                raw = source.read_bytes()
                if pin(raw) == {k: expected[k] for k in ('bytes', 'sha256', 'git_blob')}:
                    put(HERE / 'before' / relative, raw)
                    inputs[relative] = {'path': relative, 'mode': expected['mode'],
                                        'source_local': str(source), **pin(raw)}
                    return raw
        if relative not in missing:
            missing.append(relative)
        return None
    for relative in SEVEN:
        assert obtain(relative) is not None, relative
    callers = tomllib.loads(obtain('CALLERS.toml').decode())
    contract = json.loads(obtain(QA + 'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json'))
    ordinary = obtain(QA + 'test_evaluated_published_read_source_closure.py').decode()
    ordinary_scopes = assignment(ordinary, 'ORDINARY_SCOPE_GUARDS')
    ordinary_literals = assignment(ordinary, 'ORDINARY_LITERAL_SPECS')
    assert len(callers['boundary']) == 633
    assert len(callers['protected_file']) == 442
    assert len(contract['scopes']) == 45
    assert sum(len(v) for v in contract['scopes'].values()) == 288
    assert sum(len(v) for v in ordinary_scopes.values()) == 34
    assert len(ordinary_literals) == 17
    assert assignment(ordinary, 'ORDINARY_NEW_BOUNDARIES') == callers['boundary'][541:569]
    assert contract['new_boundaries'] == callers['boundary'][569:]
    frozen_manifest = json.loads((FROZEN / 'MANIFEST.json').read_bytes())
    assert len(frozen_manifest['source_paths']) == 7
    for r in frozen_manifest['source_paths']:
        assert pin(obtain(r['path'])) == r['after'], r['path']
    qa_paths = sorted(p for p in rows if p.startswith(QA) and p.endswith('.py') and '/' not in p[len(QA):])
    assert len(qa_paths) == 64, len(qa_paths)
    methods = []
    for path in qa_paths:
        raw = obtain(path)
        if raw is None:
            continue
        text = raw.decode()
        module = ast.parse(text)
        for cls in module.body:
            if isinstance(cls, ast.ClassDef):
                for method in cls.body:
                    if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith('test_'):
                        body = ast.get_source_segment(text, method).encode()
                        methods.append({'path': path, 'class': cls.name, 'method': method.name, **pin(body)})
    expected_sources = set(contract['scopes']) | set(ordinary_scopes)
    expected_sources.update(item['path'] for item in ordinary_literals)
    expected_sources.update(r['path'] for group in contract['attacks'].values() for r in group)
    expected_sources.add('codex-rs/hepta-agentd/src/lib.rs')
    for path in sorted(expected_sources):
        obtain(path)
    helpers = ['scripts/verify_hepta_callers.py', 'scripts/hepta_typed_callers.py',
               'scripts/hepta_main_protection.py', 'scripts/hepta_source_registry_closure.py',
               'scripts/hepta_c_observer_coverage.py']
    for path in helpers:
        obtain(path)
    workflow = obtain('.github/workflows/hepta-daemon-learning-native.yml').decode()
    match = re.search(r'parents = (\[[\s\S]*?\n          \])', workflow)
    assert match
    parents = ast.literal_eval(match.group(1))
    assert len(parents) == len(set(parents)) == 48
    authoring = []
    for source in sorted((FROZEN / 'authoring').glob('*.py')):
        raw = source.read_bytes()
        put(HERE / 'reference-authoring' / source.name, raw)
        authoring.append({'name': source.name, 'source_local': str(source), **pin(raw)})
    result = {
        'format': 'hepta-a489-exact-registration-refresh-baseline-v1',
        'status': 'PREPARATION_ONLY_ACTUAL_MAINTENANCE_TRANSITIONS_PENDING',
        'graph': {'path': str(GRAPH_ROOT / 'CANDIDATE_FILE_GRAPH.json'), **pin(graph_raw)},
        'preheld_complete_inventory': {'path': str(inventory_path), **pin(inventory_raw)},
        'inventory_actual_pin_provenance': 'actual materializer3bb RESULT/ARTIFACTS; exact offline recovery placement8fbeefd451f81b06ca783e69559b0296cdbfc082; not a second native scan',
        'source': inventory['source'], 'source_entries': len(rows),
        'fence_paths': SEVEN, 'boundary_rows': 633, 'protected_rows': 442,
        'provider_paths': 45, 'provider_scopes': 288,
        'ordinary_scopes': 34, 'ordinary_literals': 17,
        'qa_files': 64, 'qa_methods_found': len(methods),
        'root_parents': parents, 'root_parent_count': 48,
        'all_source_inputs': list(inputs.values()), 'missing_source_inputs': missing,
        'original_qa_methods': methods, 'reference_authoring': authoring,
        'actual_maintenance_result': None, 'actual_fix_postimages': None, 'actual_fmt_postimages': None,
        'qa_gate_Rust_native_calls': 0, 'source_tree_or_ref_mutations': 0,
    }
    if not missing:
        assert len(methods) == 607, len(methods)
    put(HERE / 'BASELINE_BINDINGS.json', encoded(result))
    print(json.dumps({'status': result['status'], 'bound_files': len(inputs), 'qa_methods': len(methods),
                      'missing': missing, 'baseline': pin(encoded(result))}, sort_keys=True))


if __name__ == '__main__':
    main()
