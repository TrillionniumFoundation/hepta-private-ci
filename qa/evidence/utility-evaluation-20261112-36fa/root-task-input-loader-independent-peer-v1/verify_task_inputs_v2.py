#!/usr/bin/env python3
"""Independent fixed-byte/static contract review; never imports project code."""
import difflib
import hashlib
import itertools
import json
import re
from pathlib import Path

D = Path('/tmp/hepta-36fa-root-task-cli-loader-proposal-v1/task-inputs-layer-v1')
C = Path('/tmp/hepta-36fa-root-product-composition-v6')
C5 = Path('/tmp/hepta-36fa-root-product-composition-v5')
O = Path('/tmp/hepta-36fa-root-task-input-loader-independent-review-v1')
P = 'codex-rs/hepta-agentd/src/'
I = Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')

def pin(b):
    return {'bytes': len(b), 'sha256': hashlib.sha256(b).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(b)).encode() + b'\0' + b).hexdigest()}

def read(path):
    path = Path(path)
    a = path.stat()
    b = path.read_bytes()
    z = path.stat()
    assert (a.st_dev, a.st_ino, a.st_size, a.st_mtime_ns, a.st_ctime_ns) == (z.st_dev, z.st_ino, z.st_size, z.st_mtime_ns, z.st_ctime_ns), str(path)
    assert len(b) == a.st_size, str(path)
    return b

def unique(pairs):
    d = {}
    for k, v in pairs:
        assert k not in d, ('duplicate JSON key', k)
        d[k] = v
    return d

def js(path):
    return json.loads(read(path), object_pairs_hook=unique)

def exact(path, want):
    b = read(path)
    assert pin(b) == want, (str(path), pin(b), want)
    return b

def block(s, start):
    # Fixed, manually inspected record/function bodies. Not a general Rust parser.
    p = s.index('{', start)
    depth, q = 1, p + 1
    while depth:
        depth += (s[q] == '{') - (s[q] == '}')
        q += 1
    return s[p + 1:q - 1], p, q

def declared_fields(s, name):
    m = list(re.finditer(r'\bstruct\s+' + re.escape(name) + r'\s*\{', s))
    assert len(m) == 1, (name, len(m))
    b, _, _ = block(s, m[0].start())
    return re.findall(r'^\s*(?:pub(?:\([^)]*\))?\s+)?([A-Za-z_]\w*)\s*:(?!:)', b, re.M)

def literal_fields(s, name):
    matches = list(re.finditer(r'\b' + re.escape(name) + r'\s*\{', s))
    matches = [m for m in matches if '->' not in s[s.rfind('\n', 0, m.start()) + 1:m.start()]]
    assert len(matches) == 1, (name, len(matches))
    b, _, _ = block(s, matches[0].start())
    pieces, at, depths = [], 0, [0, 0, 0]
    for i, ch in enumerate(b):
        if ch in '{([':
            depths['{(['.index(ch)] += 1
        elif ch in '})]':
            depths['})]'.index(ch)] -= 1
        elif ch == ',' and depths == [0, 0, 0]:
            pieces.append(b[at:i])
            at = i + 1
    pieces.append(b[at:])
    found = []
    for part in pieces:
        # All record-field values were manually read; generic commas can create
        # extra non-field pieces, which have no leading name followed by colon.
        m = re.match(r'\s*([A-Za-z_]\w*)\s*:(?!:)', part)
        if m:
            found.append(m.group(1))
    assert len(found) == len(set(found)), name
    return found

def ordered(s, needles):
    out, cursor = [], 0
    for needle in needles:
        at = s.index(needle, cursor)
        out.append({'text': needle, 'line': s[:at].count('\n') + 1})
        cursor = at + len(needle)
    return out

def line_refs(s, needle):
    return [{'line': i, 'text': line} for i, line in enumerate(s.splitlines(), 1) if needle in line]

