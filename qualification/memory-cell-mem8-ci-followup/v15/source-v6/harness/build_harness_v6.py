#!/usr/bin/env python3
"""Build, but never admit, the independent V6 source-only CI harness."""
import argparse
import ast
import difflib
import hashlib
import json
import lzma
from pathlib import Path
import re
import subprocess
import tomllib

HERE = Path(__file__).resolve().parent
WORK = HERE.parents[1]
ORIGINAL = WORK / 'mem8-source-ci-v5-original-run'
BASE_DRIVER_SHA = 'f32ca75f21c2097a30bda5892606aef80c62e4072837de7e99e42b56b17cfcf9'
BASE_WORKFLOW_SHA = '0190e2b3dfe210e2be5c7531c0a560e0e2716c98ce6057840fcffef958925990'
GOLDEN_SHA = '17ac4ede6046ccde7f2a2952d2e3e699ff75258089e195b3783638ac9735fc96'
CALLERS_BLOB = 'c1a1b945171cdb20723e398cabe6a7888fa0abdb'


def identity(data):
    return {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()}


def exact_replace(text, before, after, count=1):
    if text.count(before) != count:
        raise RuntimeError(f'baseline replacement count differs: {before[:100]!r}')
    return text.replace(before, after)


def tree_listing(raw):
    out = {}
    for record in raw.split(b'\0'):
        if not record:
            continue
        meta, path = record.split(b'\t', 1)
        mode, kind, sha = meta.decode().split()
        assert kind == 'blob' and path.decode() not in out
        out[path.decode()] = {'mode': mode, 'type': kind, 'git_blob': sha}
    return out


