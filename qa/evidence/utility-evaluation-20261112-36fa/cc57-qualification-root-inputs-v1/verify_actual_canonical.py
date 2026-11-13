import hashlib
import json
from pathlib import Path

ROOT = Path('/tmp/hepta-36fa-cc57-qualification-root-inputs-v1')
ALIGN = Path('/tmp/hepta-36fa-source-repair-canonical-alignment-launch-v1')
PACK = Path('/tmp/hepta-36fa-source-repair-canonical-packet-v1')

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}

def load(path):
    raw = path.read_bytes()
    return raw, json.loads(raw)

def payload(path):
    raw, value = load(path)
    assert value.get('isError') is False
    assert len(value['content']) == 1 and value['content'][0]['type'] == 'text'
    return raw, json.loads(value['content'][0]['text'])

raw, result = load(ALIGN / 'RESULT.json')
assert pin(raw) == {'bytes': 138945, 'sha256': '1c058f83bb69579f7d039a401ab1e94cd0fb25529dc8d8dc7f91a73c9fbb75fe', 'git_blob': 'c374e3029f0fa8fa4f66d6e311c6841785db63b5'}
normal_raw, normal = payload(ALIGN / 'STATUS_01.original.json')
assert normal['job_id'] == '1a1d223a60b-2564-1ca3'
assert normal['state'] == 'succeeded' and normal['exit_code'] == 0
assert all(normal[k] is False for k in ('automatic_retry','cancelled','timed_out'))
assert all(normal[k] is True for k in ('output_complete','output_durable','terminal_publication_confirmed'))
assert not any(normal['log_truncated'].values())
assert normal['log_bytes'] == {'stderr': {'seen':0,'stored':0}, 'stdout': {'seen':688,'stored':688}}
admission_raw, admission = payload(ALIGN / 'EXACT_RECONCILE_01.original.json')
request_raw, request = load(ALIGN / 'ACTUAL_PROCESS_INPUT.json')
assert pin(request_raw)['git_blob'] == '87bdc70f82bc46f94bcce496559c9805bf764b89'
assert admission['reused'] is False and admission['launch']['ok'] is True
job = admission['job']
assert job['id'] == normal['job_id'] and job['launch_state'] == 'launched'
for key in ('args','cwd','executable','host','idempotency_key'):
    assert job[key] == request[key], key
assert job['env_keys'] == []
assert request['idempotency_key'] == 'hepta-utility-36fa-source-repair-canonical-alignment-v1'
assert request['timeout_seconds'] == 900
assert result['format'] == 'hepta-final-canonical-alignment-result-v1'
assert result['status'] == 'CANONICAL_SOURCE_ALIGNED_CLEAN_ONLY'
assert result['action_budget_seconds'] == 600 and result['record_budget_seconds'] == 180
assert {x['check']:x['status'] for x in result['final_audits']} == {'source':'verified','git':'verified','inputs':'verified'}
assert result['actual'] == {
    'complete_source_clean': True, 'detached': True, 'index_equals_tree': True,
    'normal_stat_refresh_verified': True, 'physical_bytes_unchanged': True,
    'physical_equals_canonical_before_index_change': True, 'physical_modes_unchanged': True,
    'verified_canonical_objects': 10, 'verified_snapshot_objects': 16449}
for key in ('source_branch_refs_updated','remote_ref_updates','cargo_or_formatter_started','dependency_installation_started','qualification','automatic_retry'):
    assert result[key] is False
assert result['physical_source_writes_dispatched'] == result['test_commands_dispatched'] == 0
assert result['local_head_advanced'] is True
assert result['source_repo'] == '/home/qian-qi/hepta-utility-36fa-maintenance-86dd-v1'
assert result['after']['commit'] == 'cc57c7198db6293ccca562253c42fffbe2a04633'
assert result['after']['tree'] == 'b7b357c07b5539769a068c6b9b009629f5612d1e'
assert result['after']['parents'] == ['246d8cb614770252ee42029a5c014f2a4904176a']
clean_raw, clean = load(PACK / 'CANONICAL_CLEAN_INVENTORY.expected.json')
dirty_raw, dirty = load(Path('/tmp/hepta-36fa-source-closure-246d-diagnosis-v1/actual-finalfmt-exact-recovery/final.inventory.exact-recovered.json'))
for side, data in [('before',dirty_raw),('after',clean_raw)]:
    assert {k: result[side]['inventory'][k] for k in ('bytes','sha256','git_blob')} == pin(data)
    assert result[side]['inventory']['tracked_entries'] == result[side]['inventory']['filesystem_entries'] == 15188