want_packet = {'bytes': 386488, 'sha256': '5ef53c71c2809e99ce91337e2dc3fb49e3ecd4bb3f6360e4120ac4545b996bef', 'git_blob': '77b05d5ec3f8d3b10a4024b63103e97e8f3fe996'}
exact(D/'SOURCE_PACKET.json', want_packet)
packet, manifest = js(D/'SOURCE_PACKET.json'), js(D/'MANIFEST.json')
assert packet['base_commit'] == 'b6084394a4a38ab495c16eaba09e879f04a96f8e'
assert packet['format'] == 'full-before-after-utf8-v1'
assert manifest['source_packet'] == want_packet
assert len(packet['entries']) == 13
metadata = {}
for key, name in [('clock_consumers','CLOCK_CONSUMER_REVIEW.json'), ('mount_splices','FINAL_MOUNT_SPLICES.json'), ('public_record_fields','PUBLIC_RECORD_FIELD_MAP.json'), ('registration_obligations','REGISTRATION_OBLIGATIONS.json'), ('review','REVIEW.json'), ('source_delta','SOURCE_DELTA.patch'), ('source_references','SOURCE_REFERENCES.json'), ('static_byte_review','STATIC_BYTE_REVIEW.json')]:
    exact(D/name, manifest[key])
    metadata[name] = manifest[key]

inv_raw = read(I)
assert pin(inv_raw) == {'bytes':5631947,'sha256':'de044334afed8b804f2a997f8b8e8d16e6e1c596d2a5b3400c40f350229b054e','git_blob':'457adb9bf9ba3a844e9dfa149be49460bb306998'}
baseline = {r['path']:r for r in json.loads(inv_raw, object_pairs_hook=unique)['files']}
assert len(baseline) == 15243
composition_raw = read(C/'PREQUALIFICATION_COMPOSITION_REVIEW.json')
assert pin(composition_raw)['git_blob'] == 'cbf945f1d602aa8545d18a1a2c2fce72fcea755b'
composition = json.loads(composition_raw, object_pairs_hook=unique)
current = {r['path']:r for r in composition['files']}
assert len(current) == 100
entries = {r['path']:r for r in packet['entries']}
mf = {r['path']:r for r in manifest['files']}
assert len(entries) == 13 and set(entries) == set(mf)
splices = js(D/'FINAL_MOUNT_SPLICES.json')
sp = {r['path']:r for r in splices['changes']}
assert len(sp) == 7 and sum(len(s['splices']) for s in sp.values()) == 8
file_proof, patch, texts = [], [], {}
for p, e in entries.items():
    assert e['before'] == mf[p]['before'] and e['after'] == mf[p]['after']
    after = e['after_utf8'].encode()
    assert pin(after) == e['after'] and read(D/'after'/p) == after
    texts[p] = e['after_utf8']
    if e['before'] is None:
        assert e['before_utf8'] is None and p not in baseline and p not in current
        assert p not in sp and not (C/'after'/p).exists()
        before = b''
        row = {'path':p,'before':None,'after':e['after'],'absent_in_b608_and_v6':True}
    else:
        before = e['before_utf8'].encode()
        assert pin(before) == e['before']
        assert read(D/'before'/p) == before == read(C/'after'/p) == read(C5/'after'/p)
        assert current[p]['after'] == e['before']
        s = sp[p]
        assert s['before'] == e['before'] and s['after'] == e['after'] and s['exact_inverse'] is True
        forward = before.decode()
        for x in s['splices']:
            assert forward.count(x['anchor']) == 1
            forward = forward.replace(x['anchor'],x['anchor']+x['addition'],1)
        assert forward == e['after_utf8']
        backward = forward
        for x in reversed(s['splices']):
            target = x['anchor']+x['addition']
            assert backward.count(target) == 1
            backward = backward.replace(target,x['anchor'],1)
        assert backward == e['before_utf8']
        row = {'path':p,'before':e['before'],'after':e['after'],'v5_and_v6_exact_preimages':True,'insertions':s['splices'],'complete_forward_and_inverse_equal':True}
    file_proof.append(row)
    patch.extend(difflib.unified_diff(before.decode().splitlines(True),after.decode().splitlines(True),fromfile='a/'+p if e['before'] else '/dev/null',tofile='b/'+p))