def tree_hash(entries):
    root = {}
    for path, row in entries.items():
        cursor = root
        names = path.split('/')
        for name in names[:-1]:
            cursor = cursor.setdefault(name, {})
        assert names[-1] not in cursor
        cursor[names[-1]] = (row['mode'], row['git_blob'])

    def visit(directory):
        raw = b''
        for name, value in sorted(directory.items(), key=lambda x: (x[0] + ('/' if isinstance(x[1], dict) else '')).encode()):
            mode, sha = ('40000', visit(value)) if isinstance(value, dict) else value
            raw += mode.encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(sha)
        return hashlib.sha1(b'tree ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

    return visit(root)


HELPERS = r'''
def strict_json(raw):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON object key: ' + key)
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('non-JSON constant: ' + value)

    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs,
                      parse_constant=invalid_constant)


def canonical_json(value):
    # Preserve array ordering and scalar types; in particular false is not 0.
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode()


def rust_source_inventory(tree_entries, manifest_bytes):
    manifest = tomllib.loads(manifest_bytes.decode('utf-8'))
    roots = manifest['source_roots']
    if not isinstance(roots, list) or not roots or not all(isinstance(x, str) for x in roots):
        raise RuntimeError('invalid frozen caller source_roots')
    paths, by_root = [], []
    for root in roots:
        relative = PurePosixPath(root)
        if relative.is_absolute() or '..' in relative.parts or '.git' in relative.parts:
            raise RuntimeError('unsafe caller source root')
        prefix = relative.as_posix().rstrip('/') + '/'
        selected = []
        for name, row in sorted(tree_entries.items()):
            if name.startswith(prefix) and name.endswith('.rs'):
                if row['type'] != 'blob' or row['mode'] not in ('100644', '100755'):
                    raise RuntimeError('nonregular frozen Rust source: ' + name)
                selected.append(name)
        # Match _source_files exactly: each root contributes all *.rs paths;
        # ignored_path_fragments do not reduce rustFilesScanned.
        paths.extend(selected)
        by_root.append({'root': root, 'rust_files': len(selected)})
    return {'source_roots': roots, 'count_by_root': by_root, 'paths': sorted(paths),
            'rust_files': len(paths), 'ignored_path_fragments_applied': False}


def regression_counts(raw, expected, command_exit):
    text = raw.decode('utf-8')
    summaries = re.findall(r'^Ran (\d+) tests? in [0-9.]+s$', text, re.MULTILINE)
    named = []
    for method, identifier, outcome in re.findall(
        r'^(test_[A-Za-z0-9_]+) \(([^()\r\n]+)\) \.\.\. (.+)$', text, re.MULTILINE
    ):
        named.append({'method': method, 'id': identifier, 'outcome': outcome})
    expected_ids = ['__main__.' + case for case in expected]
    observed_ids = [row['id'] for row in named]
    passed = (command_exit == 0 and summaries == [str(len(expected))]
              and len(named) == len(expected)
              and len(observed_ids) == len(set(observed_ids))
              and sorted(observed_ids) == sorted(expected_ids)
              and all(row['outcome'] == 'ok' and row['id'].endswith('.' + row['method']) for row in named)
              and text.rstrip().endswith('\nOK'))
    return {'status': 'PASS' if passed else 'FAIL', 'command_exit': command_exit,
            'expected_case_ids': expected_ids, 'named_cases': named,
            'ran_test_summaries': summaries,
            'actual_named_pass': sum(row['outcome'] == 'ok' for row in named),
            'actual_named_fail': sum(row['outcome'] in ('FAIL', 'ERROR', 'unexpected success') for row in named),
            'actual_named_skip': sum(row['outcome'].startswith('skipped') for row in named),
            'raw': info(raw), 'no_native_or_model_execution': True}

'''

GOLDEN_LOAD = '''        golden_path = Path(args.golden)
        if (golden_path.is_symlink() or not golden_path.is_file()
                or golden_path.resolve() != workspace / 'harness' / 'qualification' / 'memory-cell-mem8-source-gates-v6' / 'GOLDEN_CALLER_RECEIPT.json'):
            raise RuntimeError('golden caller receipt is not the separate frozen harness input')
        golden_bytes = golden_path.read_bytes()
        write(records / 'GOLDEN_CALLER_RECEIPT.json', golden_bytes)
        if (len(golden_bytes), info(golden_bytes)['sha256']) != (GOLDEN_BYTES, GOLDEN_SHA):
            raise RuntimeError('golden caller receipt exact bytes differ')
        golden = strict_json(golden_bytes)
        if (golden.get('schema'), golden.get('status'), golden.get('authorityGranted'),
                golden.get('rustFilesScanned')) != (
                'hepta.caller-proof-receipt.v2', 'PASS_HEPTA_CALLER_CLOSED_SET', False, 6200):
            raise RuntimeError('unexpected original golden caller receipt')
        if config['expected_initial_tree'] != TREE or len(config['case_renames']) != 13:
            raise RuntimeError('initial tree or original whole-tree rename inventory differs')
        if {key: config['reference_caller_receipt'][key] for key in ('bytes', 'sha256', 'git_blob')} != info(golden_bytes):
            raise RuntimeError('capsule golden reference differs from retained original')
'''

INVENTORY = '''        caller_manifest = (source / 'CALLERS.toml').read_bytes()
        if info(caller_manifest)['git_blob'] != CALLERS_BLOB or expected_tree['CALLERS.toml']['git_blob'] != CALLERS_BLOB:
            raise RuntimeError('frozen caller manifest changed')
        write(records / 'CALLERS.toml', caller_manifest)
        caller_inventory = rust_source_inventory(expected_tree, caller_manifest)
        if caller_inventory['rust_files'] != EXPECTED_RUST_FILES:
            raise RuntimeError('full frozen tree Rust source count differs from reviewed inventory')
        save('CALLER_SOURCE_INVENTORY.json', {
            'initial_commit': HEAD, 'initial_tree': TREE, 'caller_manifest': info(caller_manifest),
            'original_golden_count': golden['rustFilesScanned'],
            'derived_count_delta': caller_inventory['rust_files'] - golden['rustFilesScanned'],
            'only_allowed_receipt_field_change': 'rustFilesScanned', **caller_inventory})
'''

REGRESSIONS_AND_COMPARE = '''        for script, expected_cases in REGRESSION_CASES.items():
            label = 'python-' + Path(script).stem
            raw = command(label, [sys.executable, '-B', script, '-v'], allowed=(0, 1))
            phase = strict_json((records / (label + '.json')).read_bytes())
            counts = regression_counts(raw, expected_cases, phase['exit_code'])
            source_python_regressions[label] = counts
            save(label + '-COUNTS.json', counts)
            if counts['status'] != 'PASS':
                raise RuntimeError('source Python regression identities/counts/OK check failed: ' + label)
            completed.append(label)
        self_test_raw = command('caller-self-test', [sys.executable, '-B', 'scripts/verify_hepta_callers.py', 'self-test'])
        self_test = strict_json(self_test_raw)
        if canonical_json(self_test) != canonical_json({'status': 'PASS_HEPTA_CALLER_PROOF_SELF_TEST'}):
            raise RuntimeError('caller self-test receipt differs from the original exact status')
        save('CALLER_SELF_TEST_CHECK.json', {'status': 'PASS', 'receipt': self_test, 'raw': info(self_test_raw)})
        completed.append('caller-self-test')
        caller_raw = command('caller-verify', [sys.executable, '-B', 'scripts/verify_hepta_callers.py', 'verify'])
        actual_caller = strict_json(caller_raw)
        expected_caller = strict_json(golden_bytes)
        expected_caller['rustFilesScanned'] = caller_inventory['rust_files']
        save('EXPECTED_CALLER_RECEIPT.json', expected_caller)
        equal = canonical_json(actual_caller) == canonical_json(expected_caller)
        caller_equivalence = {
            'status': 'PASS' if equal else 'FAIL', 'full_json_comparison': True,
            'array_order_and_scalar_types_preserved': True, 'duplicate_object_keys_rejected': True,
            'ignored_receipt_fields': [], 'only_derived_field': 'rustFilesScanned',
            'original_golden': info(golden_bytes), 'actual_original_raw': info(caller_raw),
            'original_golden_count': golden['rustFilesScanned'],
            'derived_frozen_tree_count': caller_inventory['rust_files'],
            'explicit_count_delta': caller_inventory['rust_files'] - golden['rustFilesScanned'],
            'expected_canonical_sha256': info(canonical_json(expected_caller))['sha256'],
            'actual_canonical_sha256': info(canonical_json(actual_caller))['sha256']}
        save('CALLER_GOLDEN_COMPARISON.json', caller_equivalence)
        if not equal:
            raise RuntimeError('full caller JSON differs beyond the frozen-tree-derived Rust count')
        completed.append('caller-verify')
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--assembly', type=Path, required=True)
    parser.add_argument('--pure-head', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.pure_head):
        raise RuntimeError('pure head must be an actual immutable commit ID supplied by the publisher')
    assembly_bytes = args.assembly.read_bytes()
    assembly = json.loads(assembly_bytes)
    encoded = (args.assembly.parent / 'INPUT_SOURCE_GATES.json.xz').read_bytes()
    golden = (args.assembly.parent / 'GOLDEN_CALLER_RECEIPT.json').read_bytes()
    assert identity(encoded) == assembly['input']
    assert identity(golden) == assembly['golden_caller_receipt']
    assert len(golden) == 75046 and identity(golden)['sha256'] == GOLDEN_SHA
    config = json.loads(lzma.decompress(encoded))
    assert config['source_gate_run_version'] == 6 and config['expected_initial_tree'] == assembly['candidate_tree']
    rows = config['files']
    assert len(rows) == len({r['path'] for r in rows}) == assembly['cumulative_paths']
    base = tree_listing((ORIGINAL / 'records/BASE_TREE.ls-tree').read_bytes())
    assert tree_hash(base) == assembly['base_tree']
    candidate = dict(base)
    for row in rows:
        data = row['content'].encode()
        assert identity(data) == {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['input_git_blob']}
        assert (base.get(row['path']) or {}).get('git_blob') == row['preimage_git_blob']
        candidate[row['path']] = {'mode': row['mode'], 'type': 'blob', 'git_blob': row['input_git_blob']}
    assert tree_hash(candidate) == assembly['candidate_tree']
    assert len(candidate) == assembly['full_candidate_entries']
    callers = (HERE / 'reference/CALLERS.toml').read_bytes()
    assert identity(callers)['git_blob'] == CALLERS_BLOB == candidate['CALLERS.toml']['git_blob']
    source_roots = tomllib.loads(callers.decode())['source_roots']
    rust_paths = [p for root in source_roots for p in sorted(candidate) if p.startswith(root.rstrip('/') + '/') and p.endswith('.rs')]
    assert len(rust_paths) == 6201 and json.loads(golden)['rustFilesScanned'] == 6200
    regression_cases = {}
    for path, count in [('scripts/test_hepta_typed_callers.py', 16), ('scripts/test_hepta_caller_cache.py', 2)]:
        content = next(r['content'] for r in rows if r['path'] == path)
        tree = ast.parse(content)
        cases = [f'{node.name}.{method.name}' for node in tree.body if isinstance(node, ast.ClassDef)
                 for method in node.body if isinstance(method, ast.FunctionDef) and method.name.startswith('test_')]
        assert len(cases) == len(set(cases)) == count
        regression_cases[path] = sorted(cases)
    driver_bytes = (ORIGINAL / 'records/DRIVER.py').read_bytes()
    workflow_bytes = (ORIGINAL / 'revision2-workflow.yml').read_bytes()
    assert identity(driver_bytes)['sha256'] == BASE_DRIVER_SHA
    assert identity(workflow_bytes)['sha256'] == BASE_WORKFLOW_SHA
    driver = driver_bytes.decode()
    workflow = workflow_bytes.decode()
    driver = exact_replace(driver, "import time\n", "import time\nimport tomllib\n")
    driver = exact_replace(driver, "HEAD = 'c842e995b047eb2ee7d81c073f14fb2fcaa6bff2'", f"HEAD = '{args.pure_head}'")
    driver = exact_replace(driver, "TREE = 'e9ba2746237562d68b1c732bee0f86df9e352cde'", f"TREE = '{assembly['candidate_tree']}'")
    driver = exact_replace(driver, "INPUT_SHA = '948e8c9ff924317f55feaa45a0c9bac92c29196f6bf652a888ddf7c8795bb0d0'",
                           f"INPUT_SHA = '{assembly['input']['sha256']}'\nINPUT_BYTES = {len(encoded)}\nPATH_COUNT = {len(rows)}\nGOLDEN_SHA = '{GOLDEN_SHA}'\nGOLDEN_BYTES = {len(golden)}\nCALLERS_BLOB = '{CALLERS_BLOB}'\nEXPECTED_RUST_FILES = {len(rust_paths)}\nREGRESSION_CASES = {regression_cases!r}")
    driver = exact_replace(driver, "def main():\n", HELPERS + "\ndef main():\n")
    driver = exact_replace(driver, "('source', 'output', 'input', 'expected-head', 'expected-tree', 'base')", "('source', 'output', 'input', 'golden', 'expected-head', 'expected-tree', 'base')")
    driver = exact_replace(driver, "(333228, INPUT_SHA)", "(INPUT_BYTES, INPUT_SHA)")
    driver = exact_replace(driver, "!= (BASE, BASE_TREE, 5)", "!= (BASE, BASE_TREE, 6)")
    driver = exact_replace(driver, "len(rows) != 103", "len(rows) != PATH_COUNT")
    driver = exact_replace(driver, "        write(records / 'DRIVER.py', Path(__file__).read_bytes())", GOLDEN_LOAD + "        write(records / 'DRIVER.py', Path(__file__).read_bytes())")
    driver = exact_replace(driver, "        locks_before = lock_pins()", INVENTORY + "        locks_before = lock_pins()")
    original_caller = """        command('caller-self-test', [sys.executable, '-B', 'scripts/verify_hepta_callers.py', 'self-test'])
        completed.append('caller-self-test')
        command('caller-verify', [sys.executable, '-B', 'scripts/verify_hepta_callers.py', 'verify'])
        completed.append('caller-verify')
"""
    driver = exact_replace(driver, original_caller, REGRESSIONS_AND_COMPARE)
    driver = exact_replace(driver, "    rows = []\n", "    rows = []\n    source_python_regressions = {}\n    caller_equivalence = None\n")
    driver = exact_replace(driver, "                  'source_candidate_committed': False,", "                  'source_python_regressions': source_python_regressions,\n                  'caller_golden_comparison': caller_equivalence,\n                  'source_candidate_committed': False,")
    for old, new in [('103-path overlay', f'{len(rows)}-path overlay'), ('all 103 reviewed paths', f'all {len(rows)} reviewed paths'), ('at most 103 reviewed paths', f'at most {len(rows)} reviewed paths')]:
        driver = exact_replace(driver, old, new)
    driver = driver.replace('mem8-source-gates-v5', 'mem8-source-gates-v6').replace('frozen V5 input', 'frozen V6 input')
    workflow = workflow.replace('source-gates-v5', 'source-gates-v6').replace('source_gates_v5', 'source_gates_v6').replace('MEM8 V5', 'MEM8 V6')
    workflow = exact_replace(workflow, 'c842e995b047eb2ee7d81c073f14fb2fcaa6bff2', args.pure_head, count=2)
    workflow = exact_replace(workflow, 'e9ba2746237562d68b1c732bee0f86df9e352cde', assembly['candidate_tree'])
    workflow = exact_replace(workflow, '          fetch-depth: 4', '          fetch-depth: 6')
    workflow = exact_replace(workflow,
        '            harness/qualification/memory-cell-mem8-source-gates-v6/INPUT_SOURCE_GATES.json.xz \\\n',
        '            harness/qualification/memory-cell-mem8-source-gates-v6/INPUT_SOURCE_GATES.json.xz \\\n            harness/qualification/memory-cell-mem8-source-gates-v6/GOLDEN_CALLER_RECEIPT.json \\\n')
    workflow = exact_replace(workflow,
        '            --input "$GITHUB_WORKSPACE/harness/qualification/memory-cell-mem8-source-gates-v6/INPUT_SOURCE_GATES.json.xz" \\\n',
        '            --input "$GITHUB_WORKSPACE/harness/qualification/memory-cell-mem8-source-gates-v6/INPUT_SOURCE_GATES.json.xz" \\\n            --golden "$GITHUB_WORKSPACE/harness/qualification/memory-cell-mem8-source-gates-v6/GOLDEN_CALLER_RECEIPT.json" \\\n')
    assert 'source-gates-v5' not in driver + workflow and 'source_gates_v5' not in driver + workflow
    ast.parse(driver)
    import yaml
    parsed = yaml.safe_load(workflow)
    job = parsed['jobs']['source-only']
    assert job['timeout-minutes'] == 20 and parsed['permissions'] == {'contents': 'read'}
    assert all('runner.' not in str(value) for value in job['env'].values())
    assert [s['with']['fetch-depth'] for s in job['steps'] if str(s.get('uses', '')).startswith('actions/checkout@')] == [1, 6]
    shell_checks, inline_checks = [], []
    for step in job['steps']:
        if 'uses' in step:
            assert re.search(r'@[0-9a-f]{40}$', step['uses'])
        if 'run' not in step:
            continue
        check = subprocess.run(['bash', '-n'], input=step['run'], text=True, capture_output=True)
        assert check.returncode == 0, (step['name'], check.stderr)
        shell_checks.append(step['name'])
        for block in re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", step['run'], re.DOTALL):
            ast.parse(block)
            inline_checks.append(step['name'])
    args.output.mkdir(parents=True, exist_ok=False)
    files = {
        '.github/scripts/mem8_source_gates_v6.py': driver.encode(),
        '.github/workflows/hepta-mem8-source-gates-v6.yml': workflow.encode(),
        'qualification/memory-cell-mem8-source-gates-v6/INPUT_SOURCE_GATES.json.xz': encoded,
        'qualification/memory-cell-mem8-source-gates-v6/GOLDEN_CALLER_RECEIPT.json': golden,
    }
    for path, data in files.items():
        output = args.output / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
    for name, old, new in [('DRIVER_V5_TO_V6.patch', driver_bytes.decode(), driver), ('WORKFLOW_V5_TO_V6.patch', workflow_bytes.decode(), workflow)]:
        (args.output / name).write_text(''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile='v5/' + name, tofile='v6/' + name)))
    audit = {'schema': 'hepta.mem8.source-v6.harness-static-validation.v1',
             'pure_source_head': args.pure_head, 'pure_source_tree': assembly['candidate_tree'],
             'cumulative_paths': len(rows), 'complete_entries': len(candidate),
             'assembly': identity(assembly_bytes), 'input': identity(encoded), 'golden': identity(golden),
             'golden_source_count': 6200, 'full_frozen_tree_rust_count': len(rust_paths), 'explicit_rust_count_delta': len(rust_paths) - 6200,
             'caller_source_roots': source_roots, 'caller_manifest': identity(callers),
             'python_regression_case_ids': regression_cases, 'python_regression_expected_total': sum(map(len, regression_cases.values())),
             'gate_budget_seconds': 600, 'workflow_job_minutes': 20,
             'bash_syntax_checked_steps': shell_checks, 'inline_python_ast_checked_steps': inline_checks,
             'driver_ast': 'PASS', 'workflow_yaml': 'PASS', 'job_env_runner_contexts': 0,
             'checkout_depths_harness_source': [1, 6], 'pure_source_and_harness_isolated': True,
             'source_gate_executed': False, 'native_tests_executed': 0, 'model_requests_executed': 0,
             'ref_changes': 0, 'baseline_driver': identity(driver_bytes), 'baseline_workflow': identity(workflow_bytes),
             'outputs': [{'path': p, **identity(b)} for p, b in files.items()]}
    (args.output / 'STATIC_VALIDATION.json').write_text(json.dumps(audit, indent=2) + '\n')
    print(json.dumps({key: audit[key] for key in ['pure_source_head', 'pure_source_tree', 'cumulative_paths', 'full_frozen_tree_rust_count', 'python_regression_expected_total', 'outputs']}, indent=2))


if __name__ == '__main__':
    main()
