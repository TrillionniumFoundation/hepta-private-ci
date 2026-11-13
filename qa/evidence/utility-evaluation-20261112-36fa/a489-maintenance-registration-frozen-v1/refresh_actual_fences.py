#!/usr/bin/env python3
"""Refresh existing exact source guards from actual fix/fmt bytes only.

No boundary, assertion, scope selector, ignored path, owner or budget is added
or relaxed. Original lexical/scope helpers alone are evaluated; no QA class,
verifier gate, project main, Rust command or H call is invoked.
"""
import ast
import copy
import difflib
import hashlib
import json
import pprint
import re
import types
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACTUAL = Path('/tmp/hepta-36fa-a489-actual-maintenance-source-review-v1')
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


def dump(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def save(path, raw):
    target = HERE / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == raw, str(target)
    else:
        with target.open('xb') as f:
            f.write(raw)
    return {'path': str(target), **pin(raw)}


def source(path, final=False):
    candidate = ACTUAL / ('after' if final else 'before') / path
    return candidate.read_text() if candidate.exists() else (HERE / 'before' / path).read_text()


def assignment(text, name):
    items = [n for n in ast.parse(text).body if isinstance(n, ast.Assign) and len(n.targets) == 1
             and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name]
    assert len(items) == 1, name
    return items[0]


def value(text, name):
    return ast.literal_eval(assignment(text, name).value)


def offsets(text, node):
    lines = text.splitlines(keepends=True)
    start = sum(len(x) for x in lines[:node.lineno - 1]) + len(lines[node.lineno - 1].encode()[:node.col_offset].decode())
    stop = sum(len(x) for x in lines[:node.end_lineno - 1]) + len(lines[node.end_lineno - 1].encode()[:node.end_col_offset].decode())
    return start, stop


def toml(value):
    if isinstance(value, str): return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool): return str(value).lower()
    if isinstance(value, list): return '[' + ', '.join(toml(x) for x in value) + ']'
    if isinstance(value, dict): return '{ ' + ', '.join(k + ' = ' + toml(v) for k, v in value.items()) + ' }'
    if isinstance(value, int): return str(value)
    raise TypeError(type(value))


def table(kind, row):
    return '[[' + kind + ']]\n' + '\n'.join(k + ' = ' + toml(v) for k, v in row.items()) + '\n\n'


