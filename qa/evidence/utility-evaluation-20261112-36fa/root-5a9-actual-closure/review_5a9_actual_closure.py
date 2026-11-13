"""Root offline audit of the one approved canonical alignment job.

This reads captured originals only. It invokes no producer, H, Git command,
admission, formatter, source gate, or test. Python preserves integer ns fields.
"""
import base64
import gzip
import hashlib
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

R = Path('/tmp/hepta-36fa-current-workspace-reconstruction-v3')
K = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-runtime-v1')
I = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1')
D = Path('/tmp/hepta-36fa-coordinator-a489-final-canonical-inputs-v1')
CONTROL = '/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-final-canonical-alignment-v1'
REPO = '/home/qian-qi/hepta-utility-36fa-provider-coordinator-a489-isolated-v1'
JOB = '1a1d4cbd33e-392-5a9'
OLD = 'd25675445c39f76db69a7bd8e71a1a72e1cd5b9f'
NEW = 'b6084394a4a38ab495c16eaba09e879f04a96f8e'
OLD_TREE = 'a489b394666b8141840275128a780605b024cde0'
NEW_TREE = '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638'

def oid(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob': oid('blob', raw)}

def identity(path):
    return pin(Path(path).read_bytes())

def read(path):
    return json.loads(Path(path).read_bytes())

def unwrap(path):
    wrapper = read(path)
    assert not wrapper.get('isError'), str(path)
    texts = [x['text'] for x in wrapper['content'] if x['type'] == 'text']
    assert len(texts) == 1, str(path)
    return json.loads(texts[0])

def same_pin(raw, record, prefix=''):
    actual = pin(raw)
    assert actual == {k: record[prefix + k] for k in actual}, record.get('name')
    return actual

def output(path, raw):
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        with path.open('xb') as stream:
            stream.write(raw)

def tree_graph(rows, blob_field, mode_field):
    dirs = {'': {}}
    for row in rows:
        path = row['path']
        assert not path.startswith('/') and all(x not in ('', '.', '..') for x in path.split('/'))
        parent, _, name = path.rpartition('/')
        assert name not in dirs.setdefault(parent, {})
        dirs[parent][name] = (row[mode_field], row[blob_field])
        while parent:
            parent, _, _ = parent.rpartition('/')
            dirs.setdefault(parent, {})
    trees = {}
    for parent in sorted(dirs, key=lambda s: (s.count('/') + bool(s)), reverse=True):
        children = dict(dirs[parent])
        for child, value in trees.items():
            upper, _, name = child.rpartition('/')
            if child and upper == parent:
                assert name not in children
                children[name] = ('40000', value['sha'])
        order = sorted(children, key=lambda n: (n + ('/' if children[n][0] == '40000' else '')).encode())
        raw = b''.join(children[n][0].encode() + b' ' + n.encode() + b'\0' + bytes.fromhex(children[n][1]) for n in order)
        trees[parent] = {'sha': oid('tree', raw), 'raw': raw}
    return trees

approval_path = R / 'ROOT_B608_CANONICAL_EXACT_APPROVAL.json'
approval = read(approval_path)
request_raw = (K / 'ACTUAL_PROCESS_INPUT.original.json').read_bytes()
same_pin(request_raw, approval['exact_request'])
assert identity(approval_path)['git_blob'] == 'adae9ceb057634904d03c10f9bd3ec33a98fef79'
assert (K / 'ROOT_EXACT_APPROVAL.original.json').read_bytes() == approval_path.read_bytes()
request = json.loads(request_raw)
assert sorted(request) == approval['exact_request_fields']
assert request['host'] == 'desktop' and request['cwd'] == '/home/qian-qi'
assert request['executable'] == '/usr/bin/python3' and request['timeout_seconds'] == 900
assert request['args'][:2] == ['-B', '-c'] and len(request['args']) == 3
assert request['idempotency_key'] == approval['idempotency_key']
same_pin(request['args'][2].encode(), approval['exact_bootstrap'])
same_pin(request['stdin'].encode(), approval['exact_stdin'])
intent = read(K / 'MAIN_DISPATCH_INTENT.json')
assert intent['approval'] == identity(approval_path) and intent['request'] == pin(request_raw)
assert intent['idempotency_key'] == request['idempotency_key'] and intent['timeout_seconds'] == 900
admission = unwrap(K / 'MAIN_ADMISSION.original.json')
job = admission['job']
assert job['id'] == JOB and job['idempotency_key'] == request['idempotency_key']
assert all(job[k] == request[k] for k in ('host', 'cwd', 'args', 'executable'))
assert job['env_keys'] == [] and job['launch_state'] == 'launched' and job['launch_error'] is None
assert admission['launch']['ok'] and not admission['reused']
assert job['request_digest'] == 'c13d43da104bd71c9f86bbf77611e8af42577ee4475cce54c317385b65a13e22'
normal = unwrap(K / 'STATUS_02.original.json')
assert normal['job_id'] == JOB and normal['state'] == 'succeeded' and normal['exit_code'] == 0
assert all(normal[k] for k in ('output_complete', 'output_durable', 'terminal_publication_confirmed'))
assert not any(normal[k] for k in ('timed_out', 'cancelled', 'automatic_retry'))
streams = unwrap(K / 'STREAM_READ_01.original.json')
assert streams['job_id'] == JOB
for label, size in [('stdout', 706), ('stderr', 0)]:
    row = streams[label]
    raw = bytes.fromhex(row['bytes_hex'])
    assert raw == row['text'].encode() == (K / (label.upper() + '.original.txt')).read_bytes()
    assert row['offset'] == 0 and row['next_offset'] == row['size'] == len(raw) == size and row['eof']
    assert normal['log_bytes'][label] == {'seen': size, 'stored': size}
    assert normal['log_synced'][label] and not normal['log_truncated'][label] and normal['log_errors'][label] is None

result = read(K / 'RESULT.json')
catalog_rows = read(K / 'ARTIFACTS.json')
catalog = {x['name']: x for x in catalog_rows}
assert len(catalog) == len(catalog_rows) == 505
assert result['artifacts'] == [x for x in catalog_rows if x['name'] != 'RESULT.json']
same_pin((K / 'RESULT.json').read_bytes(), catalog['RESULT.json'])
assert result['status'] == 'CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY' and result['source_repo'] == REPO
assert result['before'] == approval['before']
assert {k: result['after'][k] for k in ('commit', 'tree', 'parents', 'inventory')} == approval['expected_after_not_yet_observed']
assert result['after']['parents'] == [OLD] and result['local_head_advanced']
assert result['physical_source_writes_dispatched'] == result['test_commands_dispatched'] == 0
assert not any(result[k] for k in ('qualification', 'cargo_or_formatter_started', 'dependency_installation_started', 'automatic_retry', 'source_branch_refs_updated', 'remote_ref_updates'))
assert result['action_budget_seconds'] == 600 and result['record_budget_seconds'] == 180
action_elapsed = (datetime.fromisoformat(result['action_finished_at']) - datetime.fromisoformat(result['action_budget_started_at'])).total_seconds()
record_elapsed = (datetime.fromisoformat(result['finished_at']) - datetime.fromisoformat(result['record_budget_started_at'])).total_seconds()
assert 0 <= action_elapsed <= 600 and 0 <= record_elapsed <= 180
assert [(x['check'], x['status']) for x in result['final_audits']] == [('source', 'verified'), ('git', 'verified'), ('inputs', 'verified')]
assert all(result['actual'][k] is True for k in ('complete_source_clean', 'detached', 'index_equals_tree', 'normal_stat_refresh_verified', 'physical_bytes_unchanged', 'physical_equals_canonical_before_index_change', 'physical_modes_unchanged'))

# All external binary original receipts: complete, fixed-version, gap-free.
groups = {}
sdk_rows = []
for path in sorted(K.iterdir()):
    if re.fullmatch(r'.+\.READ_[0-9]{2}\.original\.json', path.name):
        item = unwrap(path)
        body = base64.b64decode(item['data_base64'], validate=True)
        assert hashlib.sha256(body).hexdigest() == item['chunk_sha256']
        assert item['next_offset'] - item['offset'] == len(body)
        groups.setdefault(item['path'], []).append((item, body, path))
        sdk_rows.append({'local_path': str(path), **identity(path)})
assert len(sdk_rows) == 58 and len(groups) == 31
observed_bodies = {}
full_reads = []
for native_path, rows in sorted(groups.items()):
    rows.sort(key=lambda x: x[0]['offset'])
    cursor = 0
    for i, (row, body, path) in enumerate(rows):
        assert row['offset'] == cursor
        assert row['version'] == rows[0][0]['version'] and row['size'] == rows[0][0]['size']
        assert row['eof'] is (i == len(rows) - 1)
        cursor = row['next_offset']
    raw = b''.join(x[1] for x in rows)
    assert cursor == len(raw) == rows[0][0]['size']
    name = Path(native_path).name
    local_candidates = [K / name, K / 'artifacts' / name, K / 'staging' / name]
    local = next((p for p in local_candidates if p.is_file() and p.read_bytes() == raw), None)
    assert local is not None, native_path
    observed_bodies[native_path] = raw
    if '/run/' in native_path and name in catalog:
        same_pin(raw, catalog[name])
    if name.endswith('.gz') and name in catalog:
        decoded = gzip.decompress(raw)
        same_pin(decoded, catalog[name], 'raw_')
        assert (K / 'artifacts' / name[:-3]).read_bytes() == decoded
    full_reads.append({'native_path': native_path, 'version': rows[0][0]['version'], 'chunks': len(rows), **pin(raw)})

# Exact staging / historical input bindings; two large bodies are preheld, not
# a second independent host download.
wire = json.loads(request['stdin'])['files']
inputs_raw = {n: base64.b64decode(v, validate=True) for n, v in wire.items()}
inputs_raw['CANONICAL_PACKET.json'] = gzip.decompress(inputs_raw['CANONICAL_PACKET.json'])
input_names = {'driver.py': 'driver', 'APPROVED_CONFIG.json': 'configuration', 'CANONICAL_PACKET.json': 'canonical_packet', 'FINAL_FORMAT_NORMAL.original.json': 'final_format_normal'}
assert set(inputs_raw) == set(input_names)
inputs_final = read(K / 'artifacts/INPUTS.final.json')
assert len(inputs_final) == 8
for name, field in input_names.items():
    same_pin(inputs_raw[name], approval['four_inputs'][field])
    same_pin(inputs_raw[name], inputs_final[CONTROL + '/' + name])
stage = read(K / 'STAGING_READBACK.json')
assert not stage['qualification'] and not stage['source_writes_during_staging']
stage_by_name = {Path(x['path']).name: x for x in stage['files']}
assert len(stage_by_name) == len(stage['files']) == 7
for name in ('ACTUAL_BOOTSTRAP.py', 'ACTUAL_BOOTSTRAP_ARGV.json', 'driver.py', 'APPROVED_CONFIG.json', 'FINAL_FORMAT_NORMAL.original.json'):
    body = observed_bodies[CONTROL + '/' + name]
    same_pin(body, stage_by_name[name])
    if name == 'ACTUAL_BOOTSTRAP.py':
        assert body == request['args'][2].encode()
    elif name == 'ACTUAL_BOOTSTRAP_ARGV.json':
        assert json.loads(body) == [request['executable'], *request['args']]
    else:
        assert body == inputs_raw[name]
same_pin(request['stdin'].encode(), stage_by_name['ACTUAL_BOOTSTRAP_PAYLOAD.json'])
same_pin(inputs_raw['CANONICAL_PACKET.json'], stage_by_name['CANONICAL_PACKET.json'])
packet = json.loads(inputs_raw['CANONICAL_PACKET.json'])
assert inputs_raw['CANONICAL_PACKET.json'] == (D / 'CANONICAL_PACKET.json').read_bytes()
assert len(packet['objects']) == 29 and result['actual']['verified_canonical_objects'] == 29
object_rows = {}
for item in packet['objects']:
    raw = base64.b64decode(item['raw_base64'], validate=True)
    assert len(raw) == item['bytes'] and hashlib.sha256(raw).hexdigest() == item['sha256']
    assert oid(item['type'], raw) == item['sha'] and item['sha'] not in object_rows
    object_rows[item['sha']] = (item, raw)
assert Counter(x[0]['type'] for x in object_rows.values()) == {'blob': 21, 'tree': 7, 'commit': 1}
assert object_rows[NEW][1] == (R / 'FINAL_B6084394_COMMIT.raw').read_bytes()
assert object_rows[NEW][1].startswith(('tree ' + NEW_TREE + '\nparent ' + OLD + '\n').encode())
for name, field in [('FINAL_FORMAT_RESULT.original.json', 'result'), ('FINAL_FORMAT_SUPERVISOR.original.json', 'supervisor'), ('FINAL_FORMAT_GIT_STATE.original.json', 'git_state')]:
    same_pin((K / 'artifacts' / name).read_bytes(), result['final_format'][field])
assert result['final_format']['result']['git_blob'] == '800869ed57256984964dd3c8b9f29e09c496438a'
assert result['final_format']['supervisor']['git_blob'] == '0f7aee8fb7c354f234732b5791e78d63671cd894'
assert inputs_final['/home/qian-qi/hepta-utility-36fa-evidence/provider-coordinator-a489-maintenance-v1/inventory-driver.original.py'] == {'bytes': 22946, 'git_blob': '51181866cbbb6e0176aab04117efffa8b6792b31', 'sha256': '20c11034146f6739dd24e9d7e33b94ee909754b07ce6295c242c842c5f3c40b2'}
assert inputs_final['/usr/bin/git'] == {'bytes': 4066232, 'sha256': 'eb54b535467e0975c1284d4c4d08eea779aeb248a5d34b02e2ee171382e22201'}

# Reconstruct the complete physical inventory and both tracked snapshot trees.
inventories = {}
inventory_receipts = []
for side in ('before', 'final'):
    cat = catalog['SOURCE.' + side + '.inventory.json.gz']
    chunks = []
    for item in cat['parts']:
        encoded = (I / item['name']).read_bytes()
        same_pin(encoded, item)
        decoded = base64.b64decode(encoded.strip(), validate=True)
        assert item['decoded_offset'] == sum(map(len, chunks))
        assert len(decoded) == item['decoded_bytes'] and hashlib.sha256(decoded).hexdigest() == item['decoded_sha256']
        chunks.append(decoded)
    zipped = b''.join(chunks)
    same_pin(zipped, cat)
    raw = gzip.decompress(zipped)
    same_pin(raw, cat, 'raw_')
    assert raw == (I / ('SOURCE.' + side + '.inventory.exact_recovered.json')).read_bytes()
    inventory = json.loads(raw)
    assert inventory['tracked_entries'] == inventory['filesystem_entries'] == len(inventory['files']) == 15243
    assert len({x['path'] for x in inventory['files']}) == 15243
    assert all(x['stable'] for x in inventory['files'])
    inventories[side] = inventory
    inventory_receipts.append({'side': side, 'provenance': 'preheld complete bytes match original producer raw/gzip/all five parts; not a new external inventory download', **pin(raw)})
assert inventories['final']['source'] == {'head': NEW, 'tree': NEW_TREE, 'status': ''}
assert all(x['matches_index'] for x in inventories['final']['files'])
physical_fields = ('path', 'bytes', 'kind', 'permissions', 'sha256', 'working_blob')
physical = lambda x: sorted([{k: row[k] for k in physical_fields} for row in x['files']], key=lambda x: x['path'].encode())
assert physical(inventories['before']) == physical(inventories['final'])
dirty_paths = sorted(x['path'] for x in inventories['before']['files'] if not x['matches_index'])
assert len(dirty_paths) == 21
old_trees = tree_graph(inventories['before']['files'], 'index_blob', 'index_mode')
new_trees = tree_graph(inventories['final']['files'], 'index_blob', 'index_mode')
assert old_trees['']['sha'] == OLD_TREE and new_trees['']['sha'] == NEW_TREE
for item, body in object_rows.values():
    if item['type'] == 'tree':
        assert body in [x['raw'] for x in new_trees.values()]
snapshot_objects = {x['index_blob']: 'blob' for side in inventories.values() for x in side['files']}
snapshot_objects.update({x['sha']: 'tree' for trees in (old_trees, new_trees) for x in trees.values()})
snapshot_objects.update({OLD: 'commit', NEW: 'commit'})
assert len(snapshot_objects) == 16523
object_requests = b''.join((sha + '\n').encode() for sha in sorted(snapshot_objects))
same_pin(object_requests, catalog['OBJECT_REQUESTS.txt'])

commands = read(K / 'artifacts/COMMANDS.json')
assert commands == result['commands'] and len(commands) == 94
assert all(x['actual_terminal'] == 'observed' and x['returncode'] == 0 for x in commands)
batch = read(K / 'artifacts/OBJECT_BATCH.terminal.json')
assert [x for x in commands if 'timed_out' not in x] == [batch]
assert batch['objects'] == batch['objects_observed'] == result['actual']['verified_snapshot_objects'] == 16523
assert batch['stdin_sha256'] == hashlib.sha256(object_requests).hexdigest()
batch_intent = read(K / 'artifacts/OBJECT_BATCH.intent.json')
assert batch_intent['actual_terminal'] == 'unknown_not_observed'
assert all(batch[k] == v for k, v in batch_intent.items() if k != 'actual_terminal')
prefix = ['/usr/bin/git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-c', 'core.untrackedCache=false', '-c', 'diff.autoRefreshIndex=false', '-c', 'core.logAllRefUpdates=false', '-C', REPO]
mutation_commands = []
for row in commands:
    if row is batch or 'timed_out' not in row:
        continue
    assert row['timed_out'] is False and row['argv'][:len(prefix)] == prefix
    for field in ('stdin', 'stdout', 'stderr'):
        if field in row:
            entry = row[field]
            if entry['name'] in catalog:
                assert entry == catalog[entry['name']]
            else:
                compressed = catalog[entry['name'] + '.gz']
                assert {k: entry[k] for k in ('bytes', 'sha256', 'git_blob')} == {k: compressed['raw_' + k] for k in ('bytes', 'sha256', 'git_blob')}
    if row['purpose'] == 'authorized mutation':
        mutation_commands.append(row)
assert len(mutation_commands) == 33
for command, item in zip(mutation_commands[:29], packet['objects']):
    assert command['argv'][len(prefix):] == ['hash-object', '-t', item['type'], '-w', '--stdin']
    raw = object_rows[item['sha']][1]
    same_pin(raw, command['stdin'])
    same_pin((item['sha'] + '\n').encode(), command['stdout'])
assert [x['argv'][len(prefix):] for x in mutation_commands[29:]] == [
    ['read-tree', NEW_TREE], ['update-index', '--refresh'], ['write-tree'],
    ['update-ref', '--no-deref', 'HEAD', NEW, OLD]]
same_pin((NEW_TREE + '\n').encode(), mutation_commands[31]['stdout'])
mutations = read(K / 'artifacts/MUTATION_PROGRESS.json')
assert mutations == result['mutation_intents'] and len(mutations) == 33
assert [x['ordinal'] for x in mutations] == list(range(1, 34))
assert all(x['terminal'] == 'observed' and x['at'] <= x['completed_at'] for x in mutations)
assert [x['sha'] for x in mutations[:29]] == [x['sha'] for x in packet['objects']]
imported = read(K / 'artifacts/OBJECT_IMPORT.json')
assert imported['verified_objects'] == 29 and imported['existing_objects_retained']
assert imported['actually_added_objects'] == [x['sha'] for x in packet['objects']]
for name in ('initial.process-preflight.json', 'immediately-before-object-import.process-preflight.json', 'immediately-before-index-head-change.process-preflight.json'):
    guard = read(K / 'artifacts' / name)
    assert guard['active_matching_processes'] == guard['unreadable_matching_processes'] == []
lease = read(K / 'artifacts/SOURCE_COORDINATION_EX.json')
assert lease['lock_acquired'] == 'LOCK_EX|LOCK_NB' and lease['uid'] == 1000 and lease['mode'] == 0o600 and lease['nlink'] == 1
assert lease['device'] == 2050 and lease['inode'] == 50139448

meta = {}
for side, result_side in [('before', 'before'), ('final', 'after')]:
    state = read(K / 'artifacts' / ('GIT_STATE.' + side + '.json'))
    assert state == result[result_side]['git_state']
    metadata = read(K / 'artifacts' / ('GIT_METADATA.' + side + '.json'))
    assert metadata['root'] == REPO + '/.git'
    rows = {x['path']: x for x in metadata['files']}
    assert len(rows) == len(metadata['files'])
    assert list(rows) == sorted(rows, key=lambda x: x.encode())
    raw_index = (K / 'artifacts' / ('INDEX.' + side + '.raw')).read_bytes()
    assert pin(raw_index)['sha256'] == state['index_sha256'] == rows['index']['sha256']
    assert len(raw_index) == state['index_bytes'] == rows['index']['bytes'] == 2080152
    assert rows['HEAD']['sha256'] == state['head_raw_sha256']
    assert state['refs_bytes'] == 0 and state['refs_sha256'] == hashlib.sha256(b'').hexdigest()
    meta[side] = rows
changes = [{'path': p, 'before': meta['before'].get(p), 'after': meta['final'].get(p)} for p in sorted(set(meta['before']) | set(meta['final']), key=lambda p: p.encode()) if meta['before'].get(p) != meta['final'].get(p)]
assert len(meta['before']) == 12 and len(meta['final']) == 70 and len(changes) == 61
assert changes == result['git_metadata_actual_changes'] == read(K / 'artifacts/GIT_METADATA.allowed-actual-delta.json')
assert len([x for x in changes if x['before'] is None]) == 58
assert [x['path'] for x in changes if x['before'] is not None] == ['HEAD', 'index', 'objects']

peer_dir = Path('/tmp/hepta-36fa-canonical-5a9-index-metadata-independent-peer-v1')
peer = read(peer_dir / 'REVIEW.json')
assert identity(peer_dir / 'REVIEW.json')['git_blob'] == 'e8c87c9ef2dfb09f1db40533b675b4032c852f9d'
assert peer['status'] == 'ACTUAL_CAPTURED_INDEX_AND_METADATA_CONSISTENT'
assert peer['no_concrete_mismatch_in_reviewed_scope'] is True
assert peer['actual_result'] == identity(K / 'RESULT.json')
assert peer['actual_catalog'] == identity(K / 'ARTIFACTS.json')
assert peer['H_calls'] == peer['Git_commands'] == peer['live_lstat_calls'] == peer['project_commands'] == 0
assert peer['qualification'] is False and peer['execution_approval'] is False
for name, expected in peer['proofs'].items():
    same_pin((peer_dir / name).read_bytes(), expected)

# This ledger is written only after Root's actual independent Git full GET of
# every original SDK/control identity; local bytes alone do not assert that.
get_ledger_path = R / 'ROOT_5A9_ORIGINAL_FULL_GET.json'
get_ledger = read(get_ledger_path)
assert get_ledger['count'] == len(get_ledger['records']) == 63
for entry in get_ledger['records']:
    assert entry['actual_full_get_equal'] is True
    assert identity(entry['path']) == {k: entry[k] for k in ('bytes', 'sha256', 'git_blob')}
assert {x['local_path'] for x in sdk_rows}.issubset({x['path'] for x in get_ledger['records']})

report = {
    'format': 'hepta-root-5a9-original-runtime-and-complete-source-closure-v1',
    'status': 'ACTUAL_CANONICAL_ALIGNMENT_CLOSED_NOT_QUALIFIED',
    'job_id': JOB, 'exact_approval': identity(approval_path), 'exact_request': pin(request_raw),
    'original_admission': identity(K / 'MAIN_ADMISSION.original.json'),
    'original_normal': identity(K / 'STATUS_02.original.json'),
    'original_result': identity(K / 'RESULT.json'), 'original_catalogue': identity(K / 'ARTIFACTS.json'),
    'complete_streams': {'stdout': 706, 'stderr': 0},
    'original_binary_calls': 58, 'complete_fixed_version_paths': 31, 'full_reads': full_reads,
    'actual_root_full_get_ledger': identity(get_ledger_path),
    'source': {'before': result['before'], 'after': result['after'], 'complete_paths': 15243,
               'before_dirty_paths': dirty_paths, 'physical_bytes_and_modes_unchanged': True,
               'independently_rebuilt_old_tree': old_trees['']['sha'],
               'independently_rebuilt_new_tree': new_trees['']['sha'],
               'old_tree_nodes': len(old_trees), 'new_tree_nodes': len(new_trees),
               'inventories': inventory_receipts},
    'canonical_objects': {'blobs': 21, 'trees': 7, 'commit': 1, 'all_typed_hashes_equal': True},
    'two_snapshot_object_union': {'objects': len(snapshot_objects), 'exact_original_request_listing': pin(object_requests), 'original_batch_observed': 16523},
    'commands': {'total_observed_zero': 94, 'ordinary_commands_without_timeout': 93,
                 'original_object_batch_without_invented_timeout_field': 1,
                 'authorized_mutations': 33, 'object_imports': 29, 'index_and_head_operations': 4},
    'staging': {'small_original_full_reads': 5, 'large_exact_preheld_producer_bound_bodies': 2, 'new_large_external_downloads': 0},
    'metadata': {'before_rows': 12, 'final_rows': 70, 'exact_delta_rows': 61,
                 'added_rows': 58, 'changed_existing_paths': ['HEAD', 'index', 'objects'],
                 'native_ns_integers_preserved_in_python': True},
    'independent_index_metadata_peer': identity(peer_dir / 'REVIEW.json'),
    'budgets': {'outer_seconds': 900, 'action_seconds': 600, 'record_seconds': 180,
                'actual_action_seconds': action_elapsed, 'actual_record_seconds': record_elapsed},
    'final_audits': result['final_audits'],
    'scope': ['505 catalogue rows retain original producer identities; only the stated 31 paths are complete external binary reads.',
              'Full inventory and audit recovery compare exact raw/gzip/parts. They are not new host observations.',
              'Separate independent index/metadata peer closes complete index entries, flags, cache trees and metadata projection.',
              'No separate HEAD.final.raw was emitted; successful original detached HEAD CAS, final Git state and metadata bind it.'],
    'qualification': False, 'source_or_native_tests_dispatched': 0,
    'real_authorized_learning_chains': 0, 'source_branch_refs_updated': False,
    'new_h_dispatches_by_this_review': 0,
}
raw = (json.dumps(report, sort_keys=True, indent=2) + '\n').encode()
target = R / 'ROOT_5A9_ACTUAL_SOURCE_RUNTIME_CLOSURE.json'
output(target, raw)
print(json.dumps({'path': str(target), **pin(raw), 'commands': 94, 'mutations': 33, 'native_reads': 58, 'paths': 31, 'qualification': False}))