assert len(clean['files']) == len(dirty['files']) == 15188
changed_index = []
for old, new in zip(dirty['files'], clean['files']):
    assert {k:v for k,v in old.items() if k not in ('index_blob','matches_index')} == {k:v for k,v in new.items() if k not in ('index_blob','matches_index')}
    assert new['matches_index'] is True and new['working_blob'] == new['index_blob']
    if old != new: changed_index.append(new['path'])
assert len(changed_index) == 5
packet_raw, packet = load(PACK / 'CANONICAL_PACKET.json')
assert result['canonical_packet'] == pin(packet_raw)
commands = result['commands']
assert len(commands) == 56
assert all(c['returncode'] == 0 and c['actual_terminal'] == 'observed' for c in commands)
ordinary_commands = [c for c in commands if 'timed_out' in c]
batch_commands = [c for c in commands if 'timed_out' not in c]
assert len(ordinary_commands) == 55 and all(c['timed_out'] is False for c in ordinary_commands)
assert len(batch_commands) == 1
batch = batch_commands[0]
assert batch['purpose'] == 'full two-snapshot original object validation'
assert batch['objects'] == batch['objects_observed'] == 16449
assert batch['argv'] == ['/usr/bin/git','--no-optional-locks','-C',result['source_repo'],'cat-file','--batch']
assert batch['stderr']['bytes'] == 0
mutations = result['mutation_intents']
assert len(mutations) == 14 and all(m['terminal'] == 'observed' for m in mutations)
assert [m['ordinal'] for m in mutations] == list(range(1,15))
assert all(m['action'] == 'import_missing_canonical_object' for m in mutations[:10])
assert mutations[-1]['action'] == 'align_detached_HEAD_compare_and_swap'
assert mutations[-1]['expected_old'] == result['before']['commit'] and mutations[-1]['new'] == result['after']['commit']
assert mutations[10]['worktree_update'] is False
changes = result['git_metadata_actual_changes']
assert len(changes) == 23
assert all(c['path'] in ('HEAD','index','objects') or c['path'].startswith('objects/') for c in changes)
assert sum(c['after']['kind'] == 'file' and c['path'].startswith('objects/') for c in changes) == 10
for field in ('config_bytes','config_sha256','refs_bytes','refs_sha256'):
    assert result['before']['git_state'][field] == result['after']['git_state'][field]
timeout_raw, timeout = load(ALIGN / 'MAIN_ADMISSION.original.json')
assert len(timeout_raw) == 220 and timeout.get('isError') is True
review = {
    'format':'hepta-root-actual-cc57-canonical-alignment-review-v1',
    'status':'CANONICAL_SOURCE_ALIGNED_CLEAN_INDEPENDENTLY_REVIEWED',
    'actual_job_id':normal['job_id'], 'actual_result':pin(raw), 'actual_normal':pin(normal_raw),
    'actual_reconciliation':pin(admission_raw), 'exact_request':pin(request_raw),
    'first_transport_timeout_retained':pin(timeout_raw), 'actual_reconciliation_reused':False,
    'after':result['after'], 'before':result['before'], 'final_audits':result['final_audits'],
    'all_15188_physical_rows_bytes_modes_stable':True, 'five_index_changes':changed_index,
    'complete_command_count':56, 'all_commands_normal_zero':True,
    'object_batch_schema':'The single original object-batch terminal reports observed returncode0 and all16449 objects, with no separate timed_out key;55 ordinary command terminals explicitly report timed_outfalse.',
    'mutation_intent_count':14, 'git_metadata_change_count':23,
    'scope':'Canonical snapshot and explicit commit anchors; no whole-history fsck claim.',
    'source_ref_publication_ready':True, 'source_gates_passed':False, 'native_tests_started':False,
    'previous_246d_source_failure_retained':True, 'qualification':False, 'real_qualified_task_chains':0,
    'full_inventory_recovery':'Exact original-serializer bytes match actual native RESULT in all three identities. This is lossless recovery, not a second native full read.'}
output = (json.dumps(review,sort_keys=True,indent=2)+'\n').encode()
target = ROOT / 'ROOT_ACTUAL_CANONICAL_REVIEW.json'
if target.exists(): assert target.read_bytes() == output
else: target.write_bytes(output)
print(json.dumps({'review':pin(output),'actual_source':result['after']['commit'],'physical_entries':15188,'source_ref_ready':True},sort_keys=True))