assert sum(r['before'] is None for r in file_proof) == 6
assert ''.join(patch).encode() == read(D/'SOURCE_DELTA.patch')

refs = js(D/'SOURCE_REFERENCES.json')
reference_proof, reftexts = [], {}
for r in refs:
    want = {k:r[k] for k in ('bytes','sha256','git_blob')}
    body = exact(r['local'],want)
    old = baseline[r['path']]
    assert want == {'bytes':old['bytes'],'sha256':old['sha256'],'git_blob':old['working_blob']}
    assert old['matches_index'] and old['working_blob'] == old['index_blob']
    reftexts[r['path']] = body.decode()
    reference_proof.append({'path':r['path'],'local':r['local'],'pin':want,'complete_bytes_equal_b608':True,'scope':'content binding; not a claim of semantic reading of every line'})
extras = [
('/tmp/hepta-36fa-root-product-e3-proposal-v1/references/codex-rs/hepta-agentd/src/authority_host_config.rs',P+'authority_host_config.rs'),
('/tmp/hepta-36fa-root-product-e3-proposal-v1/references/codex-rs/hepta-agentd/src/cell_composed_q24_codec.rs',P+'cell_composed_q24_codec.rs'),
('/tmp/hepta-36fa-root-product-e2-proposal-v1/references/codex-rs/hepta-agentd/src/circuit_feature_current_control.rs',P+'circuit_feature_current_control.rs'),
]
for local, p in extras:
    b = read(local); old = baseline[p]
    want = {'bytes':old['bytes'],'sha256':old['sha256'],'git_blob':old['working_blob']}
    assert pin(b) == want
    reftexts[p] = b.decode()
    reference_proof.append({'path':p,'local':local,'pin':want,'complete_bytes_equal_b608':True})

model = texts[P+'authority_host_generation_task_model_types.rs']
types = texts[P+'authority_host_generation_task_input_types.rs']
record_map = js(D/'PUBLIC_RECORD_FIELD_MAP.json')
original_sources = {
 'CellDefinitionV1': 'codex-rs/hepta-neuron/src/cell_types.rs',
 'CellCandidateV1': 'codex-rs/hepta-neuron/src/cell_types.rs',
 'CellCandidateMaskV1': 'codex-rs/hepta-neuron/src/cell_types.rs',
 'CellScopeV1': 'codex-rs/hepta-neuron/src/cell_types.rs',
 'NeuronRuntimeConfigV1': 'codex-rs/hepta-neuron/src/runtime_types.rs',
 'NeuronCalibrationProfileV1': 'codex-rs/hepta-neuron/src/runtime_types.rs',
 'NeuronResourceEnvelopeV1': 'codex-rs/hepta-neuron/src/runtime_types.rs',
 'SparseConfig': 'codex-rs/hepta-neuron/src/sparse.rs',
 'InhibitoryEdge': 'codex-rs/hepta-neuron/src/sparse.rs',
 'CellCompatibilityBundleV1': 'codex-rs/hepta-learning-artifacts/src/cell_bundle.rs',
 'CellBundleComponentsV1': 'codex-rs/hepta-learning-artifacts/src/cell_bundle.rs',
 'CellTrainingLineageV1': 'codex-rs/hepta-learning-artifacts/src/cell_bundle.rs',
 'CircuitTaskSourceInputV1': P+'circuit_task_source.rs',
 'CircuitCellRouteV1': P+'circuit_cell_binding.rs',
}
record_proof = []
for row in record_map:
    name = row['original_type']
    source = original_sources[name]
    declared = declared_fields(reftexts[source],name)
    constructed = literal_fields(model+'\n'+types,name)
    assert declared == constructed == row['original_fields'], (name,declared,constructed,row['original_fields'])
    record_proof.append({'original_type':name,'source':source,'source_pin':pin(reftexts[source].encode()),'fields':declared,'field_count':len(declared),'full_original_declaration_equals_explicit_constructor':True})
