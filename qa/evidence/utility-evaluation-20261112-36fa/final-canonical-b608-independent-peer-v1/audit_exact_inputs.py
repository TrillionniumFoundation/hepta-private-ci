#!/usr/bin/env python3
"""Pure captured-byte/schema audit. Never invokes bootstrap, preflight or main."""
import ast
import base64
import copy
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IN = ROOT / 'inputs'
PREP = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-preparation-v1')
LAUNCH = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-launch-v1/execution-candidate-v1')
SOURCE = Path('/tmp/hepta-36fa-a489-final-nonrust-exact-recovery-v1/final.inventory.exact_recovered.json')
RUNTIME = Path('/tmp/hepta-36fa-final-nonrust-50f-runtime-archive-v1/frozen')


def ident(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}


def typed(kind, raw):
    return hashlib.sha1(kind.encode()+b' '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def nodup(pairs):
    out = {}
    for key, value in pairs:
        assert key not in out
        out[key] = value
    return out


def parse(raw):
    return json.loads(raw, object_pairs_hook=nodup)


def enc(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))+'\n').encode()


def check_pin(raw, pin):
    assert ident(raw) == {k: pin[k] for k in ('bytes', 'sha256', 'git_blob')}


def funcs(source):
    return {n.name: ast.get_source_segment(source, n) for n in ast.walk(ast.parse(source))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def assignment(source, name):
    found = [n for n in ast.parse(source).body if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    assert len(found) == 1
    return found[0], ast.get_source_segment(source, found[0])


def decode_representation(member, nested_decoded=False):
    packed = b''
    for part in member['parts']:
        raw = (IN / part['name']).read_bytes()
        check_pin(raw, part)
        assert len(raw) <= 512000 and part['decoded_offset'] == len(packed)
        block = base64.b64decode(raw.strip(), validate=True)
        if nested_decoded:
            check_pin(block, part['decoded'])
        else:
            assert len(block) == part['decoded_bytes']
            assert hashlib.sha256(block).hexdigest() == part['decoded_sha256']
        packed += block
    check_pin(packed, member['gzip'])
    raw = gzip.decompress(packed)
    check_pin(raw, member['raw'])
    return raw


def tree_graph(rows, physical):
    trie = {}
    for row in rows:
        path = row['path']; pieces = path.split('/')
        assert not path.startswith('/') and all(x not in ('', '.', '..', '.git') for x in pieces)
        node = trie
        for piece in pieces[:-1]:
            node = node.setdefault(piece, {})
            assert isinstance(node, dict)
        assert pieces[-1] not in node
        mode = ('120000' if row['kind'] == 'symlink' else
                '100755' if row['permissions'] & 0o111 else '100644') if physical else row['index_mode']
        sha = row['working_blob'] if physical else row['index_blob']
        node[pieces[-1]] = (mode, sha)
    trees = {}; bodies = {}
    def visit(node, prefix):
        raw = b''
        for name in sorted(node, key=lambda n: (n + ('/' if isinstance(node[n], dict) else '')).encode()):
            value = node[name]
            if isinstance(value, dict):
                mode = '40000'; sha = visit(value, prefix+'/'+name if prefix else name)
            else:
                mode, sha = value
            raw += mode.encode()+b' '+name.encode()+b'\0'+bytes.fromhex(sha)
        sha = typed('tree', raw); trees[prefix] = sha; bodies[sha] = raw
        return sha
    return visit(trie, ''), trees, bodies


def main():
    fetched = parse((ROOT/'FETCHED_INPUT_INDEX.json').read_bytes())
    for row in fetched:
        raw = (IN/row['name']).read_bytes()
        assert ident(raw)['git_blob'] == row['git_blob']
        sdk = parse((ROOT/'github'/(row['name']+'.GET.original.json')).read_bytes())['structuredContent']
        sdk = sdk.get('structuredContent', sdk)
        assert sdk['content'].encode() == raw
    driver = (IN/'driver.HOLD.py').read_text(); original = (IN/'ORIGINAL_765ADA.py').read_text()
    substitutions = parse((PREP/'EXACT_CONSTANT_SUBSTITUTIONS.json').read_bytes())['substitutions']
    inverse = driver
    for change in substitutions:
        assert inverse.count(change['after']) == 1
        inverse = inverse.replace(change['after'], change['before'])
    assert len(substitutions) == 7 and inverse == original
    assert funcs(driver) == funcs(original) and len(funcs(driver)) == 47
    assert len([n for n in ast.parse(driver).body if isinstance(n, ast.FunctionDef)]) == 46
    bootstrap = (IN/'BOOTSTRAP.candidate.py').read_text(); oldboot = (IN/'ORIGINAL_BOOTSTRAP.py').read_text()
    inverse = bootstrap
    for name in ('BASE', 'PINS'):
        newspan = assignment(bootstrap, name)[1]; oldspan = assignment(oldboot, name)[1]
        assert inverse.count(newspan) == 1; inverse = inverse.replace(newspan, oldspan)
    assert inverse == oldboot and funcs(bootstrap) == funcs(oldboot) and len(funcs(bootstrap)) == 5
    assert 'flock' not in bootstrap and 'fcntl' not in bootstrap
    pins = ast.literal_eval(assignment(bootstrap, 'PINS')[0].value)
    assert set(pins) == {'driver.py', 'FINAL_FORMAT_NORMAL.original.json', 'CANONICAL_PACKET.json', 'APPROVED_CONFIG.json'}
    roots = {x['name']: decode_representation(x) for x in parse((IN/'LOSSLESS_REPRESENTATIONS.json').read_bytes())}
    launch_manifest = parse((IN/'LAUNCH_ENCODING_MANIFEST.json').read_bytes())
    launch = {x['name']: decode_representation(x, True) for x in launch_manifest['members']}
    for name, raw in launch.items():
        assert raw == (LAUNCH/name).read_bytes()
    request_raw = launch['ACTUAL_PROCESS_INPUT.candidate.json']; request = parse(request_raw)
    stdin_raw = launch['ACTUAL_STDIN.candidate.json']; stdin = parse(stdin_raw)
    assert ident(request_raw)['git_blob'] == 'fd655e0dea612e9dd13d4026c11d01b811c8fd8d'
    assert len(request_raw) == 940279 < 1048576 and len(stdin_raw) == 934139 < 1048576
    assert set(request) == {'host','cwd','executable','args','stdin','timeout_seconds','idempotency_key'}
    assert request['host'] == 'desktop' and request['cwd'] == '/home/qian-qi'
    assert request['executable'] == '/usr/bin/python3' and request['args'] == ['-B','-c',bootstrap]
    assert request['stdin'].encode() == stdin_raw and request['timeout_seconds'] == 900
    assert request['idempotency_key'] == 'hepta-utility-36fa-provider-coordinator-a489-final-canonical-alignment-v1'
    assert set(stdin) == {'format','files'} and stdin['format'] == 'hepta-final-canonical-alignment-bootstrap-v1'
    assert set(stdin['files']) == set(pins)
    decoded = {}
    for name, text in stdin['files'].items():
        raw = base64.b64decode(text, validate=True)
        if name == 'CANONICAL_PACKET.json': raw = gzip.decompress(raw)
        check_pin(raw, pins[name]); decoded[name] = raw
    assert decoded['driver.py'] == driver.encode()
    assert decoded['APPROVED_CONFIG.json'] == (IN/'APPROVED_CONFIG.candidate.json').read_bytes()
    assert decoded['CANONICAL_PACKET.json'] == roots['CANONICAL_PACKET.json']
    assert decoded['FINAL_FORMAT_NORMAL.original.json'] == (RUNTIME/'STATUS_02.original.json').read_bytes()
    cfg = parse(decoded['APPROVED_CONFIG.json']); packet = parse(decoded['CANONICAL_PACKET.json'])
    assert cfg['action_seconds'] == 600 and cfg['record_seconds'] == 180 and cfg['outer_seconds'] == 900
    assert cfg['not_an_execution_approval'] is True and cfg['qualification'] is False
    for k in ('physical_source_writes_authorized','dependency_installation_authorized','cargo_or_formatter_authorized','test_commands_authorized','remote_ref_updates_authorized'):
        assert cfg[k] is False
    assert cfg['status'] == 'ROOT_APPROVED_FOR_ONE_CANONICAL_ALIGNMENT' and cfg['root_execution_approved'] is True
    assert packet['before'] == {'commit':cfg['before_commit'],'tree':cfg['before_tree'],'parents':cfg['before_parents'],'inventory':cfg['before_inventory'],'git_state':cfg['expected_before_git_state']}
    assert packet['after'] == {'commit':cfg['after_commit'],'tree':cfg['after_tree'],'parents':cfg['after_parents'],'inventory':cfg['after_inventory']}
    assert cfg['source_repo'] == packet['source_repo'] == '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
    assert cfg['complete_leaf_count'] == packet['complete_leaf_count'] == 15243
    assert cfg['after_parents'] == [cfg['before_commit']] and cfg['before_parents'] == ['cc57c7198db6293ccca562253c42fffbe2a04633']
    before_raw = SOURCE.read_bytes(); check_pin(before_raw, cfg['before_inventory']); before = parse(before_raw)
    after_raw = roots['EXPECTED_AFTER_INVENTORY.json']; check_pin(after_raw, cfg['after_inventory']); after = parse(after_raw)
    assert before['source']['head'] == cfg['before_commit'] and before['source']['tree'] == cfg['before_tree']
    assert before['tracked_entries'] == before['filesystem_entries'] == len(before['files']) == 15243
    projected = copy.deepcopy(before)
    projected['source'] = {'head':cfg['after_commit'],'tree':cfg['after_tree'],'status':''}
    for row in projected['files']:
        assert row['stable'] is True
        row['index_blob'] = row['working_blob']
        row['index_mode'] = '120000' if row['kind'] == 'symlink' else '100755' if row['permissions'] & 0o111 else '100644'
        row['matches_index'] = True
    assert enc(projected) == after_raw and projected == after
    oldroot, oldtrees, _ = tree_graph(before['files'], False)
    newroot, newtrees, treebodies = tree_graph(before['files'], True)
    assert oldroot == cfg['before_tree'] and newroot == cfg['after_tree']
    changes = [r for r, a in zip(before['files'], after['files']) if (r['index_blob'],r['index_mode']) != (a['index_blob'],a['index_mode'])]
    assert len(changes) == 21
    objects = {}; summaries = []
    for obj in packet['objects']:
        assert set(obj) == {'type','sha','bytes','sha256','raw_base64'}
        raw = base64.b64decode(obj['raw_base64'], validate=True)
        assert len(raw) == obj['bytes'] and hashlib.sha256(raw).hexdigest() == obj['sha256']
        assert typed(obj['type'], raw) == obj['sha'] and obj['sha'] not in objects
        objects[obj['sha']] = (obj['type'], raw)
        summaries.append({k:v for k,v in obj.items() if k != 'raw_base64'})
    assert Counter(kind for kind, _ in objects.values()) == {'blob':21,'tree':7,'commit':1}
    assert len(objects) == cfg['canonical_object_count'] == 29
    expected_blobs = {r['working_blob'] for r in changes}
    expected_trees = {sha for path,sha in newtrees.items() if oldtrees.get(path) != sha}
    assert set(objects) == expected_blobs | expected_trees | {cfg['after_commit']}
    for row in changes:
        kind,raw = objects[row['working_blob']]
        assert kind == 'blob' and len(raw) == row['bytes'] and hashlib.sha256(raw).hexdigest() == row['sha256']
    for sha in expected_trees: assert objects[sha] == ('tree',treebodies[sha])
    kind, commitraw = objects[cfg['after_commit']]
    lines = commitraw.split(b'\n\n',1)[0].splitlines()
    assert kind == 'commit' and len(commitraw) == 775
    assert lines[0] == ('tree '+newroot).encode()
    assert [x[7:].decode() for x in lines if x.startswith(b'parent ')] == cfg['after_parents']
    assert ident(commitraw)['git_blob'] == 'bcef892eaa1ae8bc7e91fb09760b7ff86141900f'
    # Run only the original pure final-format predicate with captured in-memory I/O.
    allowed = {'check','sha256','oid','nodup','parse','pin','parse_supervisor','validate_final_format'}
    selected = [n for n in ast.parse(driver).body if isinstance(n,ast.FunctionDef) and n.name in allowed]
    assert {n.name for n in selected} == allowed
    namespace = {'json':json,'hashlib':hashlib,'cfg':cfg,'REPO':Path(cfg['source_repo']),
                 'OLD':cfg['before_commit'],'OLD_TREE':cfg['before_tree'],'OLD_PARENTS':cfg['before_parents'],
                 'NEW_TREE':cfg['after_tree'],'LEAVES':15243,'result':{}}
    exec(compile(ast.Module(body=selected,type_ignores=[]),'captured-pure-final-format-predicate','exec'),namespace)
    captured = {
        cfg['final_format']['result_path']:(RUNTIME/'RESULT.json').read_bytes(),
        cfg['final_format']['supervisor_path']:decoded['FINAL_FORMAT_NORMAL.original.json'],
        cfg['final_format']['git_state_path']:(RUNTIME/'final.git-state.json').read_bytes(),
    }
    reads = []; writes = {}
    def read_input(path, pin):
        raw = captured[str(path)]; check_pin(raw,pin); reads.append(str(path)); return raw
    def write(name, raw):
        assert name not in writes; writes[name] = ident(raw); return writes[name]
    namespace.update(read_input=read_input,write=write)
    namespace['validate_final_format']()
    assert len(reads) == 3 and len(writes) == 3
    output = {
        'format':'hepta-b608-canonical-exact-input-independent-dataflow-v1',
        'status':'STATIC_EXACT_INPUTS_AND_CAPTURED_PREDICATE_CONSISTENT_NOT_EXECUTED',
        'independent_full_GET_inputs':fetched,
        'driver':ident(driver.encode()),'driver_seven_constant_inverse_complete_equal':True,
        'unchanged_driver_top_functions':46,'unchanged_driver_all_functions':47,
        'bootstrap':ident(bootstrap.encode()),'bootstrap_only_BASE_PINS_inverse_complete_equal':True,
        'unchanged_bootstrap_all_functions':5,'bootstrap_acquires_no_EX':True,
        'request':ident(request_raw),'stdin':ident(stdin_raw),'request_exact_keys':sorted(request),
        'request_no_environment_field':True,'outer_seconds':900,'action_seconds':600,'record_seconds':180,
        'decoded_inputs':{n:ident(b) for n,b in decoded.items()},
        'actual_before_inventory':ident(before_raw),'projected_after_inventory_not_observed':ident(after_raw),
        'all_15243_physical_rows_unchanged_by_projection':True,
        'independent_old_index_merkle':oldroot,'independent_physical_merkle':newroot,
        'changed_index_entries':len(changes),'changed_paths':[r['path'] for r in changes],
        'objects':summaries,'complete_packet_object_membership_exact':True,
        'authentic_commit_storage_identity':ident(commitraw),'authentic_commit_typed_id':cfg['after_commit'],
        'sole_parent':cfg['before_commit'],'captured_actual50f_original_pure_predicate_completed':True,
        'predicate_input_paths':reads,'predicate_writes_in_memory_only':writes,
        'new_H_calls':0,'input_module_import_or_main_or_preflight_calls':0,
        'source_index_HEAD_ref_writes':0,'qualification':False,
    }
    raw=(json.dumps(output,indent=2)+'\n').encode()
    with (ROOT/'EXACT_DATAFLOW_REVIEW.json').open('xb') as f:f.write(raw)
    print(json.dumps(ident(raw)))


if __name__ == '__main__':
    main()
