#!/usr/bin/env python3
"""Pure local byte/schema review. Never imports or executes project code."""
import difflib
import hashlib
import json
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent
E1 = Path('/tmp/hepta-36fa-root-product-e1-proposal-v1')
E2 = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')
LAYER = E2 / 'ordinary-handoff-layer-v1'
INVENTORY = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')
PREFIX = 'codex-rs/hepta-agentd/src/'

def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode('ascii') + b'\0' + raw).hexdigest()}

def stable_read(path):
    path = Path(path)
    first = path.stat()
    raw = path.read_bytes()
    last = path.stat()
    assert (first.st_dev, first.st_ino, first.st_size, first.st_mtime_ns, first.st_ctime_ns) == (
        last.st_dev, last.st_ino, last.st_size, last.st_mtime_ns, last.st_ctime_ns), path
    assert len(raw) == last.st_size
    return raw

def exact_object(raw):
    def pairs(rows):
        result = {}
        for key, value in rows:
            assert key not in result, key
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)

def normalized_entries(obj):
    if 'images' not in obj:
        return obj['entries']
    identities = {row['path']: row for row in obj['manifest']['entries']}
    assert len(identities) == len(obj['manifest']['entries']) == len(obj['images'])
    result = []
    for image in obj['images']:
        identity = identities[image['path']]
        result.append(dict(identity, before_utf8=image['before'], after_utf8=image['after']))
    return result

raw_inventory = stable_read(INVENTORY)
assert pin(raw_inventory) == {
    'bytes': 5631947,
    'sha256': 'de044334afed8b804f2a997f8b8e8d16e6e1c596d2a5b3400c40f350229b054e',
    'git_blob': '457adb9bf9ba3a844e9dfa149be49460bb306998'}
inventory = exact_object(raw_inventory)
assert inventory['source'] == {'head': 'b6084394a4a38ab495c16eaba09e879f04a96f8e',
    'tree': '8ebb37e523ad3932a58cf016af0a9f4e0eeb6638', 'status': ''}
rows = {row['path']: row for row in inventory['files']}
assert len(rows) == len(inventory['files']) == 15243
state = {name: {'pin': {'bytes': row['bytes'], 'sha256': row['sha256'], 'git_blob': row['working_blob']},
                'mode': row['index_mode'], 'origin': str(INVENTORY), 'raw': None}
         for name, row in rows.items()}

prior_layers = [
    (E1/'assembled-source-v1/SOURCE_PACKET.json', '1ca7a06948fcae69bf7c8e4c7823627a872c0c62'),
    (E1/'request-type-import-increment-v1/SOURCE_PACKET.json', '36cd9a693ce75070e1225a978575ca6dea5f72c2'),
    (E2/'factory-split-layer-v1/SOURCE_PACKET.json', '62ad5a5363ca91c335f2d599128f763c355b33bf'),
    (E2/'factory-test-refusal-increment-v1/SOURCE_PACKET.json', '12459a8255be0358c822a825d2445fa48828a7e1'),
    (E2/'ipc-layer-v1/SOURCE_PACKET.json', '06dafdbdeb53eb5ccf6480993596bbb4d939f203'),
    (E2/'ipc-purpose-increment-v1/SOURCE_PACKET.json', '69d6d5eda401ff59f7e89b1e659f77a431274248'),
]
layer_proofs = []
for path, expected_blob in prior_layers:
    raw = stable_read(path)
    identity = pin(raw)
    assert identity['git_blob'] == expected_blob, path
    entries = normalized_entries(exact_object(raw))
    names = set()
    origins = []
    for entry in entries:
        name = entry['path']
        assert name not in names and name.startswith(PREFIX) and entry['mode'] == '100644'
        names.add(name)
        before = entry['before_utf8']
        if before is None:
            assert entry['before'] is None and name not in state, (path, name, 'new collision')
            origin = None
        else:
            before = before.encode('utf-8')
            assert pin(before) == entry['before'] == state[name]['pin'], (path, name)
            assert state[name]['mode'] == entry['mode']
            if state[name]['raw'] is not None:
                assert before == state[name]['raw']
            origin = state[name]['origin']
        after = entry['after_utf8'].encode('utf-8')
        assert pin(after) == entry['after'], (path, name)
        state[name] = {'pin': entry['after'], 'mode': entry['mode'], 'origin': str(path), 'raw': after}
        origins.append({'path': name, 'preimage_origin': origin, 'before': entry['before'], 'after': entry['after']})
    layer_proofs.append({'path': str(path), **identity, 'entries': origins})