assert len(record_proof) == 14 and sum(x['field_count'] for x in record_proof) == 109
for source in (model,types):
    for m in re.finditer(r'\bstruct\s+(\w+)\s*\{',source):
        if m[1] == 'RootHostQ24TaskFilesV1':
            continue
        assert '#[serde(deny_unknown_fields)]' in source[max(0,m.start()-120):m.start()], m[1]

loader = texts[P+'authority_host_generation_task_input_loader.rs']
wrapper = texts[P+'authority_host_session_generation_task_loader.rs']
clock = texts[P+'authority_host_generation_task_clock.rs']
files = texts[P+'authority_host_generation_task_input_files.rs']
public_methods = re.findall(r'\bpub fn (\w+)\s*(?:<|\()',wrapper)
assert public_methods == ['read_loaded_original_root_task_generation','prepare_original_root_task_from_files','recover_original_root_task_from_files']
assert re.findall(r'\bpub fn (\w+)\s*(?:<|\()',loader) == []
for forbidden in ['impl Clone','impl Deref','impl AsRef','into_inner','pub task:','pub clock_status:','pub fn clock','pub fn runtime','pub fn owner','Config::','AutomationStore::','tokio::spawn','std::thread::spawn','try_clone(']:
    assert forbidden not in loader+wrapper+clock+files, forbidden
assert 'task: PreparedRootHostCircuitTaskV1<FileAnchorWitnessStore, FileAnchorWitnessStore>' in wrapper
assert 'clock_status: OriginalTaskClockStatus' in wrapper
assert wrapper.count('HostAuthorityService::load_original_root_q24_task_inputs(') == 1
assert wrapper.count('PreparedRootHostInitialGenerationV1::prepare_original_root_task(self, loaded.inputs)?') == 1
assert 'into_original_q24_task(' not in loader+wrapper
assert 'CircuitQ24TaskRuntimeV1::install' not in loader+wrapper
assert 'pub(crate) struct LoadedOriginalTaskInputs' in loader
assert 'pub(crate) fn load_original_root_q24_task_inputs' in loader

clock_calls = ordered(loader,[
 'let original_clock = Arc::clone(&self.clock);',
 'let clock_status = OriginalTaskClockStatus::new(end);',
 'let callback_status = clock_status.clone();',
 'if callback_status.require_healthy().is_err()',
 'let circuit_millis = match original_clock.now_unix_ms()',
 'callback_status.record_original_error(error);',
 'let Some(cell_micros) = circuit_millis.checked_mul(1000)',
 'callback_status.record_overflow();',
 'if callback_status.require_healthy().is_err()',
 'CircuitCellTimeV1 { circuit_millis, cell_micros }',
])
assert clock.count('compare_exchange(') == 1
assert 'compare_exchange(0, code, Ordering::AcqRel, Ordering::Acquire)' in clock
for forbidden in ['.store(','.swap(','.fetch_','compare_exchange_weak','AtomicU8::new(1)','unsafe']:
    assert forbidden not in clock
assert clock.count('AtomicU8::new(0)') == 1
assert 'if Instant::now() >= self.end { self.record(5); }' in clock
assert 'first_failure.load(Ordering::Acquire)' in clock
assert all('AuthorityTrustError::'+name+' => '+str(n) in clock for n,name in enumerate(['Invalid','Conflict','Unavailable'],1))
cas_examples=[]
for seq in itertools.permutations(range(1,6)):
    value=0
    for cause in seq:
        if value==0:
            value=cause
    assert value==seq[0]
    cas_examples.append({'attempt_order':seq,'retained':value})

