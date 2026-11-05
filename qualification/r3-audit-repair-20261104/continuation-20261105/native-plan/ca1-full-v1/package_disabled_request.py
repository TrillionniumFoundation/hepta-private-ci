"""Freeze existing source/graph originals into a disabled native request."""
import ast
import base64
import gzip
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path('/workspace/scratch/07dd58cc9630')
CORE = HERE.parent


def identity(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def pin(path):
    return {'local_path': str(path), **identity(path.read_bytes())}


def save(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    return pin(path)


original_path = ROOT / 'hepta-audit-fifth/inputs/core-musl-native-ENABLED-v3.json'
original = json.loads(original_path.read_bytes())
packed = base64.b64decode(original['inputs']['gzip_base64'], validate=True)
assert hashlib.sha256(packed).hexdigest() == original['inputs']['gzip_sha256']
raw = gzip.decompress(packed)
assert len(raw) == original['inputs']['bytes'] and hashlib.sha256(raw).hexdigest() == original['inputs']['sha256']
inputs = json.loads(raw)
frozen_source = original['runner']['source']
tree = ast.parse(frozen_source)
namespace = {'hashlib': hashlib}
selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('need', 'tree_hash', 'graph')]
exec(compile(ast.Module(body=selected, type_ignores=[]), 'pure-source-map-functions', 'exec'), namespace)
initial = {row['path']: row for row in inputs['product_leaves']}
assert namespace['tree_hash'](initial.values()) == 'b26598d0d97d8d51e723bb5582137315f2174d35'
for post in inputs['candidate_posts']:
    body = base64.b64decode(post['base64'], validate=True)
    assert identity(body) == post['identity']
    initial[post['path']] = {'path': post['path'], 'mode': '100644', 'type': 'blob',
                             'sha': post['identity']['git_blob'], 'size': len(body)}
assert namespace['tree_hash'](initial.values()) == 'e78c819b8b1f435f8b37bea17b4ffdc724961aa2'

composition_path = ROOT / 'hepta-audit-fifth/inputs/integrated-14-path-candidate-v2.json'
composition = json.loads(composition_path.read_bytes())
assert composition['tree'] == 'ca1c4671ef6b2773280d01b5d76c6166252f5856'
assert len(composition['changes']) == 14 and composition['leaf_count'] == 10582
candidate = dict(initial)
changes = []
unchanged_e78 = []
for change in composition['changes']:
    before = initial.get(change['path'])
    if before and before['sha'] == change['sha'] and before['mode'] == change['mode']:
        unchanged_e78.append(change['path'])
        continue
    assert (before or {}).get('sha') == change['before_sha']
    response_path = HERE / 'candidate-posts' / ('git-get-' + change['sha'] + '.original.json')
    response = json.loads(response_path.read_bytes())
    assert response.get('isError') is False
    body = response['structuredContent']['content'].encode()
    assert identity(body)['git_blob'] == change['sha']
    post_path = HERE / 'candidate-posts' / ('post-' + change['sha'] + '.source.txt')
    with post_path.open('xb') as stream:
        stream.write(body)
    row = {'path': change['path'], 'mode': change['mode'],
           'before': None if before is None else {key: before[key] for key in ('mode', 'sha')},
           'identity': identity(body), 'base64': base64.b64encode(body).decode()}
    changes.append(row)
    candidate[change['path']] = {'path': change['path'], 'mode': change['mode'], 'type': 'blob',
                                'sha': change['sha'], 'size': len(body)}
assert len(changes) == 12 and sum(row['before'] is None for row in changes) == 2
assert len(unchanged_e78) == 2 and len(candidate) == 10582
assert namespace['tree_hash'](candidate.values()) == composition['tree']

metadata_path = CORE / 'project-nonpass-complete-v1/decoded-verified-v1/candidate-full-metadata.stdout'
metadata_raw = metadata_path.read_bytes()
historical_pin = inputs['historical_full_metadata']
assert len(metadata_raw) == historical_pin['bytes'] and hashlib.sha256(metadata_raw).hexdigest() == historical_pin['sha256']
metadata = json.loads(metadata_raw)
graph = namespace['graph'](metadata)
graph_raw = (json.dumps(graph, sort_keys=True, separators=(',', ':')) + '\n').encode()
assert len(graph['workspace_members']) == 193 and len(graph['nodes']) == 1501
stage = {'schema': 'ai395-published-candidate-default-full-inputs-v1',
         'initial_tree': 'e78c819b8b1f435f8b37bea17b4ffdc724961aa2',
         'candidate_tree': composition['tree'], 'candidate_leaf_count': 10582,
         'publication_commit': 'eed4d6bb61b789b19f60facc79f9e031765fa4c9',
         'ordinary_HEAD_retained': '5b6331250ff459033bd44d1a95daec70131277cc',
         'composition_manifest': pin(composition_path), 'changes': changes,
         'historical_graph_reference': {
             'source_tree': historical_pin['source_tree'],
             'source_directory': original['plan']['source_directory'],
             'original_native_metadata_path': historical_pin['path'],
             'raw_metadata_identity': identity(metadata_raw), 'graph_identity': identity(graph_raw),
             'derivation_file_byte_identical_to_historical_raw': pin(metadata_path),
             'graph': graph}}
stage_path = HERE / 'candidate-stage-inputs.json'
stage_pin = save(stage_path, stage)
stage_raw = stage_path.read_bytes()
z = gzip.compress(stage_raw, mtime=0)
envelope = {'identity': identity(stage_raw), 'gzip_bytes': len(z),
            'gzip_sha256': hashlib.sha256(z).hexdigest(), 'gzip_mtime': 0,
            'gzip_base64': base64.b64encode(z).decode()}
assert gzip.decompress(base64.b64decode(envelope['gzip_base64'], validate=True)) == stage_raw

parent_request = CORE / 'ai395-c1-after-memory-stop-v1/c1-resume-candidate-v1/request-DISABLED.json'
request = json.loads(parent_request.read_bytes())
request['schema'] = 'ai395-published-candidate-C1-default-full-request-v1'
request['stage'] = 'PUBLISHED_CANDIDATE_C1_DEFAULT_FULL'
request['idempotency_key'] = 'hepta-ai395-core-candidate-ca1-full-20261105-v1'
request['historical_readonly_observation'] = request.pop('current_readonly_observation')
latest_root = CORE / 'ai395-c1-after-memory-stop-v1/native-c1-first-start/native-originals'
for key, name in [('latest_C1_terminal', 'C1-resume-terminal.json'),
                  ('latest_C1_source_guard', 'C1-resume-final-source-guard.json')]:
    request[key] = {'path': '/home/qq/work/hepta-core-musl-full-20261105/c1-resume-e78-v1/' + name,
                    **identity((latest_root / name).read_bytes())}
request['candidate_inputs'] = envelope
request['current_resource_observation_reference'] = {
    'actual_bundle_Git': '3011b3096e2a26c7474903356cb4b2430451ba62',
    'admission': 'Historical one-shot observation only; runtime fresh64GB/32GiB gates remain decisive.'}
request_path = HERE / 'request-DISABLED.json'
request_pin = save(request_path, request)
assert request_pin['bytes'] < 1048576
runner = HERE / 'run_candidate_default_full.py'
process = {'host': 'ai395', 'executable': '/usr/bin/python3',
           'args': ['-I', '-B', '-c', runner.read_text()], 'cwd': '/',
           'env': {}, 'timeout_seconds': 21600, 'idempotency_key': request['idempotency_key'],
           'stdin': request_path.read_text()}
process_pin = save(HERE / 'process-start-DISABLED.json', process)
manifest = {'schema': 'ai395-published-candidate-C1-default-full-disabled-manifest-v1',
            'execute': False, 'root_execution_guard': None,
            'native_actions_performed_by_preparation': 0,
            'publication_commit': stage['publication_commit'], 'working_tree_after_transition': composition['tree'],
            'ordinary_HEAD_retained': stage['ordinary_HEAD_retained'],
            'ordinary_index_sha256': 'b488256c0552f9ff6d6030b3a1738721dec54ffb5d2a2b56d99100943f04ed19',
            'runner': pin(runner), 'request': request_pin, 'process_start': process_pin,
            'delta': pin(HERE / 'C1-to-candidate-default-full.delta.patch'),
            'runner_derivation': pin(HERE / 'runner-derivation.json'),
            'stage_inputs': stage_pin, 'compressed_input_bytes': len(z),
            'source_transition': {'from': stage['initial_tree'], 'to': composition['tree'],
                                  'changed_from_e78': 12, 'new_files': 2, 'final_leaves': 10582,
                                  'changes': [{key: row[key] for key in ('path', 'mode', 'before', 'identity')} for row in changes]},
            'source_mutation_contract': 'All mapped preimages and the initial whole tree are checked; existing files use same-filesystem atomic replacement after exact preimage/stat checks, new paths use exclusive link publication. Exact backups and a transition journal are retained. Failure preserves actual working tree; no reset, auto-restore or unrelated overwrite.',
            'commands': [original['plan']['phases'][3]['commands'][0]] + original['plan']['phases'][5]['commands'],
            'complete_default_roster': {'total': len(inputs['full_roster']),
                                         'eligible': sum(not row['ignored'] for row in inputs['full_roster']),
                                         'ignored': sum(row['ignored'] for row in inputs['full_roster']),
                                         'comparison': 'Exact Counter(binary_id,name,ignored); only nonignored matches or ignored mismatch/reason ignored.'},
            'metadata_relation': {'historical_source_tree': historical_pin['source_tree'],
                                  'historical_raw_metadata': identity(metadata_raw),
                                  'historical_graph': identity(graph_raw),
                                  'members': 193, 'nodes': 1501,
                                  'normalization': 'Only explicit old/new source directory prefixes in package IDs: workspace_members, nodes.id, nodes.deps.pkg; all other fields/features/dependencies remain equal.'},
            'guard_reuse': 'Twelve C1 common functions are byte-equal. Frozen V3 command/source/tool/catalog/program/JUnit parsing functions are invoked unchanged, with new source/target/JUnit paths bound to the existing independent Core root.',
            'resource_floors': {'disk_bytes_before_after_every_command': 64000000000,
                                'MemAvailable_bytes': 34359738368, 'CARGO_BUILD_JOBS': 4,
                                'entry_200GB': 'Already completed C0, not a new cold root or a lowered initial floor.'},
            'result_rules': 'Keep every actual command exit, raw/JUnit/exact case result and original ignored/early-return distinctions. Final source/SDK/capacity guard error forces nonzero while retaining the prior scope result. No retries, exclusion, all-features, timeout/profile/security adjustment.',
            'not_automatic': ['Core project/direct-parallel reruns', 'Agentd qualification feature scope', 'hygiene', 'old B16 driver lookup/replay or source/target writes', 'cache cleanup', 'workflow or Git-ref mutation'],
            'later_original_Agentd_scope_DISABLED': {
                'precondition': 'Actual default full results reviewed by root; distinct feature metadata/catalog/binary qualification before hygiene.',
                'argv': ['just', 'test', '--locked', '--cargo-profile', 'dev-small', '--no-tests', 'fail', '--retries', '0',
                         '-p', 'codex-hepta-agentd', '--features', 'qualification-cognitive-write', '--lib',
                         'runtime::tests::qualification_', '--test-threads=1'],
                'names': ['runtime::tests::qualification_host_binds_one_local_turn_and_replays_exactly_once',
                          'runtime::tests::qualification_prepare_takes_over_expired_registry_head_without_evidence',
                          'runtime::tests::qualification_prepare_quarantines_expired_registry_attempt_with_h7_evidence'],
                'limit': 'Original3 cases once, distinct feature graph; never borrowed from default243-case Agentd program. Original lease30s/internal waits and local30s x2 timeout remain.'}}
manifest_pin = save(HERE / 'manifest-DISABLED.json', manifest)
print(json.dumps({'manifest': manifest_pin, 'request': request_pin, 'process': process_pin,
                  'input': stage_pin, 'compressed_bytes': len(z)}))
