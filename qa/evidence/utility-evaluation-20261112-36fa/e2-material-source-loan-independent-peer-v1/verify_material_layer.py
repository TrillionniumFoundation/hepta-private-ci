#!/usr/bin/env python3
"""Pure byte/schema review; never imports or executes project code."""
import difflib
import hashlib
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
E1 = Path('/tmp/hepta-36fa-root-product-e1-proposal-v1')
E2 = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')
E3 = Path('/tmp/hepta-36fa-root-product-e3-proposal-v1')
D = E2 / 'material-source-loan-layer-v1'
INVENTORY = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')
PREFIX = 'codex-rs/hepta-agentd/src/'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()}

def read(path):
    path = Path(path)
    first = path.stat()
    raw = path.read_bytes()
    last = path.stat()
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    assert tuple(getattr(first, k) for k in fields) == tuple(getattr(last, k) for k in fields), path
    assert len(raw) == last.st_size
    return raw

def obj(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            assert k not in result, k
            result[k] = v
        return result
    return json.loads(raw, object_pairs_hook=pairs)

def entries_of(packet):
    if 'images' not in packet:
        return packet['entries']
    identities = {e['path']: e for e in packet['manifest']['entries']}
    assert len(identities) == len(packet['manifest']['entries']) == len(packet['images'])
    return [dict(identities[e['path']], before_utf8=e['before'], after_utf8=e['after'])
            for e in packet['images']]

inventory_raw = read(INVENTORY)
assert pin(inventory_raw) == {
    'bytes': 5631947, 'sha256': 'de044334afed8b804f2a997f8b8e8d16e6e1c596d2a5b3400c40f350229b054e',
    'git_blob': '457adb9bf9ba3a844e9dfa149be49460bb306998'}
inventory = obj(inventory_raw)
assert inventory['source'] == {
    'head': 'b6084394a4a38ab495c16eaba09e879f04a96f8e',
    'tree': '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638', 'status': ''}
rows = {r['path']: r for r in inventory['files']}
assert len(rows) == len(inventory['files']) == 15243
state = {name: {'pin': {'bytes': r['bytes'], 'sha256': r['sha256'], 'git_blob': r['working_blob']},
                'mode': r['index_mode'], 'origin': str(INVENTORY), 'raw': None}
         for name, r in rows.items()}

prior = [
    (E1/'assembled-source-v1/SOURCE_PACKET.json', '1ca7a06948fcae69bf7c8e4c7823627a872c0c62'),
    (E1/'request-type-import-increment-v1/SOURCE_PACKET.json', '36cd9a693ce75070e1225a978575ca6dea5f72c2'),
    (E2/'factory-split-layer-v1/SOURCE_PACKET.json', '62ad5a5363ca91c335f2d599128f763c355b33bf'),
    (E2/'factory-test-refusal-increment-v1/SOURCE_PACKET.json', '12459a8255be0358c822a825d2445fa48828a7e1'),
    (E2/'ipc-layer-v1/SOURCE_PACKET.json', '06dafdbdeb53eb5ccf6480993596bbb4d939f203'),
    (E2/'ipc-purpose-increment-v1/SOURCE_PACKET.json', '69d6d5eda401ff59f7e89b1e659f77a431274248'),
    (E2/'ordinary-handoff-layer-v1/SOURCE_PACKET.json', '65e62f807885cd890d8fa9944c58e232dc55ae01'),
]
prior_proofs = []
for path, blob in prior:
    raw = read(path)
    assert pin(raw)['git_blob'] == blob, path
    packet_entries = entries_of(obj(raw))
    names = set()
    for e in packet_entries:
        name = e['path']
        assert name not in names and name.startswith(PREFIX) and e['mode'] == '100644'
        names.add(name)
        if e['before_utf8'] is None:
            assert e['before'] is None and name not in state, (path, name)
        else:
            before = e['before_utf8'].encode('utf-8')
            assert pin(before) == e['before'] == state[name]['pin'], (path, name)
            assert e['mode'] == state[name]['mode']
            if state[name]['raw'] is not None:
                assert before == state[name]['raw'], (path, name)
        after = e['after_utf8'].encode('utf-8')
        assert pin(after) == e['after'], (path, name)
        state[name] = {'pin': e['after'], 'mode': e['mode'], 'raw': after, 'origin': str(path)}
    prior_proofs.append({'path': str(path), **pin(raw), 'full_entries': len(names),
                         'all_preimages_match_prior_state': True})

packet_raw = read(D/'SOURCE_PACKET.json')
assert pin(packet_raw) == {'bytes': 532571,
    'sha256': 'a749862a739f321a3751c461e403904eb4488af6508cfa912c7e318adee31630',
    'git_blob': '911e41dbd5bb0dbe2098fe84e50728a73c5b3757'}
packet = obj(packet_raw)
assert packet['format'] == 'hepta-e2-material-original-source-loan-source-v1'
assert packet['status'] == 'LOCAL_PREPARED_UNEXECUTED'
assert packet['source_baseline'] == {'commit': inventory['source']['head'], 'tree': inventory['source']['tree']}
entries = packet['entries']
assert len(entries) == len({e['path'] for e in entries}) == 22
assert sum(e['before'] is None for e in entries) == 8
manifest_raw = read(D/'MANIFEST.json')
assert pin(manifest_raw)['git_blob'] == 'c08fdb652e9b417ff3cc675b43f81ade085af595'
manifest = obj(manifest_raw)
assert manifest['packet'] == pin(packet_raw)
assert manifest['entries'] == [{k:e[k] for k in ('path','mode','before','after')} for e in entries]
metadata = []
for field, file in [('byte_proof','BYTE_PROOF.json'), ('interface','INTERFACE_CONTRACT.json'),
                    ('patch','SOURCE_DELTA.patch'), ('registration_impact','REGISTRATION_IMPACT.json'),
                    ('review','REVIEW.json'), ('splices','EXACT_SOURCE_SPLICES.json')]:
    raw = read(D/file)
    assert pin(raw) == manifest[field], file
    metadata.append({'path': str(D/file), **pin(raw)})
splices = obj(read(D/'EXACT_SOURCE_SPLICES.json'))
assert len(splices) == 14 and sum(len(e['replacements']) for e in splices) == 23
splice_map = {s['path']: s for s in splices}
assert len(splice_map) == 14
assert set(splice_map) == {e['path'] for e in entries if e['before'] is not None}
source = {}; before_source = {}; file_proofs = []; patch_lines = []
for e in entries:
    name = e['path']
    assert name.startswith(PREFIX) and e['mode'] == '100644'
    after = e['after_utf8'].encode('utf-8')
    assert pin(after) == e['after'] and read(D/'after'/name) == after, name
    source[name] = after
    if e['before_utf8'] is None:
        assert e['before'] is None and name not in state and name not in rows
        assert not (D/'before'/name).exists(), name
        before = b''; origin = None; replacement_proofs = []
    else:
        before = e['before_utf8'].encode('utf-8')
        before_source[name] = before
        assert pin(before) == e['before'] == state[name]['pin'], name
        assert e['mode'] == state[name]['mode']
        assert read(D/'before'/name) == before
        if state[name]['raw'] is not None:
            assert before == state[name]['raw'], name
        own = splice_map[name]
        assert read(own['source']) == before, (name, 'declared preimage')
        forward = before; replacement_proofs = []
        for change in own['replacements']:
            left, right = change['before'].encode(), change['after'].encode()
            assert forward.count(left) == 1, (name, 'forward')
            offset = forward.index(left)
            replacement_proofs.append({'before': pin(left), 'after': pin(right), 'intermediate_offset': offset})
            forward = forward.replace(left, right, 1)
        assert forward == after, name
        inverse = after
        for change in reversed(own['replacements']):
            left, right = change['before'].encode(), change['after'].encode()
            assert inverse.count(right) == 1, (name, 'inverse')
            inverse = inverse.replace(right, left, 1)
        assert inverse == before, name
        origin = state[name]['origin']
    patch_lines.extend(difflib.unified_diff(before.decode().splitlines(keepends=True),
        after.decode().splitlines(keepends=True), fromfile='/dev/null' if e['before'] is None else 'a/'+name,
        tofile='b/'+name))
    file_proofs.append({'path': name, 'mode': e['mode'], 'before': e['before'], 'after': e['after'],
        'preimage_origin': origin, 'new_absent_from_canonical_and_all_prior_layers': e['before'] is None,
        'whole_forward_inverse_equal': e['before'] is not None, 'replacements': replacement_proofs,
        'embedded_equals_complete_local_source_bytes': True})
assert ''.join(patch_lines).encode() == read(D/'SOURCE_DELTA.patch')

# Exact old body preservation, beyond matching documentation claims.
dataset = PREFIX+'cell_q24_dataset.rs'
assert source[dataset].replace(b'pub(crate) fn require_source(\n', b'fn require_source(\n', 1) == before_source[dataset]
pair = PREFIX+'cell_q24_material_receipt_owner.rs'
mount = b'#[cfg(target_os = "linux")]\n#[path = "cell_q24_material_root_source.rs"]\nmod original_root_source;\n\n'
assert source[pair].count(mount) == 1 and source[pair].replace(mount,b'',1) == before_source[pair]
command = PREFIX+'cell_q24_material_command.rs'
mount = b'#[path = "cell_q24_material_source_context.rs"]\nmod original_source_context;\n\n'
assert source[command].count(mount) == 1 and source[command].replace(mount,b'',1) == before_source[command]
task = source[PREFIX+'authority_host_session_generation_root_task.rs']
assert task.count(b'runtime: CircuitQ24TaskRuntimeV1<SW, CW>,') == 1
for text in [b'session: Arc::new(session)', b'operation: Arc::new(operation)',
             b'custody: Arc::new(custody)', b'material_source_taken: false']:
    assert task.count(text) == 1, text
loan = source[PREFIX+'authority_host_session_material_source.rs']
assert loan.count(b'self.material_source_taken = true;') == 1
assert b'material_source_taken = false' not in loan
assert b'self.runtime' not in loan and b'impl Clone' not in loan and b'#[derive(Clone' not in loan
registration = source[PREFIX+'authority_host_material_source_registration.rs']
assert b'impl Clone' not in registration and b'#[derive(Clone' not in registration
assert b'pub(crate) fn from_original_supervisor(' in registration
assert b'pub fn from_original_supervisor(' not in registration
remote = source[PREFIX+'circuit_task_source_material.rs']
assert remote.count(b'*slot = Some(channel);') == 1
assert remote.count(b'decode_current_root_payload(payload)?') == 1
assert b'fn decode_current_root_payload(' in remote and b'pub fn decode_current_root_payload(' not in remote
assert b'Slot' not in remote  # No separate replacement channel/counter abstraction.

# Reviewer-owned ordered anchors supplement the complete human control-flow
# read. They are not Rust tests, a project collector or proof of live execution.
def ordered(name, texts):
    raw = source[PREFIX+name]; cursor = 0; items = []
    for text in texts:
        token = text.encode(); offset = raw.index(token,cursor)
        items.append({'text':text,'line':raw[:offset].count(b'\n')+1,'offset':offset})
        cursor=offset+len(token)
    return {'path':PREFIX+name,'anchors':items}

ordering = [
 ordered('authority_host_session_material_source.rs',[
  'self.read_original_root_task_generation()?;', 'if self.material_source_taken {',
  'self.material_source_taken = true;', 'let host = PreparedRootMaterialSourceHostV1 {',
  'host.require_current()?;', 'Ok(host)']),
 ordered('authority_host_session_material_source.rs',[
  'pub fn serve(self, registration:', 'self.require_current()?;',
  'if consumer.pid == self.session.registration.peer_pid {', 'let binding = wire::context(&material)',
  'let lifetime = self.end.checked_duration_since(Instant::now())',
  'let mut channel = original_owner_command_channel_v1(', 'for id in 1..=wire::LIMIT {',
  'let exchanged = channel.exchange(|bytes| {', 'let until = (Instant::now() + timeout).min(self.end);',
  'if bytes != request || wire::context(&material)', 'self.require_current()?;',
  'OriginalRootCircuitTaskCustodyV1::read_original_material_source(', 'self.require_current()?;',
  'let response = wire::response(', 'wire::before(until).map_err(protocol)?;',
  'Ok(true) => {', 'channel.check_peer_lifetime()', 'self.require_current()?;',
  'wire::context(&material)', 'wire::before(until).map_err(protocol)?;']),
 ordered('circuit_task_source_material.rs',[
  'pub(super) fn read(&self,', 'if identity != &self.identity', 'let mut channel = self.slot.try_lock()',
  '.take().ok_or(Error::Unavailable)?;', 'let deadline = (Instant::now() + self.timeout).min(self.end);',
  'wire::before(deadline)?;', 'wire::context(&self.config)?', 'wire::request(',
  'channel.next = channel.next.checked_add(1)', 'channel.original.request(&request)',
  'wire::before(deadline)?;', 'wire::read_response(', 'decode_current_root_payload(payload)?',
  'crate::cell_q24_dataset::require_source(', 'channel.original.check_peer_lifetime()',
  'wire::context(&self.config)?', 'let mut slot = self.slot.try_lock()',
  'wire::before(deadline)?;', '*slot = Some(channel);', 'Ok(observed)']),
 ordered('neuron_generation_initial_material_source.rs',[
  'require_root()?;', 'self.read_original_operation()?;',
  'self.task.read_original_material_publication(', 'crate::cell_q24_dataset::require_source(',
  'self.source.encode_original_material_publication(', 'self.task.read_original_material_publication(',
  'self.read_original_operation()?;', 'Ok(payload)']),
 ordered('circuit_feature_material_source.rs',[
  'if !Arc::ptr_eq(&self.0, &cell.task.0)', 'self.require_current()?;',
  'source.read_run_publication(identity, run)', 'cell.committed(&observed)?;',
  'source.read_run_publication(identity, run)', 'cell.committed(&observed)? != decision',
  'self.require_current()?;', 'Ok(observed)']),
 ordered('circuit_task_source_material.rs',[
  'pub(crate) fn encode_original_material_publication(', 'let OriginalReadback::Local(original)',
  'original.read_publication(', 'let mut owner = original.0.try_lock()',
  'owner.require_bytes("request",', 'owner.read("input",', 'owner.read("result",',
  'codec::decode_input(&saved)?', 'let mut out = wire::Writer::new(b"HCMATPUB1");',
  'out.bytes(&request_bytes)?;', 'out.bytes(&saved)?;', 'out.bytes(&result)?;',
  'owner.require_active(', 'owner.require_current()?;', 'wire::bounded(&payload)?;']),
 ordered('cell_q24_material_root_source.rs',[
  'pub fn into_original_root_source_command_owner(', 'self, stream:',
  'CircuitTaskSourceReadbackV1::from_original_material_root_stream(',
  'self.config.clone(), identity.clone()', 'OriginalCellQ24MaterialReceiptOwnersV1::into_command_owner(',
  'self, source, identity, ledger, baseline,']),
]
wire = source[PREFIX+'circuit_task_source_material_wire.rs']
for token in [b'pub(crate) const BOUND: usize = 16_384;',
              b'pub(crate) const TIMEOUT: Duration = Duration::from_millis(500);',
              b'pub(crate) const LIMIT: u64 = 128;']:
    assert token in wire
frame_prefix = len(b'HCMATRD1') + 32 + 16 + 8
assert frame_prefix == 64

impact = obj(read(D/'REGISTRATION_IMPACT.json'))
assert impact['combined_collector_result'] is None and impact['combined_counts'] is None
assert impact['new_tests_in_this_layer'] == [] and impact['source_git_created'] is False
assert impact['new_production_modules_requiring_full_guard'] == [e['path'] for e in entries if e['before'] is None]
assert impact['modified_paths_requiring_existing_guard_review'] == [e['path'] for e in entries if e['before'] is not None]
actual_declarations = []
for e in entries:
    if e['before'] is not None:
        continue
    raw = source[e['path']]
    for match in re.finditer(rb'(?m)^\s*(pub(?:\((?:crate|super)\))?) fn ([a-zA-Z_][a-zA-Z_0-9]*)',raw):
        actual_declarations.append({'path':e['path'], 'visibility':match[1].decode(), 'name':match[2].decode()})
assert actual_declarations == impact['new_explicit_function_declarations']
assert len(actual_declarations) == 16

dependencies_spec = [
 (E2/'references', PREFIX+'learning_owner_command_channel.rs', ['original_owner_command_channel_v1','require_original_process']),
 (E2/'references', PREFIX+'circuit_feature_current_owner.rs', ['PublishedCircuitCellOwnerV1','committed']),
 (E2/'references', PREFIX+'authority_host_admin.rs', ['Lifetime','Pending','RootAdminRuntime']),
 (E3/'references', PREFIX+'cell_q24_material_command_wire.rs', ['context_binding']),
 (E3/'references', PREFIX+'cell_q24_material_receipt_binding.rs', ['validate_config','read_material','verify_freeze']),
 (E3/'references', PREFIX+'cell_q24_material_command_service.rs', ['from_original_pair','serve_role_commands']),
 (E3/'references', PREFIX+'authority_host_learning_registration.rs', ['RegisteredHostLearningCheckpointV1']),
 (E3/'references', PREFIX+'learning_iteration_checkpoint.rs', ['Store','LearningIterationCheckpointOwnerV1']),
 (E1/'references', PREFIX+'neuron_generation_initial_root_custody.rs', ['OriginalInitialOperation','read_original']),
 (E1/'references', PREFIX+'neuron_generation_initial.rs', ['root_custody Linux module gate']),
 (E1/'references', PREFIX+'neuron_generation_current.rs', ['NeuronGenerationCurrentOwnerV1']),
 (E1/'references', PREFIX+'neuron_generation_current_store.rs', ['Store']),
 (E1/'references', PREFIX+'neuron_generation_update_live.rs', ['AgentdGenerationUpdateAuthoritiesV1','LiveGenerationCurrent']),
 (E1/'after', PREFIX+'authority_host_service.rs', ['HostAuthorityService']),
 (E1/'after', PREFIX+'authority_host_generation.rs', ['OriginalHostInitialOperation']),
 (E2/'ordinary-handoff-layer-v1/after', PREFIX+'authority_host_session_generation_task_handoff.rs', ['serve ordinary task and original host scope']),
 (E2/'ordinary-handoff-layer-v1/after', PREFIX+'authority_host_session_task_host.rs', ['same borrowed service fields']),
 (E2/'ipc-layer-v1/after', PREFIX+'authority_host_session_generation_task_service.rs', ['original single runtime lane take']),
 (E2/'ordinary-handoff-layer-v1/after', PREFIX+'circuit_task_source_codec.rs', ['original_record','decode_input','publication','decision_metadata']),
 (E2/'ordinary-handoff-layer-v1/after', PREFIX+'circuit_task_root_bootstrap_codec.rs', ['Reader','Writer']),
 (Path('/tmp/hepta-36fa-root-task-loader-references-v1'), 'codex-rs/hepta-contracts/src/authority_host_store.rs', ['RootAuthorityDirectory','HostAuthorityFrontierStore','DurableRecord']),
 (E2/'references', 'codex-rs/hepta-contracts/src/authority_host_peer.rs', ['HostAuthorityPeerChannel original framing']),
]
dependencies=[]
for base, name, symbols in dependencies_spec:
    path=base/name; raw=read(path)
    expected=state[name]['pin']
    assert pin(raw)==expected,(path,pin(raw),expected)
    dependencies.append({'path':str(path),'source_path':name,**pin(raw),
        'canonical_or_prior_layer':state[name]['origin'], 'reviewed_symbols_or_regions':symbols,
        'whole_file_hashed_but_not_claiming_full_semantic_review_of_unlisted_regions':True})

proof = {
 'format':'hepta-independent-material22-byte-and-control-flow-v1',
 'status':'PURE_STATIC_REVIEW_COMPLETE_NO_PROJECT_EXECUTION',
 'candidate':{'path':str(D/'SOURCE_PACKET.json'),**pin(packet_raw)},
 'manifest':{'path':str(D/'MANIFEST.json'),**pin(manifest_raw)},
 'canonical_inventory':{'path':str(INVENTORY),**pin(inventory_raw),'source':inventory['source']},
 'prior_layers':prior_proofs, 'candidate_files':file_proofs, 'metadata':metadata,
 'counts':{'source_paths':22,'new_paths':8,'modified_paths':14,'exact_replacements':23,
           'new_explicit_public_or_restricted_declarations':16,'new_test_methods_in_production_layer':0},
 'whole_patch_exact_reconstructed':True,
 'old_dataset_predicate_whole_file_equal_after_only_visibility_inverse':True,
 'old_material_pair_and_command_whole_files_equal_after_only_private_mount_inverse':True,
 'same_single_runtime_not_in_exported_handle':True,
 'three_original_owners_wrapped_exactly_once_and_handle_clones_same_arcs':True,
 'one_export_bit_not_reset':True, 'one_remote_channel_restore_after_all_checks':True,
 'ordering':ordering, 'dependencies':dependencies,
 'transport_bounds':{'frame_bytes':16384,'exact_request_bytes':frame_prefix,
   'maximum_payload_inside_response_bytes':16384-frame_prefix,'requests':128,'timeout_ms_max':500,
   'root_absolute_end_preserved':True,'client_aliases_share_counter_slot_end':True,
   'complete_content_over_bound_rejected_not_truncated':True},
 'explicit_declarations':actual_declarations,
 'not_claimed':['Rust compile/typecheck, including universal Send/Sync proof',
   'formatter, project QA or collector, tests, production IPC or Root loader completion',
   'physical termination at deadline, cancellation join, atomic global snapshot after response',
   'actual Source qualification, H execution, source/ref publication'],
 'storage':'LOCAL_COMPUTED_CONTENT_IDENTITIES_ONLY; Root owns publication',
}
encoded=(json.dumps(proof,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
with (OUT/'BYTE_AND_CONTROL_FLOW_PROOF.json').open('xb') as handle:
    handle.write(encoded)
print(json.dumps({'proof':pin(encoded),'source_paths':22,'replacements':23,'status':proof['status']},sort_keys=True))