packet_raw = stable_read(LAYER/'SOURCE_PACKET.json')
assert pin(packet_raw) == {'bytes': 556937,
    'sha256': '37dd57a99c5ca3c029e4d8a41fd3e4d0a221559cd33245a21a610946139395cc',
    'git_blob': '65e62f807885cd890d8fa9944c58e232dc55ae01'}
packet = exact_object(packet_raw)
entries = packet['entries']
assert len(entries) == 26 and len({row['path'] for row in entries}) == 26
assert packet['canonical_base_commit'] == inventory['source']['head']
assert packet['canonical_base_tree'] == inventory['source']['tree']
manifest_raw = stable_read(LAYER/'MANIFEST.json')
manifest = exact_object(manifest_raw)
assert manifest['packet'] == pin(packet_raw)
assert manifest['entries'] == [{k: e[k] for k in ('path','mode','before','after')} for e in entries]
metadata = []
for field, name in [('patch','SOURCE_DELTA.patch'), ('splices','EXACT_SOURCE_SPLICES.json'),
                    ('review','REVIEW.json'), ('proof','BYTE_AND_STARTUP_PROOF.json')]:
    raw = stable_read(LAYER/name)
    assert pin(raw) == manifest[field], (field, pin(raw), manifest[field])
    metadata.append({'path': str(LAYER/name), **pin(raw)})
splices = exact_object(stable_read(LAYER/'EXACT_SOURCE_SPLICES.json'))
assert len(splices) == 40
assert {x['path'] for x in splices} == {x['path'] for x in entries if x['before'] is not None}
current_proofs = []
patches = []
source = {}
old_source = {}
for entry in entries:
    name = entry['path']
    assert name.startswith(PREFIX) and entry['mode'] == '100644'
    after = entry['after_utf8'].encode('utf-8')
    assert pin(after) == entry['after'] and stable_read(LAYER/'after'/name) == after
    source[name] = after
    before = entry['before_utf8']
    if before is None:
        assert entry['before'] is None and name not in state and name not in rows
        assert not (LAYER/'before'/name).exists()
        before_raw = b''
        origin = None
        count = 0
    else:
        before_raw = before.encode('utf-8')
        old_source[name] = before_raw
        assert pin(before_raw) == entry['before'] == state[name]['pin'], name
        assert stable_read(LAYER/'before'/name) == before_raw
        if state[name]['raw'] is not None:
            assert before_raw == state[name]['raw'], name
        assert entry['mode'] == state[name]['mode']
        own = [x for x in splices if x['path'] == name]
        forward = before_raw
        for change in own:
            left, right = change['before'].encode(), change['after'].encode()
            assert forward.count(left) == 1, (name, 'forward', left)
            forward = forward.replace(left, right, 1)
        assert forward == after, name
        inverse = after
        for change in reversed(own):
            left, right = change['before'].encode(), change['after'].encode()
            assert inverse.count(right) == 1, (name, 'inverse', right)
            inverse = inverse.replace(right, left, 1)
        assert inverse == before_raw
        origin = state[name]['origin']
        count = len(own)
    patches.extend(difflib.unified_diff(before_raw.decode().splitlines(keepends=True),
        after.decode().splitlines(keepends=True), fromfile='a/'+name if before is not None else '/dev/null',
        tofile='b/'+name))
    current_proofs.append({'path':name, 'mode':entry['mode'], 'before':entry['before'], 'after':entry['after'],
        'preimage_origin':origin, 'new_path_absent_from_b608_and_all_prior_layers':before is None,
        'exact_splice_count':count, 'full_forward_and_inverse':before is not None,
        'local_before_and_after_match_embedded_bytes':True})