guard_order = {
 'protected_data_and_materials': ordered(loader,[
    'require_before(end)?;', 'read_root_json(deployment)?;',
    'files::require_descriptors(&original_files, purpose)?;',
    'value.definition.into_original()?;', 'value.source.into_original()?;',
    'value.bundle.into_original()?;', 'value.fence.into_original()?;',
    'let now = self.clock.now_unix_ms().map_err(invalid)?;',
    'LoadedCellQ24ModelV1::open_files(model)',
    'model.components() != &bundle.components',
    'FileAnchorWitnessStore::open(', 'FileAnchorWitnessStore::open(',
    'DurableInferenceControl::open_file(', 'OriginalTaskClockStatus::new(end)',
 ]),
 'ready_precedes_all_input_opening': ordered(wrapper,[
    'require_original_session(&self.session, self.end)?;',
    'let InitialHostPhase::Ready(custody) = &self.phase',
    'OriginalHostInitialOperation::require_observed(',
    'HostAuthorityService::load_original_root_q24_task_inputs(',
    'OriginalHostInitialOperation::require_observed(',
    'require_original_session(&self.session, self.end)?;',
    'PreparedRootHostInitialGenerationV1::prepare_original_root_task(self, loaded.inputs)?',
    'Ok(PreparedRootHostLoadedQ24TaskV1 { task, clock_status: loaded.clock_status })',
 ]),
 'returned_readback_both_sides_checked': ordered(wrapper,[
    'self.clock_status.require_healthy()?;',
    'PreparedRootHostCircuitTaskV1::read_original_root_task_generation(&self.task)',
    'self.require_original_result(result)',
 ]),
}
assert '(Err(error), Err(clock)) => Err(AgentdError::Protocol(format!(' in wrapper
assert 'failure: OriginalInstallationFailure::Host(error)' in wrapper
assert 'TaskFilePurpose::Create => CircuitQ24TaskOpenModeV1::Create' in loader
assert 'TaskFilePurpose::Recover => CircuitQ24TaskOpenModeV1::Recover' in loader
assert 'purpose == TaskFilePurpose::Recover' in files
for exact_guard in ['metadata.uid() != 0','metadata.mode() & 0o7777 != 0o600','metadata.nlink() != 1','!identities.insert((metadata.dev(), metadata.ino()))','libc::F_GETFL','flags & libc::O_ACCMODE != mode','flags & libc::O_APPEND != append','files.source_journal.metadata()?.len() == 0','files.cell_journal.metadata()?.len() == 0','files.source_witness.metadata()?.len() < 112','files.cell_witness.metadata()?.len() < 112']:
    assert exact_guard in files, exact_guard
assert files.count('Access::ReadAppend)') == 1
assert 'File::open' not in files and 'OpenOptions' not in files
assert 'let control = Self::replay_file(file, path, capacity)?;' in reftexts['codex-rs/hepta-infer-core/src/durable_control.rs']
assert 'Self::replay_file(file, path, capacity)' in reftexts['codex-rs/hepta-infer-core/src/durable_control.rs']

consumer_author=js(D/'CLOCK_CONSUMER_REVIEW.json')
consumer_references=[]
for r in consumer_author['references']:
    want={k:r[k] for k in ('bytes','sha256','git_blob')}
    raw=exact(C/'after'/r['path'],want)
    assert current[r['path']]['after']==want
    consumer_references.append({'path':r['path'],'pin':want,'exact_v6':True})

# Complete changed-file view plus the candidate's six new files. This is a
# static source reference enumeration, not a compiler name-resolution proof.
view={p:read(C/'after'/p).decode() for p in current}
view.update(texts)
assert len(view)==106
terms=['LoadedOriginalTaskInputs','load_original_root_q24_task_inputs','PreparedRootHostLoadedQ24TaskV1','OriginalTaskClockStatus','prepare_original_root_task_from_files','recover_original_root_task_from_files']
occurrences={term:[] for term in terms}
for term in terms:
    for path,text in sorted(view.items()):
        for row in line_refs(text,term):
            occurrences[term].append({'path':path,**row})
assert {x['path'] for x in occurrences['LoadedOriginalTaskInputs']} == {P+'authority_host_generation_task_input_loader.rs'}
assert {x['path'] for x in occurrences['load_original_root_q24_task_inputs']} == {P+'authority_host_generation_task_input_loader.rs',P+'authority_host_session_generation_task_loader.rs'}
for method in ['prepare_original_root_task_from_files','recover_original_root_task_from_files']:
    assert len(occurrences[method])==1