def main():
    baseline = json.loads((HERE / 'BASELINE_COMPLETE_BINDINGS.json').read_bytes())
    assert baseline['missing_source_inputs'] == [] and baseline['qa_methods_found'] == 607
    actual_review = json.loads((ACTUAL / 'ACTUAL_BYTE_AND_LEXICAL_REVIEW.json').read_bytes())
    assert actual_review['final_physical_tree'] == 'c026a8d7e93c958b39a36c666debecb3dba4be14'
    assert actual_review['all_initial_to_fix_to_fmt_to_final_rows_and_raw_bytes_equal'] is True
    changed = {r['path'] for x in actual_review['transitions'] if x['stage'] == 'final' for r in x['rows']}
    assert len(changed) == 17
    original_lexical = (HERE / 'before/scripts/verify_hepta_callers.py').read_text()
    names = {'VerificationFailure', '_strip_rust_non_code', '_cfg_without_test', '_strip_cfg_test_items',
             '_matching_delimiter', '_skip_space', '_rust_item_end', '_looks_like_char_literal'}
    nodes = [n for n in ast.parse(original_lexical).body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    assert {n.name for n in nodes} == names
    raw_start = [n for n in ast.parse(original_lexical).body if isinstance(n, ast.Assign)
                 and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                 and n.targets[0].id == 'RAW_STRING_START']
    assert len(raw_start) == 1
    nodes = raw_start + nodes
    lexical = {'re': re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'original-lexical-helpers-only', 'exec'), lexical)
    P = types.SimpleNamespace(**lexical)
    ordinary_path = QA + 'test_evaluated_published_read_source_closure.py'
    ordinary_text = (HERE / 'before' / ordinary_path).read_text()
    nodes = [n for n in ast.parse(ordinary_text).body if isinstance(n, ast.FunctionDef) and n.name.startswith('ordinary_')]
    ns = {'PROOF': P, 're': re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'original-scope-locators-only', 'exec'), ns)
    scopes = types.SimpleNamespace(**ns)
    provider_path = QA + 'test_resident_provider_local_read_source_closure.py'
    provider_text = (HERE / 'before' / provider_path).read_text()
    nodes = [n for n in ast.parse(provider_text).body if isinstance(n, ast.FunctionDef) and n.name in
             {'require', 'active_source', 'actual_scope', 'module_shape'}]
    pn = {'PROOF': P, 'SCOPES': scopes, 're': re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'original-provider-span-locators-only', 'exec'), pn)
    active_source, actual_scope, module_shape = pn['active_source'], pn['actual_scope'], pn['module_shape']
    original_refresh = (HERE / 'reference-authoring/refresh_formatted_guards.py').read_text()
    nodes = [n for n in ast.parse(original_refresh).body if isinstance(n, ast.FunctionDef)]
    rn = {'P': P, 're': re, 'difflib': difflib, 'hashlib': hashlib, 'maps': {},
          'TOK': re.compile(r'[A-Za-z_][A-Za-z_0-9]*|[0-9]+|[^\s]')}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'original-author-span-remapping-functions-only', 'exec'), rn)
    active, remap, function, locate_sequence = (rn[x] for x in ('active', 'remap', 'function', 'locate_sequence'))

    old_text = (HERE / 'before/CALLERS.toml').read_text()
    old = tomllib.loads(old_text)
    candidate = copy.deepcopy(old)
    assert len(old['boundary']) == 633 and len(old['protected_file']) == 442
    guard_changes, inspected_rows = [], []
    for index, row in enumerate(candidate['protected_file']):
        path = row['path']
        if path not in changed:
            continue
        previous = copy.deepcopy(row)
        before_raw, after_raw = source(path), source(path, True)
        before, after = active(before_raw), active(after_raw)
        replacements = []
        for j, marker in enumerate(row['required']):
            current = remap(marker, before_raw, after_raw, f'row{index}.required[{j}]')
            if current != marker: replacements.append({'field': f'required[{j}]', 'before': marker, 'after': current})
            row['required'][j] = current
        for j, sequence in enumerate(row.get('required_order', [])):
            for k, marker in enumerate(sequence):
                current = remap(marker, before, after, f'row{index}.required_order[{j}][{k}]')
                if current != marker: replacements.append({'field': f'required_order[{j}][{k}]', 'before': marker, 'after': current})
                sequence[k] = current
            locate_sequence(sequence, after, f'row{index}.required_order[{j}]')
        for j, guard in enumerate(row.get('required_function_order', [])):
            old_body, a, b = function(before, guard['function'])
            new_body, c, d = function(after, guard['function'])
            for key in ('sequence', 'top_level', 'literal_calls'):
                for k, marker in enumerate(guard.get(key, [])):
                    left, right = (before_raw[a:b], after_raw[c:d]) if key == 'literal_calls' or marker in guard.get('literal_calls', []) else (old_body, new_body)
                    current = remap(marker, left, right, f'row{index}.function[{j}].{key}[{k}]')
                    if current != marker:
                        replacements.append({'field': f'required_function_order[{j}].{key}[{k}]', 'before': marker, 'after': current})
                    guard[key][k] = current
            sequence = [x for x in guard['sequence'] if x not in guard.get('literal_calls', [])]
            locate_sequence(sequence, new_body, f'row{index}.function[{j}]')
            for marker in guard.get('top_level', []):
                assert new_body.count(marker) == 1
                prefix = new_body[:new_body.index(marker)]
                assert prefix.count('{') - prefix.count('}') == 1
        assert previous['forbidden'] == row['forbidden']
        # Keep all additional constraint shape/order. Any raw literal or top
        # level span update is recorded in full, not removed or deduplicated.
        assert previous.keys() == row.keys()
        for key in ('required_order', 'required_function_order'):
            assert len(previous.get(key, [])) == len(row.get(key, []))
        inspected_rows.append({'row': index, 'path': path, 'changed': previous != row,
                               'before_source': pin(before_raw.encode()), 'after_source': pin(after_raw.encode())})
        if previous != row:
            guard_changes.append({'row': index, 'path': path, 'before': previous, 'after': copy.deepcopy(row),
                                  'replacements': replacements})
    assert candidate['boundary'] == old['boundary']
    assert all(a['forbidden'] == b['forbidden'] for a, b in zip(old['protected_file'], candidate['protected_file']))
    assert candidate['protected_file'][411] == old['protected_file'][411]
    assert all(candidate[k] == old[k] for k in old if k != 'protected_file')
    starts = list(re.finditer(r'(?m)^\[\[(boundary|protected_file)\]\]\n', old_text))
    authority = old_text.index('[authority]')
    chunks, boundary_i, protected_i = [old_text[:starts[0].start()]], 0, 0
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else authority
        block = old_text[match.start():end]
        if match.group(1) == 'boundary':
            chunks.append(block)
            boundary_i += 1
        else:
            row = candidate['protected_file'][protected_i]
            chunks.append(block if row == old['protected_file'][protected_i] else table('protected_file', row))
            protected_i += 1
    assert (boundary_i, protected_i) == (633, 442)
    chunks.append(old_text[authority:])
    callers = ''.join(chunks).encode()
    assert tomllib.loads(callers.decode()) == candidate
    save('after/CALLERS.toml', callers)

    contract_path = QA + 'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json'
    original_contract_raw = (HERE / 'before' / contract_path).read_bytes()
    original_contract = json.loads(original_contract_raw)
    contract = copy.deepcopy(original_contract)
    provider_updates, shape_updates = [], []
    for path, guards in contract['scopes'].items():
        before_raw, after_raw = source(path), source(path, True)
        bc, bl = active_source(before_raw); ac, al = active_source(after_raw)
        assert module_shape(bc, bl) == original_contract['module_shapes'][path], path
        for guard in guards:
            start, stop = actual_scope(bc, guard['selector'])
            expected = {'masked_sha256': hashlib.sha256(bc[start:stop].encode()).hexdigest(),
                        'literal_source_sha256': hashlib.sha256(bl[start:stop].encode()).hexdigest()}
            assert all(guard[k] == v for k, v in expected.items()), (path, guard['selector'])
            start, stop = actual_scope(ac, guard['selector'])
            updated = {'masked_sha256': hashlib.sha256(ac[start:stop].encode()).hexdigest(),
                       'literal_source_sha256': hashlib.sha256(al[start:stop].encode()).hexdigest()}
            if expected != updated:
                provider_updates.append({'path': path, 'selector': guard['selector'], 'before': expected, 'after': updated})
            guard.update(updated)
        next_shape = module_shape(ac, al)
        if next_shape != contract['module_shapes'][path]:
            shape_updates.append({'path': path, 'before': contract['module_shapes'][path], 'after': next_shape})
        contract['module_shapes'][path] = next_shape
    assert len(contract['scopes']) == 45 and sum(map(len, contract['scopes'].values())) == 288
    assert contract['attacks'] == original_contract['attacks']
    assert contract['mounts'] == original_contract['mounts'] and contract['exports'] == original_contract['exports']
    assert contract['new_boundaries'] == candidate['boundary'][569:]
    checked = {k: candidate[k] for k in ('boundary','privileged_inventory','authority','source_roots','ignored_path_fragments')}
    digest = hashlib.sha256(json.dumps(checked, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert digest == contract['complete_boundary_sha256']
    # Preserve historical source_refresh_basis; add the subsequent actual
    # transformation provenance without replacing that earlier origin.
    contract['actual_maintenance_refresh'] = {
        'source_commit': 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f',
        'base_physical_tree': 'a489b394666b8141840275128a780605b024cde0',
        'actual_final_physical_tree': 'c026a8d7e93c958b39a36c666debecb3dba4be14',
        'actual_result': 'b87aed7647ac34e3db0e381110bf685438aee0ee',
        'actual_final_postimages': '88b9299120113937610da4a84b344eda76011674',
        'no_new_scope_selector_boundary_or_attack': True,
        'qualification': False,
    }
    contract_raw = dump(contract)
    save('after/' + contract_path, contract_raw)

    ordinary = ordinary_text
    old_scopes = value(ordinary, 'ORDINARY_SCOPE_GUARDS')
    scopes_after = copy.deepcopy(old_scopes)
    ordinary_updates = []
    for path, guards in scopes_after.items():
        bc = active(source(path)); ac = active(source(path, True))
        for guard in guards:
            old_span = scopes.ordinary_select_scope(P, bc, guard['selector'])
            new_span = scopes.ordinary_select_scope(P, ac, guard['selector'])
            old_hash = hashlib.sha256(bc[old_span['start']:old_span['end']].encode()).hexdigest()
            new_hash = hashlib.sha256(ac[new_span['start']:new_span['end']].encode()).hexdigest()
            assert old_hash == guard['masked_sha256']
            if old_hash != new_hash:
                ordinary_updates.append({'path': path, 'selector': guard['selector'], 'before': old_hash, 'after': new_hash})
            guard['masked_sha256'] = new_hash
    node = assignment(ordinary, 'ORDINARY_SCOPE_GUARDS').value
    a, b = offsets(ordinary, node); raw_value = ordinary[a:b]
    for item in ordinary_updates:
        assert raw_value.count(item['before']) == 1
        raw_value = raw_value.replace(item['before'], item['after'])
    ordinary = ordinary[:a] + raw_value + ordinary[b:]
    assert value(ordinary, 'ORDINARY_COMPLETE_BOUNDARY_SHA256') == digest
    assert value(ordinary, 'ORDINARY_NEW_BOUNDARIES') == candidate['boundary'][541:569]
    assert value(ordinary, 'ORDINARY_LITERAL_SPECS') == value(ordinary_text, 'ORDINARY_LITERAL_SPECS')
    assert sum(map(len, scopes_after.values())) == 34 and len(value(ordinary, 'ORDINARY_LITERAL_SPECS')) == 17
    save('after/' + ordinary_path, ordinary.encode())

    old_contract_hash, new_contract_hash = hashlib.sha256(original_contract_raw).hexdigest(), hashlib.sha256(contract_raw).hexdigest()
    assert provider_text.count(old_contract_hash) == 1
    provider_after = provider_text.replace(old_contract_hash, new_contract_hash)
    save('after/' + provider_path, provider_after.encode())
    for path in ('.github/workflows/hepta-daemon-learning-native.yml', QA + 'test_resident_root_source_closure.py'):
        save('after/' + path, (HERE / 'before' / path).read_bytes())
    allow_path = '.github/blob-size-allowlist.txt'
    allow = (HERE / 'before' / allow_path).read_bytes()
    assert allow.endswith(b'\n')
    line = ('sha256:' + hashlib.sha256(callers).hexdigest() + ' CALLERS.toml\n').encode()
    assert line not in allow
    save('after/' + allow_path, allow + b'# Exact actual a489 scoped-fix and format source guard refresh; no wildcard.\n' + line)

    # Static exact marker location checks are distinct from invoking attacks.
    anchors = []
    for group, attacks in contract['attacks'].items():
        for attack in attacks:
            path = attack['path']
            bc, _ = active_source(source(path)); ac, _ = active_source(source(path, True))
            selector = {'kind': 'unique_function', 'name': attack['function']}
            bs = scopes.ordinary_select_scope(P, bc, selector)
            ass = scopes.ordinary_select_scope(P, ac, selector)
            marker = attack['marker']
            pattern = r'\s*'.join(re.escape(x) for x in re.findall(r'\w+|[^\w\s]', marker))
            if marker[0].isalnum() or marker[0] == '_': pattern = r'(?<!\w)' + pattern
            if marker[-1].isalnum() or marker[-1] == '_': pattern += r'(?!\w)'
            n = len(re.findall(pattern, bc[bs['start']:bs['end']]))
            m = len(re.findall(pattern, ac[ass['start']:ass['end']]))
            assert n == m and n > 0, attack
            anchors.append({'group': group, **attack, 'before_occurrences': n, 'after_occurrences': m})
    assert len(anchors) == 107
    method_count, method_equal, qa_files = 0, 0, 0
    for path in sorted((HERE / 'before' / QA).glob('*.py')):
        relative = path.relative_to(HERE / 'before')
        before = path.read_text(); after_path = HERE / 'after' / relative
        after = after_path.read_text() if after_path.exists() else before
        def methods(text):
            return {(c.name,m.name):ast.get_source_segment(text,m)
                    for c in ast.parse(text).body if isinstance(c,ast.ClassDef)
                    for m in c.body if isinstance(m,(ast.FunctionDef,ast.AsyncFunctionDef)) and m.name.startswith('test_')}
        bm, am = methods(before), methods(after)
        assert bm.keys() == am.keys()
        assert all(bm[k] == am[k] for k in bm), str(relative)
        method_count += len(bm); method_equal += sum(bm[k] == am[k] for k in bm); qa_files += 1
    assert (qa_files, method_count, method_equal) == (64,607,607)
    workflow = (HERE / 'after/.github/workflows/hepta-daemon-learning-native.yml').read_text()
    parents = ast.literal_eval(re.search(r'parents = (\[[\s\S]*?\n          \])',workflow).group(1))
    assert parents == baseline['root_parents'] and len(parents) == 48
    report = {
        'format':'hepta-actual-maintenance-exact-fence-refresh-v1',
        'status':'PREPARED_EXACT_ACTUAL_SOURCE_GUARDS_NOT_QUALIFIED',
        'actual_source_review':pin((ACTUAL/'ACTUAL_BYTE_AND_LEXICAL_REVIEW.json').read_bytes()),
        'base_physical_tree':'c026a8d7e93c958b39a36c666debecb3dba4be14',
        'boundaries':633,'all_boundary_rows_unchanged':True,
        'protected_rows':442,'all_forbidden_arrays_equal':True,'old_row411_equal':True,
        'row_order_and_duplicate_path_rows_preserved':True,'no_path_deduplication':True,
        'inspected_protected_rows':inspected_rows,'guard_changes':guard_changes,
        'provider_paths':45,'provider_scopes':288,
        'provider_scope_updates':provider_updates,'module_shape_updates':shape_updates,
        'all_scope_selectors_mounts_exports_unchanged':True,'all_attack_specs_unchanged':True,
        'actual_marker_locations':anchors,'ordinary_scope_updates':ordinary_updates,
        'ordinary_scopes':34,'ordinary_literals':17,'ordinary_28_boundary_slice_unchanged':True,
        'qa_files':64,'qa_methods':607,'all_607_method_bodies_byte_equal':True,
        'root_parent_count':48,'all_root_parent_order_and_workflow_bytes_unchanged':True,
        'existing_allowlist_bytes_preserved':True,'appended_allowlist_line':line.decode().rstrip('\n'),
        'source_roots_ignore_authority_and_privileged_inventory_unchanged':True,
        'full_gate_or_QA_method_executions':0,'Rust_or_H_calls':0,'source_tree_or_ref_writes':0,
        'qualification':False,
    }
    save('REGISTRATION_REFRESH_REVIEW.json', dump(report))
    rows = []
    patch = []
    for path in SEVEN:
        before = (HERE/'before'/path).read_bytes();after = (HERE/'after'/path).read_bytes()
        rows.append({'path':path,'mode':'100644','operation':'unchanged' if before==after else 'modify',
                     'before':pin(before),'after':pin(after)})
        if before != after:
            patch.extend(difflib.unified_diff(before.decode().splitlines(keepends=True),after.decode().splitlines(keepends=True),
                                            fromfile='a/'+path,tofile='b/'+path))
    save('FENCE_PATHS.json',dump(rows))
    save('SOURCE_DELTA.patch',''.join(patch).encode())
    print(json.dumps({'source_rows':rows,'changed_rows':len(guard_changes),
      'changed_marker_values':sum(len(r['replacements'])for r in guard_changes),
      'provider_changed_scopes':len(provider_updates),'provider_module_shapes_changed':len(shape_updates),
      'ordinary_changed_scopes':len(ordinary_updates),'all_607_methods_unchanged':True,
      'all_107_attacks_same_locations':True,'review':pin(dump(report))},indent=2))


if __name__=='__main__':
    main()