assert ''.join(patches).encode() == stable_read(LAYER/'SOURCE_DELTA.patch')
assert sum(x['before'] is None for x in entries) == 9
assert sum(x['exact_splice_count'] for x in current_proofs) == 40

# Mechanical extraction: compare the entire old inner decoder including its
# final canonical re-encode, not a handful of guard strings.
codec_name = PREFIX+'circuit_task_source_codec.rs'
old_codec, new_codec = old_source[codec_name], source[codec_name]
start = b'    let mut r = Reader(encoded);\n'
end = b'\npub(super) fn result('
old_start = old_codec.index(start)
new_start = new_codec.index(start)
old_end = old_codec.index(end, old_start)
new_end = new_codec.index(end, new_start)
old_inner, new_inner = old_codec[old_start:old_end], new_codec[new_start:new_end]
assert old_inner == new_inner
old_encoder = old_codec[old_codec.index(b'fn encode_input('):old_codec.index(b'pub(super) fn decode_input(')]
new_encoder = new_codec[new_codec.index(b'fn encode_input('):new_codec.index(b'pub(super) fn decode_input(')]
assert old_encoder == new_encoder

# Hash canonical dependencies actually read during this independent review.
dependency_names = [
 'codex-rs/hepta-agentd/src/authority_host_listeners.rs',
 'codex-rs/hepta-agentd/src/authority_host_bootstrap.rs',
 'codex-rs/hepta-agentd/src/authority_host_bootstrap_seal.rs',
 'codex-rs/hepta-agentd/src/root_production_handoff.rs',
 'codex-rs/hepta-agentd/src/circuit_cell_binding.rs',
 'codex-rs/hepta-agentd/src/circuit_task_source_codec.rs',
 'codex-rs/hepta-contracts/src/authority_host_peer.rs',
 'codex-rs/hepta-contracts/src/authority_host_channel.rs',
 'codex-rs/hepta-neuron/src/cell_types.rs',
 'codex-rs/hepta-neuron/src/runtime_types.rs',
 'codex-rs/hepta-neuron/src/sparse.rs',
]
dependencies = []
for name in dependency_names:
    path = E2/'references'/name
    raw = stable_read(path)
    row = rows[name]
    expected = {'bytes':row['bytes'], 'sha256':row['sha256'], 'git_blob':row['working_blob']}
    assert pin(raw) == expected, (name,pin(raw),expected)
    dependencies.append({'path':str(path), 'canonical_path':name, **expected})

def struct_fields(raw, name):
    pattern = rb'pub struct ' + name.encode() + rb'\s*\{([^}]*)\}'
    matches = re.findall(pattern, raw, flags=re.S)
    assert len(matches) == 1, name
    return re.findall(rb'(?m)^\s*pub (\w+):', matches[0])

cell_source = source[PREFIX+'circuit_task_root_bootstrap_cell.rs']
field_checks=[]
for rel, name in [
 ('cell_types.rs','CellDefinitionV1'), ('cell_types.rs','CellCandidateV1'),
 ('runtime_types.rs','NeuronRuntimeConfigV1'), ('runtime_types.rs','NeuronCalibrationProfileV1'),
 ('runtime_types.rs','NeuronResourceEnvelopeV1'), ('sparse.rs','SparseConfig'), ('sparse.rs','InhibitoryEdge')]:
    raw = stable_read(E2/'references/codex-rs/hepta-neuron/src'/rel)
    fields = struct_fields(raw,name)
    # Field-name occurrence is a structural cross-check; human review separately
    # checks codec order and original semantic validation. It is not Rust execution.
    for field in fields:
        assert re.search(rb'\b'+field+rb'\b',cell_source), (name,field)
    field_checks.append({'type':name,'canonical_fields':[x.decode() for x in fields],
        'all_field_names_present_in_full_cell_codec':True})