# Constructor callback use is storage only. The owner-loop's local execution
# remains unstrengthened and is inaccessible through this layer's wrapper.
channel=view[P+'circuit_task_runtime.rs']
prefix=channel[channel.index('pub fn circuit_task_channel_v1'):channel.index('owner: Box::new(move |store, state, cancellation|')]
assert 'clock()' not in prefix and 'clock,' in prefix
feature=view['codex-rs/hepta-neuron/src/feature_control.rs']
ctor,_,_=block(feature,feature.index('pub fn new('))
assert '(clock)()' not in ctor and '(self.clock)()' not in ctor
assert 'clock,' in ctor
published=reftexts[P+'circuit_feature_current_control.rs']
assert 'let guarded_clock = Arc::new(move || {' in published
assert 'ControlledNeuronFeaturePortV1::new(' in published
assert 'guarded_clock,' in published
assert consumer_author['required_layers'] == {'feature_clock':'ade9282388680285416c7829000b7081e22550ef','remote_clock':'9f780f963b0e9585b5b85a83f87de593f604bfa5'}

output={
 'format':'hepta-independent-task-input-loader-byte-and-contract-review-v1',
 'state':'STATIC_FIXED_SOURCE_ONLY_NO_PROJECT_EXECUTION_NO_H_NO_GIT_WRITE',
 'candidate':want_packet,'manifest':pin(read(D/'MANIFEST.json')),
 'metadata_complete_byte_bindings':metadata,
 'composition_v6':pin(composition_raw),'baseline_inventory':pin(inv_raw),
 'files':file_proof,'counts':{'files':13,'new':6,'old':7,'exact_insertions':8,'public_records':14,'public_record_fields':109,'fixed_changed_view_files':106,'original_reference_files':len(reference_proof)},
 'final_splice_table':'FINAL_MOUNT_SPLICES.json; original intermediate MOUNT_SPLICES is retained but not used as the final source contract',
 'source_delta_exact':True,'original_references':reference_proof,
 'records':record_proof,'guards':guard_order,
 'public_methods':public_methods,'new_symbol_references':occurrences,
 'clock_callback_order':clock_calls,'clock_consumer_v6_bindings':consumer_references,
 'clock_first_failure':{'exact_one_nonresetting_compare_exchange':True,'one_zero_initialization_only':True,'pure_transition_permutations':len(cas_examples),'examples':cas_examples,'scope':'stdlib arithmetic on the inspected CAS transition; not execution of Rust atomics or a concurrency test; first successful CAS wins'},
 'constructor_clock_observation':'Original profile/control/channel only store the callback in construction; the active sampling resides in later owner execution. This layer has no serving/Config installation entry and returns only the opaque wrapper.',
 'limitations':['No Rust compilation, formatter, QA/collector, test, model inference, original owner execution, native/H call, source or ref writes.','No claim of full CLI/orchestration completion or IPC/cold-recovery success.','Old local Cell/runtime remain unchanged and not claimed MAX-safe; later assembly must stay in this private subtree and use the reviewed remote path.','Descriptor checks establish exact current role metadata and pairwise identities, not global absence of dup descriptors or physical cross-owner atomicity.','Original witness/journal recovery may change durable state before a later refusal; error is not no-effect or permission for retry.','Postcondition deadline checks cannot guarantee interrupting a blocking OS call at the exact deadline.','This reference enumeration is for the complete frozen changed view plus relevant original reference chain, not arbitrary future Rust consumers.'],
}
raw=(json.dumps(output,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
with (O/'BYTE_AND_CONTRACT_PROOF.json').open('xb') as f:
    f.write(raw)
print(json.dumps({'ok':True,'output':str(O/'BYTE_AND_CONTRACT_PROOF.json'),'pin':pin(raw),'counts':output['counts']},ensure_ascii=False))
