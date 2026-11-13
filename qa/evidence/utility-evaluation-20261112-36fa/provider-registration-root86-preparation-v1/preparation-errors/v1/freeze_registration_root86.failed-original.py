#!/usr/bin/env python3
"""Freeze exact registration source bytes; no QA method, full scan or main gate."""
from pathlib import Path
import ast
import base64
import datetime
import difflib
import gzip
import hashlib
import importlib.util
import json
import re
import sys
import tomllib

sys.dont_write_bytecode = True
BASE = Path('/tmp/hepta-36fa-provider-registration-rebuilt-v3')
BEFORE = BASE / 'before'
VIEW = BASE / 'view-root86'
CANDIDATE = BASE / 'candidate-registration-root86-final'
OUT = Path('/tmp/hepta-36fa-provider-registration-root86-frozen-v1')
QA = 'qa/b4-no-bypass/'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def dump(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode()

def save(name, raw):
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    return {'local_path': str(path), **pin(raw)}

def definitions(text):
    result = {}
    for item in ast.parse(text).body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            result[(None, item.name)] = ast.get_source_segment(text, item)
        elif isinstance(item, ast.ClassDef):
            for function in item.body:
                if isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    result[(item.name, function.name)] = ast.get_source_segment(text, function)
    return result

def raw_protected(text):
    starts = [m.start() for m in re.finditer(r'(?m)^\[\[protected_file\]\]\s*$', text)]
    return [text[start:end] for start, end in zip(starts, starts[1:] + [len(text)])]

def main():
    OUT.mkdir(exist_ok=False)
    original_text = (BEFORE / 'CALLERS.toml').read_text()
    proposed_text = (CANDIDATE / 'CALLERS.toml').read_text()
    original, proposed = map(tomllib.loads, (original_text, proposed_text))
    assert len(original['boundary']) == 569 and len(proposed['boundary']) == 621
    assert len(original['protected_file']) == 422 and len(proposed['protected_file']) == 437
    changed_edges = []
    for index, old in enumerate(original['boundary']):
        new = proposed['boundary'][index]
        assert old['id'] == new['id']
        assert {k:v for k,v in old.items() if k != 'product_callers'} == {k:v for k,v in new.items() if k != 'product_callers'}
        assert set(old['product_callers']) <= set(new['product_callers'])
        if old != new:
            changed_edges.append(index)
    assert len(changed_edges) == 17
    for key in original:
        if key not in ('boundary', 'protected_file', 'privileged_inventory'):
            assert original[key] == proposed[key], key
    assert original['privileged_inventory']['required_ids'] == proposed['privileged_inventory']['required_ids'][:569]
    assert proposed['privileged_inventory']['required_ids'] == [r['id'] for r in proposed['boundary']]
    old_blocks, new_blocks = map(raw_protected, (original_text, proposed_text))
    assert len(old_blocks) == 422 and len(new_blocks) == 437
    changed_protected = []
    for index, old in enumerate(original['protected_file']):
        new = proposed['protected_file'][index]
        assert old['path'] == new['path']
        assert old['forbidden'] == new['forbidden']
        assert new['required'][:len(old['required'])] == old['required']
        if old_blocks[index] != new_blocks[index]:
            changed_protected.append(index)
    assert len(changed_protected) == 21
    assert old_blocks[411] == new_blocks[411]
    remote = original['protected_file'][411]['path']
    assert (VIEW / remote).read_bytes() == (BEFORE / remote).read_bytes()

    inputs = json.loads((BASE / 'SOURCE_VIEW_ROOT86_INPUTS.json').read_text())
    assert inputs['root_map_git_blob'] == '3f7d40d4933669da33d2aef3491efb431c5771ae'
    assert pin((BASE / 'ROOT_86_MAP.original.json').read_bytes()) == inputs['root_map_pin']
    for row in inputs['rows']:
        observed = pin((VIEW / row['path']).read_bytes())
        assert all(observed[key] == row[key] for key in observed), row['path']
    assert len(inputs['rows']) == 88

    allowlist = BEFORE / '.github/blob-size-allowlist.txt'
    allowance_before = allowlist.read_bytes()
    assert pin(allowance_before)['git_blob'] == 'c3257329caece666950db2041a8e9f47acf5c129'
    allowance_line = ('sha256:' + pin(proposed_text.encode())['sha256'] + ' CALLERS.toml\n').encode()
    assert allowance_line not in allowance_before
    allowance_after = allowance_before + allowance_line
    target = CANDIDATE / '.github/blob-size-allowlist.txt'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert target.read_bytes() == allowance_after
    else:
        with target.open('xb') as stream:
            stream.write(allowance_after)

    old_methods = unchanged_methods = 0
    changed_methods, changed_definitions = [], []
    original_qa = sorted((BEFORE / QA).glob('test_*.py'))
    assert len(original_qa) == 63
    for file in original_qa:
        relative = file.relative_to(BEFORE).as_posix()
        initial = (VIEW / relative) if (VIEW / relative).exists() else file
        final = (CANDIDATE / relative) if (CANDIDATE / relative).exists() else initial
        left, right = initial.read_text(), final.read_text()
        old_defs, new_defs = definitions(left), definitions(right)
        assert old_defs.keys() == new_defs.keys(), relative
        for key, old_def in old_defs.items():
            new_def = new_defs[key]
            if old_def != new_def:
                changed_definitions.append({'path': relative, 'class': key[0], 'method': key[1]})
            if key[0] is not None and key[1].startswith('test_'):
                old_methods += 1
                if old_def == new_def:
                    unchanged_methods += 1
                else:
                    old_asserts = [n.func.attr for n in ast.walk(ast.parse(old_def)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith('assert')]
                    new_asserts = [n.func.attr for n in ast.walk(ast.parse(new_def)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith('assert')]
                    assert old_asserts == new_asserts
                    changed_methods.append({'path': relative, 'class': key[0], 'method': key[1],
                                            'before': old_def, 'after': new_def,
                                            'assertion_call_names_unchanged': old_asserts})
    assert old_methods == 590 and unchanged_methods == 587
    assert len(changed_definitions) == len(changed_methods) == 3
    old_review = json.loads((CANDIDATE / 'OLD_QA_PRESERVATION_REVIEW.json').read_text())
    assert [{k:r[k] for k in ('path','class','method','before','after')} for r in changed_methods] == old_review['changed_methods']
    assert len(old_review['boundary_constant_updates']) == 26
    assert len(old_review['scope_hash_updates']) == 5

    new_qa_path = QA + 'test_resident_provider_local_read_source_closure.py'
    new_qa = (CANDIDATE / new_qa_path).read_text()
    new_ast = ast.parse(new_qa)
    methods = [n.name for n in ast.walk(new_ast) if isinstance(n, ast.FunctionDef) and n.name.startswith('test_')]
    assert len(methods) == 14
    contract_path = QA + 'PROVIDER_LOCAL_READ_SOURCE_CONTRACT.json'
    contract_bytes = (CANDIDATE / contract_path).read_bytes()
    contract = json.loads(contract_bytes)
    assert pin(contract_bytes)['sha256'] in new_qa
    assert len(contract['scopes']) == 41
    assert sum(map(len,contract['scopes'].values())) == 264
    assert sum(map(len,contract['attacks'].values())) == 83
    assert len(contract['new_boundaries']) == 52 and contract['new_boundaries'] == proposed['boundary'][569:]
    boundary_calls = [n for n in ast.walk(new_ast) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr == '_verify_boundary']
    assert len(boundary_calls) == 3 and all(len(n.args) == 4 and not n.keywords for n in boundary_calls)
    assert 'for path in PROOF._source_files(ROOT, roots)' in new_qa
    assert 'for path in CONTRACT["scopes"]:' in new_qa
    assert 'fields_by_receiver_type' not in new_qa
    assert '"tail": " ".join(code[cursor:].split())' in new_qa
    assert 'attributes.append(original[begin:stop + 1])' in new_qa

    spec = importlib.util.spec_from_file_location('final_registration_original_predicates', BEFORE / 'scripts/verify_hepta_callers.py')
    proof = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = proof
    spec.loader.exec_module(proof)
    checked = []
    for index, row in enumerate(proposed['protected_file']):
        path = VIEW / row['path']
        if not path.exists():
            continue
        text = path.read_text()
        assert all(marker in text for marker in row['required']), (index,'required')
        code = proof._strip_cfg_test_items(proof._strip_rust_non_code(text))
        proof._verify_required_order(row, code, row['path'])
        proof._verify_function_order(row, code, row['path'], text)
        for marker in row['forbidden']:
            pattern = re.escape(marker)
            if marker and (marker[0].isalnum() or marker[0] == '_'):
                pattern = r'(?<!\w)' + pattern
            if marker and (marker[-1].isalnum() or marker[-1] == '_'):
                pattern += r'(?!\w)'
            assert not re.search(pattern,code),(index,'forbidden',marker)
        checked.append(index)
    assert len(checked) == 42

    source_paths = ['CALLERS.toml', '.github/blob-size-allowlist.txt']
    source_paths += sorted(p.relative_to(CANDIDATE).as_posix() for p in (CANDIDATE / QA).iterdir() if p.is_file())
    assert len(source_paths) == 19
    changes, patch = [], []
    for relative in source_paths:
        old_path = VIEW / relative if (VIEW / relative).exists() else BEFORE / relative
        before = old_path.read_bytes() if old_path.exists() else None
        after = (CANDIDATE / relative).read_bytes()
        assert before != after,relative
        if relative != 'CALLERS.toml':
            assert len(after) < 500000,relative
        changes.append({'path':relative,'mode':'100644',
                        'before':pin(before) if before is not None else None,'after':pin(after),
                        'before_content':before.decode() if before is not None else None,
                        'after_content':after.decode(),
                        'preimage_scope':'root86 prepared input' if (VIEW / relative).exists() else 'cc57 canonical or new'})
        patch.extend(difflib.unified_diff((before or b'').decode().splitlines(True),after.decode().splitlines(True),
                                        fromfile='a/'+relative if before is not None else '/dev/null',tofile='b/'+relative))
    report = {
        'status':'PREPARATION_HOLD_STATIC_BYTE_AND_SCOPE_CONSTRUCTION_ONLY',
        'frozen_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'root86_map':inputs['root_map_pin'],'canonical_source_commit':'cc57c7198db6293ccca562253c42fffbe2a04633',
        'canonical_source_tree':'b7b357c07b5539769a068c6b9b009629f5612d1e',
        'coverage_view':{'rust_paths':86,'new_rust_paths':43,'changed_original_rust_paths':42,'restored_original_rust_paths':1,'prepared_non_rust_paths':2,'removed_old_helper_paths':1},
        'boundaries':{'before':569,'after':621,'old_product_caller_arrays_appended':changed_edges,'new':52,'all_other_old_boundary_fields_equal':True},
        'protected':{'before':422,'after':437,'old_raw_rows_identical':401,'changed_old_row_indices':changed_protected,'new':15,'all_422_forbidden_arrays_equal':True,'all_old_raw_required_prefixes_equal':True,'row411_entire_block_and_source_equal':True,'row411_is_not_deduplicated_by_path':True},
        'old_qa':{'files':63,'methods':590,'method_text_unchanged':587,'changed_methods':changed_methods,'all_other_function_definitions_unchanged':True,'methods_added_or_removed':0,'constant_updates':26,'scope_hash_updates':5,'original_28_boundary_slice':'[541:569]'},
        'new_qa':{'methods':methods,'scope_paths':41,'scopes':264,'deletion_specs':83,'all_scope_paths_on_default_method':True,'complete_original_source_collector_and_four_argument_calls':True,'no_verdict_or_field_cache_added':True,'fixed_root_module_imports_declarations_attributes_and_tail':True},
        'partial_scope_construction':{'checked_rows':checked,'errors':[],'original_marker_functions_used':True,'full_gate_executed':False},
        'allowlist':{'before':pin(allowance_before),'after':pin(allowance_after),'single_appended_line':allowance_line.decode()},
        'source_changes':[{k:v for k,v in row.items() if k not in ('before_content','after_content')} for row in changes],
        'unchanged_controls':{str(p.relative_to(BEFORE)):pin(p.read_bytes()) for p in sorted((BEFORE/'scripts').glob('*.py'))},
        'important_limits':['Only the fixed 86-path overlay was scanned for typed call edges; the complete repository has not been scanned.','No QA method, unittest runner, full source gate, formatter, Rust compiler or behavioral test was run.','Full-body markers and literal scopes are prepared against unformatted source and require exact rebinding after actual formatting.','The pure ledger codec is not registered as an authority boundary merely because its codec functions are public.','New root handoff protection omits File::open from its new forbidden list because the fixed real-peer check reads boot_id and process stat; no original forbidden entry was removed.','This package does not activate source or change any Git ref, tree, commit, PR or authorization.'],
        'qa_methods_executed':0,'full_source_scans':0,'formatter_runs':0,'rust_compiles_or_tests':0,'source_or_refs_changed':False,
    }
    packet = {'format':'hepta-source-registration-proposal-v1','status':'PREPARATION_HOLD_NOT_QUALIFIED',
              'base_source_commit':report['canonical_source_commit'],'base_source_tree':report['canonical_source_tree'],
              'required_overlay_map':inputs['root_map_pin'],'source_changes':changes,
              'qa_methods_executed':0,'full_source_scans':0,'formatter_runs':0,'rust_compiles_or_tests':0,
              'notes':'Preimages bind canonical files except the explicitly prepared root QA preimage from root86. Final formatting and complete original gates remain required.'}
    records = {}
    records['SOURCE_PACKET.json'] = save('SOURCE_PACKET.json',dump(packet))
    records['EXACT_SOURCE_DELTA.patch'] = save('EXACT_SOURCE_DELTA.patch',''.join(patch).encode())
    records['REVIEW.json'] = save('REVIEW.json',dump(report))
    for name in ('BOUNDARY_REVIEW.json','PROTECTED_REVIEW.json','SOURCE_SCOPE_INPUTS.json','OLD_QA_PRESERVATION_REVIEW.json','QA_CONSTRUCTION_REVIEW.json','BUILD_RESULT.json'):
        records[name] = save(name,(CANDIDATE/name).read_bytes())
    for name in ('SOURCE_VIEW_ROOT86_INPUTS.json','ROOT_86_MAP.original.json','OVERLAY_CALL_EDGE_INSPECTION_ROOT86.json','NEW_BOUNDARY_PREPARATION_ROOT86.json','build_registration_candidate_root86.py','build_qa_candidate_root86.py','provider_qa.template.py','freeze_registration_root86.py'):
        records[name] = save(name,(BASE/name).read_bytes())
    encoded = []
    for name, record in list(records.items()):
        if record['bytes'] <= 450000:
            continue
        raw = (OUT/name).read_bytes()
        compressed = gzip.compress(raw, compresslevel=9, mtime=0)
        gzname=name+'.gz'
        save(gzname,compressed)
        parts=[]
        for index,start in enumerate(range(0,len(compressed),240000),1):
            payload=compressed[start:start+240000]
            partname=gzname+f'.part-{index:03}.b64'
            part=base64.b64encode(payload)+b'\n'
            parts.append({'name':partname,'encoded':save(partname,part),'decoded':pin(payload)})
        assert gzip.decompress(b''.join(base64.b64decode((OUT/p['name']).read_bytes(),validate=False) for p in parts)) == raw
        encoded.append({'raw_name':name,'raw':pin(raw),'gzip':pin(compressed),'parts':parts,'claim':'lossless encoding of this prepared local artifact, not a native observation'})
    records['ENCODING_MANIFEST.json']=save('ENCODING_MANIFEST.json',dump({'format':'hepta-prepared-evidence-lossless-v1','items':encoded}))
    manifest={'status':'PREPARATION_HOLD_STATIC_ONLY','root86_map':inputs['root_map_pin'],
              'packet':records['SOURCE_PACKET.json'],'source_path_count':len(changes),
              'source_after_objects':[{k:v for k,v in row.items() if k in ('path','mode','before','after','preimage_scope')} for row in changes],
              'artifacts':records,'readback_state_at_creation':'Git upload/readback will be recorded separately; these are computed local identities.',
              'no_gate_execution':True,'no_source_or_refs_updated':True}
    manifest_pin=save('MANIFEST.json',dump(manifest))
    print(json.dumps({'directory':str(OUT),'packet':records['SOURCE_PACKET.json'],'manifest':manifest_pin,'review':records['REVIEW.json'],'changes':len(changes),'encoded_large_items':len(encoded),'no_qa_methods_or_gates_executed':True},indent=2))

if __name__ == '__main__':
    main()