# Exact ordered anchors in the new integration. These substantiate the review;
# they do not replace full control-flow reading or claim runtime completion.
def ordered(name, anchors):
    raw=source[PREFIX+name]
    cursor=0; report=[]
    for anchor in anchors:
        value=anchor.encode()
        offset=raw.index(value,cursor)
        report.append({'anchor':anchor,'line':raw[:offset].count(b'\n')+1,'offset':offset})
        cursor=offset+len(value)
    return {'path':PREFIX+name,'ordered_anchors':report}

ordering = [
 ordered('authority_host_session_generation_task_handoff.rs',[
  'let startup_end = (Instant::now() + Duration::from_secs(30)).min(self.end);',
  'let lane = self.runtime.take_original_root_lane()?;',
  'let bound = listeners::TaskListeners::bind(',
  'let original_host = self.session.bind_original_task_host_lanes()?;',
  'crate::send_root_production_handoff(',
  'crate::root_production_handoff::send_original_task_handoff(',
  'let host = scope.spawn(move || original_host.serve());',
  'bound.accept(&root.session.owner_pidfd, startup_end)?',
  'listeners::wait_first_frame(task_fd, &root.session.owner_pidfd, startup_end)?;',
  'OriginalRootTaskStreams::new(task, loan, session_nonce, end)',
  'let host_result = host.join()']),
 ordered('production_launcher.rs',[
  'config.prepare_root_handoff(uid, gid)?.drop_to_owner()?;',
  'crate::receive_root_production_handoff(',
  'crate::receive_root_original_task_handoff(handoff, remaining(bootstrap_deadline)?)']),
 ordered('main.rs',[
  'config = launch.install_original_root_task(config).await?;',
  'launch.run(config, arg0_paths).await'])
]
root_handoff = stable_read(E2/'references'/PREFIX/'root_production_handoff.rs')
old_marker = re.search(rb'const FRAME: &\[u8\] = b"([^"]+)";',root_handoff)
new_handoff = source[PREFIX+'root_original_task_handoff.rs']
new_marker = re.search(rb'const TASK_FRAME: &\[u8\] = b"([^"]+)";',new_handoff)
assert old_marker and new_marker and old_marker[1] != new_marker[1]

proof = {
 'format':'hepta-e2-ordinary-handoff-independent-byte-review-v1',
 'status':'PURE_STATIC_BYTE_AND_SCHEMA_CHECKS_COMPLETE',
 'packet':{'path':str(LAYER/'SOURCE_PACKET.json'),**pin(packet_raw)},
 'manifest':{'path':str(LAYER/'MANIFEST.json'),**pin(manifest_raw)},
 'canonical_inventory':{'path':str(INVENTORY),**pin(raw_inventory),'source':inventory['source']},
 'prior_layers':layer_proofs,
 'metadata':metadata,
 'entries':current_proofs,
 'counts':{'source_paths':26,'modified':17,'new':9,'exact_splices':40},
 'full_patch_reproduced':True,
 'source_codec':{'inner_decode_verbatim':True,'inner_decode_pin':pin(old_inner),
   'encoder_except_visibility_verbatim':True,'encoder_pin':pin(old_encoder)},
 'canonical_dependencies':dependencies,
 'complete_cell_struct_field_presence':field_checks,
 'ordered_integration_anchors':ordering,
 'markers':{'production':old_marker[1].decode(),'task':new_marker[1].decode(),'distinct':True},
 'limits':{'no_project_import_or_execution':True,'no_rust_compilation':True,'no_fmt_or_fix':True,
    'no_QA_or_tests':True,'no_H_calls':True,'no_source_tree_or_ref_changes':True,
    'local_file_stability_only':True,'no_live_source_preservation_claim':True,
    'payload_and_report_git_blobs_are_computed_content_identities':True},
}
out_raw=(json.dumps(proof,sort_keys=True,indent=2,ensure_ascii=False)+'\n').encode()
destination=OUT/'BYTE_AND_PREIMAGE_REVIEW.json'
with destination.open('xb') as handle:
    handle.write(out_raw)
print(json.dumps({'result':'complete','report':str(destination),**pin(out_raw),
                  'counts':proof['counts'],'source_codec_inner_bytes':len(old_inner)}))
