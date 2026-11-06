#!/usr/bin/env python3
"""Read-only fixed-source and native13 fact binding; no product/native execution."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
TREE_PATH = 'hepta-audit-fifth/b11-acl-control-v2-publication/intended-full-tree.json'
N13 = 'architecture-audit/b11-pr4884-ci-20261105/terminal/probe-127639593751/'
OLD = 'architecture-audit/b11-delete-boundary-20261105/source/'
V3 = 'architecture-audit/b11-host-neither-observation-candidate-20261105/v3/source/'
PREFIX = 'codex-rs/windows-sandbox-rs/'
HEAD = 'daa21e7a6a9b19e74b61c6bbdc2c813f9fd35a42'
TREE = 'fbaf12d56a9702d927ae6f71cb9f3abc0cf31cae'
CHECKOUT = 'f8e97e161c7ad87bd1e242363901a0852170483c'

def digest(data):
    return dict(bytes=len(data), git_blob=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(), sha256=hashlib.sha256(data).hexdigest())

def read(path):
    return (ROOT / path).read_bytes()

def json_read(path):
    return json.loads(read(path))

tree_bytes = read(TREE_PATH)
tree = json.loads(tree_bytes)
assert tree['sha'] == TREE and not tree['truncated']
entries = {x['path']: x for x in tree['tree']}
assert len(entries) == len(tree['tree'])

# Rebuild every Git tree from its exact mode/path/object entries. The fixed
# root identity is independently bound by the already-frozen actual publication.
children = {}
for item in tree['tree']:
    parent, _, name = item['path'].rpartition('/')
    children.setdefault(parent, []).append((name, item))
for directory in sorted(children, key=lambda p: (p.count('/'), len(p)), reverse=True):
    items = sorted(children[directory], key=lambda x: (x[0] + ('/' if x[1]['type'] == 'tree' else '')).encode())
    payload = b''.join((item['mode'].lstrip('0')+' '+name).encode()+b'\0'+bytes.fromhex(item['sha']) for name, item in items)
    calculated = hashlib.sha1(b'tree '+str(len(payload)).encode()+b'\0'+payload).hexdigest()
    expected = TREE if not directory else entries[directory]['sha']
    assert calculated == expected, (directory, calculated, expected)

selected = {}
for relative in ['src/acl.rs', 'src/allow.rs', 'src/bin/command_runner/win.rs',
                 'src/identity.rs', 'src/setup.rs', 'src/spawn_prep.rs',
                 'src/unified_exec/backends/elevated.rs', 'src/unified_exec/backends/legacy.rs',
                 'src/unified_exec/mod.rs', 'src/unified_exec/tests.rs']:
    selected[PREFIX+relative] = OLD+PREFIX+relative
for relative in ['BUILD.bazel', 'Cargo.toml', 'src/delete_permission_matrix_tests.rs',
                 'src/desktop.rs', 'src/proc_thread_attr.rs', 'src/process.rs', 'src/token.rs',
                 'src/token_integrity_probe_support.rs', 'src/token_integrity_probe_tests.rs', 'src/winutil.rs']:
    selected[PREFIX+relative] = V3+PREFIX+relative
selected['codex-rs/utils/pty/src/win/job.rs'] = V3+'codex-rs/utils/pty/src/win/job.rs'
selected[PREFIX+'src/elevated/ipc_framed.rs'] = 'architecture-audit/b11-full-restricting-caller-20261105/source/'+PREFIX+'src/elevated/ipc_framed.rs'
for relative, local in [
    ('src/lib.rs','executed-lib.rs.source.txt'),
    ('src/token_tests.rs','executed-token-tests.rs.source.txt'),
    ('src/unified_exec/delete_permission_tests.rs','executed-delete-permission-tests.rs.source.txt'),
    ('src/acl_control_test_support.rs','executed-acl-control-helper.rs.source.txt'),
    ('src/token_neither_privilege_observation.rs','executed-observation-module.rs.source.txt'),
]:
    selected[PREFIX+relative] = N13+local
bindings = []
for repo_path, local_path in sorted(selected.items()):
    body = read(local_path)
    proof = digest(body)
    assert entries[repo_path]['type'] == 'blob'
    assert proof['git_blob'] == entries[repo_path]['sha'], repo_path
    bindings.append(dict(repository_path=repo_path, local_path=local_path, **proof, current_tree_leaf_equal=True))

token = read(selected[PREFIX+'src/token.rs']).decode()
assert 'let flags = DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED;' in token
strict_constructor = token.split('pub unsafe fn create_workspace_write_token_with_caps_from(',1)[1].split('\n}\n',1)[0]
assert 'RestrictingIdentity::Exclude' in strict_constructor
ipc = read(selected[PREFIX+'src/elevated/ipc_framed.rs']).decode()
message = ipc.split('pub enum Message {',1)[1].split('\n}',1)[0]
assert [line.strip().split(' ',1)[0] for line in message.splitlines() if line.strip()] == [
    'SpawnRequest','SpawnReady','Output','Stdin','CloseStdin','Resize','Exit','Error','Terminate']
legacy = read(selected[PREFIX+'src/unified_exec/backends/legacy.rs']).decode()
capture = read(selected[PREFIX+'src/lib.rs']).decode()
for source in [legacy, capture]:
    assert 'has_full_disk_read_access()' in source and 'preserve_descendants()' in source

result_bytes = read(N13+'VERIFICATION.json')
assert digest(result_bytes)['git_blob'] == 'af10ff6664344d3d8825dbdfc6ef3c6646a59a61'
result = json.loads(result_bytes)
assert result['head'] == HEAD and result['actual_checkout'] == CHECKOUT and result['actual_tree'] == TREE
assert (result['whole']['passed'],result['whole']['failed'],result['whole']['ignored']) == (147,7,2)
control = result['new_nonprivileged_host_controls']
assert control['new_host_preconditions_reached_and_passed_before_original_strict_failures'] is True
assert control['all_four_matrices_actual_DACL_bytes_equal_by_route_and_kind'] is True
assert control['strict_Rust_actual_restricting_membership'] == [True,True,False,False]
assert control['production_token_or_security_flags_changed'] is False
assert control['arbitrary_descendants_cancellation_loader_or_full_product_isolation_qualified'] is False
for name, record in control['physical_after_release_records'].items():
    strict = name in ['after-revert','legacy-child-done']
    assert len(record['outcomes']) == 4
    for row in record['outcomes']:
        deleted = row['route'] in (['ParentOnly','Both'] if strict else ['TargetOnly','ParentOnly','Both'])
        assert row['file_deleted'] is deleted and row['directory_deleted'] is deleted

raw_path = N13+'members/bazel-execution-logs/failed-test-logs/invocation-b0lnxmpu/targets/0000/test.log'
raw = read(raw_path).decode()
for location in ['token_tests.rs:434:5','token_tests.rs:573:5','delete_permission_tests.rs:100:9','tests.rs:62:10']:
    assert location in raw, location
assert len(result['whole']['failures']) == 7
assert sum(x['classification']=='downstream_poisoned_test_lock' for x in result['whole']['failures']) == 4

facts = dict(schema='hepta-b11-native13-product-feasibility-facts-v1',
    authority=dict(head=HEAD,checkout=CHECKOUT,tree=TREE,run=result['run'],job=result['job']),
    whole={k:result['whole'][k] for k in ['passed','failed','ignored','failures']},
    complete_physical_matrix_records=control['physical_after_release_records'],
    exact_DACL_bytes_equal_across_four_matrices=True,
    membership=control['strict_Rust_actual_restricting_membership'],
    positive_read_and_inside_IO_basis=control['strict_ambient_reads_and_allowed_deletions_basis'],
    raw_JSON_limits=dict(new_control=control['unparsed_original_JSON_records'],
                        Rust_actual_token_JSON_independently_parsed=control['Rust_effective_token_entire_original_JSON_independently_parsed']),
    production_flags_changed=False,all_descendants_loader_or_product_isolation_qualified=False,
    full_native13_result=dict(local_path=N13+'VERIFICATION.json',**digest(result_bytes)),
    complete_original_target_log=dict(local_path=raw_path,**digest(read(raw_path))),
    conclusion='NO_QUALIFIED_LOCAL_PRODUCT_FIX_IDENTIFIED_IN_CURRENT_INTERFACES; B11_OPEN',
    exclusions=['no new native','no ref changes','no product or test changes','no driver or new platform plan','no private Windows kernel algorithm claim'])
source_bindings = dict(schema='hepta-fixed-current-source-bindings-v1',head=HEAD,checkout=CHECKOUT,tree=TREE,
    complete_tree=dict(local_path=TREE_PATH,**digest(tree_bytes),all_tree_nodes_rebuilt=True),
    selected_complete_file_count=len(bindings),selected_files=bindings,
    binding_scope='Complete file bytes are checked; prose review focuses on the cited factory/caller/lifetime functions, not every unrelated line.')
for filename, value in [('MECHANISM_FACTS.json',facts),('SOURCE_BINDINGS.json',source_bindings)]:
    output = (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode()
    path = HERE/filename
    if path.exists():
        assert path.read_bytes()==output, filename
    else:
        path.write_bytes(output)
print(json.dumps(dict(schema='hepta-b11-feasibility-offline-verification-v1',result='PASS_FIXED_EVIDENCE_BINDING_ONLY',
    selected_source_files=len(bindings),tree=TREE,whole=[147,7,2],physical_matrix_count=4,
    files={name:digest((HERE/name).read_bytes()) for name in ['MECHANISM_FACTS.json','SOURCE_BINDINGS.json']},
    B11='OPEN',native_started=0,ref_writes=0),ensure_ascii=False,indent=2))
