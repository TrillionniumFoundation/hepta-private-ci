#!/usr/bin/env python3
"""Static source data only. No project imports, compilation or runtime tests."""
from pathlib import Path
import difflib
import hashlib
import itertools
import json
import re

D=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')
C=Path('/tmp/hepta-36fa-root-product-composition-v5')
O=Path('/tmp/hepta-36fa-clock-rejection-independent-review-v1')
I=Path('/tmp/hepta-36fa-coordinator-a489-canonical-inventory-exact-recovery-v1/SOURCE.final.inventory.exact_recovered.json')
P='codex-rs/hepta-agentd/src/'
N='codex-rs/hepta-neuron/src/'

def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def rd(p):
    p=Path(p);a=p.stat();b=p.read_bytes();z=p.stat()
    assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns)==(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns,z.st_ctime_ns)
    assert len(b)==a.st_size
    return b
def pairs(items):
    d={}
    for k,v in items:
        assert k not in d,k
        d[k]=v
    return d
def js(p):return json.loads(rd(p),object_pairs_hook=pairs)
def save(n,x):
    b=(json.dumps(x,sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode()
    with (O/n).open('xb') as f:f.write(b)
    return pin(b)
def anchors(s,items):
    at=0;out=[]
    for t in items:
        i=s.index(t,at);out.append({'text':t,'line':s[:i].count('\n')+1});at=i+len(t)
    return out

assert pin(rd(I))['git_blob']=='457adb9bf9ba3a844e9dfa149be49460bb306998'
base={r['path']:r for r in js(I)['files']}
cr=C/'PREQUALIFICATION_COMPOSITION_REVIEW.json'
assert pin(rd(cr))['git_blob']=='59014cde8a2ed41b652260773f81e09d7e3f67eb'
composed={r['path']:r for r in js(cr)['files']}
assert len(composed)==98
layers=[
('remote-clock-rejection-increment-v1','9f780f963b0e9585b5b85a83f87de593f604bfa5',66844,4,7),
('feature-clock-rejection-increment-v1','ade9282388680285416c7829000b7081e22550ef',27556,1,1),
('feature-clock-regression-tests-v1','b2dc4c80ce5918463f3713fd6d916f0aeb1c85c0',28419,1,1),
]
allfiles=[];layerproof=[];after={};before={};own_sources={}
for name,g,b,n,k in layers:
    d=D/name
    raw=rd(d/'SOURCE_PACKET.json');ident=pin(raw)
    assert ident['git_blob']==g and len(raw)==b
    packet=json.loads(raw,object_pairs_hook=pairs);m=js(d/'MANIFEST.json');sp=js(d/'EXACT_SOURCE_SPLICES.json')
    assert packet['format']=='hepta-e2-exact-source-increment-v1'
    assert packet['execution']=='Not formatted, compiled, tested or executed.'
    assert m['source_paths']==n and len(packet['entries'])==n and len(sp)==n
    assert m['git_source_written'] is False and m['rust_or_project_qa_executed'] is False
    metadata=[]
    for row in m['files']:
        p=rd(d/row['path']);assert pin(p)=={x:row[x] for x in ['bytes','sha256','git_blob']}
        metadata.append({'local':str(d/row['path']),'pin':pin(p)})
    sm={r['path']:r for r in sp};mm={r['path']:r for r in m['source_images']}
    assert sum(len(x['exact_splices']) for x in sp)==k
    patch=[];files=[]
    for e in packet['entries']:
        p=e['path'];a=e['after_utf8'].encode();b=e['before_utf8'].encode()
        assert pin(a)==e['after']==sm[p]['after']==mm[p]['after']
        assert pin(b)==e['before']==sm[p]['before']==mm[p]['before']
        assert rd(d/'after'/p)==a and rd(d/'before'/p)==b
        if p in composed:
            assert composed[p]['after']==e['before'] and rd(C/'after'/p)==b
            baseline='exact-v5-composed-file'
        else:
            r=base[p]
            assert e['before']=={'bytes':r['bytes'],'sha256':r['sha256'],'git_blob':r['working_blob']}
            assert r['matches_index'] is True and r['working_blob']==r['index_blob']
            baseline='unchanged-original-b608-file'
        applied=b.decode()
        inverse=a.decode()
        for x in sm[p]['exact_splices']:
            assert applied.count(x['old'])==1,(p,'old anchor')
            applied=applied.replace(x['old'],x['new'],1)
        for x in reversed(sm[p]['exact_splices']):
            assert inverse.count(x['new'])==1,(p,'new anchor')
            inverse=inverse.replace(x['new'],x['old'],1)
        assert applied.encode()==a and inverse.encode()==b
        assert sm[p]['reverse_full_bytes_equal'] is True
        files.append({'path':p,'before':e['before'],'after':e['after'],'baseline':baseline,
                      'splice_count':len(sm[p]['exact_splices']),'forward_and_reverse_complete_bytes_equal':True})
        assert p not in after
        after[p]=a.decode();before[p]=b.decode();own_sources[p]={'local':str(d/'after'/p),'pin':pin(a)}
        patch.extend(difflib.unified_diff(b.decode().splitlines(True),a.decode().splitlines(True),fromfile='a/'+p,tofile='b/'+p))
    assert ''.join(patch).encode()==rd(d/'source.patch')
    layerproof.append({'name':name,'packet':ident,'manifest':pin(rd(d/'MANIFEST.json')),'metadata':metadata,'files':files,'exact_patch_reconstructed':True})
    allfiles+=files
assert len(allfiles)==6 and sum(x['splice_count'] for x in allfiles)==9

refspec=[
(C/'after'/(P+'circuit_task_root_lane.rs'),P+'circuit_task_root_lane.rs'),
(C/'after'/(P+'circuit_task_cell_port.rs'),P+'circuit_task_cell_port.rs'),
(C/'after'/(P+'circuit_task_driver.rs'),P+'circuit_task_driver.rs'),
(C/'after'/(P+'circuit_task_runtime.rs'),P+'circuit_task_runtime.rs'),
(C/'after'/(P+'circuit_cell.rs'),P+'circuit_cell.rs'),
(C/'after'/(P+'circuit_task_remote_wire.rs'),P+'circuit_task_remote_wire.rs'),
(C/'after'/(P+'circuit_task_remote_admission.rs'),P+'circuit_task_remote_admission.rs'),
(D/'references'/(P+'circuit_cell_dispatch.rs'),P+'circuit_cell_dispatch.rs'),
(D/'references'/(N+'cell_inference.rs'),N+'cell_inference.rs'),
(D/'references'/(N+'cell.rs'),N+'cell.rs'),
(D/'references'/(N+'cell_types.rs'),N+'cell_types.rs'),
]
refs=[];texts={}
for f,p in refspec:
    b=rd(f);ident=pin(b)
    if p in composed:
        assert composed[p]['after']==ident
    else:
        r=base[p];assert ident=={'bytes':r['bytes'],'sha256':r['sha256'],'git_blob':r['working_blob']}
    refs.append({'path':p,'local':str(f),'pin':ident,'baseline':'v5' if p in composed else 'b608'})
    texts[p]=b.decode()

cell=after[P+'circuit_cell_remote.rs'];feature=after[N+'feature_control.rs']
flows=[]
def flow(name,path,needles,explanation):
    src=after.get(path,texts.get(path))
    assert src is not None
    a=anchors(src,needles)
    flows.append({'name':name,'path':path,'source_pin':pin(src.encode()),'ordered_anchors':a,'meaning':explanation})

flow('remote first sample',P+'circuit_cell_remote.rs',[
'let time = clock();','time.circuit_millis == u64::MAX','time.cell_micros == u64::MAX',
'return Err(CircuitCellErrorV1::ReconciliationRequired);','let read_only =','let committed =',
'let pending = self.state_owner.pending_inference(&input.scope)?;','recover_cell_inference(',
'if read_only','enter_cell_step('],
'Either MAX field refuses before state lookup, pending recovery, replay acceptance or fresh entry. Finite read-only recovery structure is unchanged.')
flow('remote inference callback',P+'circuit_cell_remote.rs',[
'let now = clock();','now.circuit_millis == u64::MAX','now.cell_micros == u64::MAX',
'invalid_clock = true;','return u64::MAX;','sampled.set(now);','now.cell_micros',
'if invalid_clock','return Err(CircuitCellErrorV1::ReconciliationRequired);'],
'MAX is not stored as a valid Circuit sample. Existing infer_cell_with_clock rejects the numeric marker before admission or dispatch; an earlier persisted admission remains pending.')
flow('remote decision and commit',P+'circuit_cell_remote.rs',[
'let decided_at = clock();','decided_at.circuit_millis == u64::MAX','decided_at.cell_micros == u64::MAX',
'return Err(CircuitCellErrorV1::ReconciliationRequired);','let proposal = decide_cell(',
'let committed_at = clock();','committed_at.circuit_millis == u64::MAX','committed_at.cell_micros == u64::MAX',
'return Err(CircuitCellErrorV1::ReconciliationRequired);','commit_cell_step(',
'if loan_failed.get()', 'admission.require_current()'],
'A MAX decision sample cannot reach numerical/policy proposal computation; a MAX commit sample cannot reach owner.commit. Later error is not proof previous inference did not run.')
assert len(re.findall(r'\bclock\(\)',cell))==4
flow('Root CLOCK encoding',P+'circuit_task_remote_service.rs',[
'Operation::Clock if frame.loan == record.id && frame.body.is_empty()',
'let clock = original.pump.clock();','clock.circuit_millis == u64::MAX || clock.cell_micros == u64::MAX',
'return Err(Error::ReconciliationRequired);','clock.circuit_millis.to_be_bytes()',
'clock.cell_micros.to_be_bytes()'],
'Refusal precedes the complete 16-byte CLOCK payload encoding and Lane response.')
flow('daemon CLOCK decoding',P+'circuit_task_remote_client.rs',[
'pub(crate) fn sample_original_clock(', 'Operation::Clock, loan: id, body: Vec::new()',
'if bytes.len() != 16', 'let clock = CircuitCellTimeV1',
'clock.circuit_millis == u64::MAX || clock.cell_micros == u64::MAX',
'return Err(Error::ReconciliationRequired);','Ok(clock)'],
'Only a complete bound response is decoded; either MAX field returns an existing error before exposing time. Higher-level failure does not refund the already consumed request.')
flow('daemon merged current RunStart time',P+'circuit_task_remote_runtime.rs',[
'if cancellation.is_cancelled()', 'let now_ms = state.require_current_run_start',
'let sampled = original.sample_original_clock()?;',
'circuit_millis: sampled.circuit_millis.max(now_ms)',
'sampled.circuit_millis == u64::MAX || sampled.cell_micros == u64::MAX',
'return Err(Error::ReconciliationRequired);','Ok(sampled)'],
'The merge can introduce MAX even if the wire sample was finite; the new check covers the merged result before the Driver closure returns Ok.')
flow('original inference two samples',N+'cell_inference.rs',[
'pub fn infer_cell_with_clock(', 'let admitted_at_micros = clock_micros();',
'let mut admission = admission_for_step(&prepared, admitted_at_micros)?;',
'owner.admit_inference(admission.clone())?;',
'let dispatch_at_micros = clock_micros();',
'if dispatch_at_micros >= prepared.input.deadline_micros',
'return Err(CellExecutionError::DeadlineExceeded);',
'let result = control.execute_feature(&request);','owner.record_host_queue_age('],
'A MAX first sample fails admission_for_step before durable admission. A MAX second sample fails the original >= u64 deadline before feature execution and host queue persistence, while prior admitted work is retained.')
flow('original feature four samples',N+'feature_control.rs',[
'let admitted = (self.clock)();','admitted < binding.not_before_micros || admitted >= deadline',
'.admit_generation(admitted,', 'let dispatch = (self.clock)();','dispatch < admitted || dispatch >= deadline',
'.dispatch_generation(dispatch,', 'let entered = (self.clock)();','entered < dispatch || entered >= deadline',
'let mut observation = self.worker.execute(request)?;',
'let completed = (self.clock)();', 'completed == u64::MAX || completed < entered',
'return Err(NeuronModelError::Indeterminate);',
'observation.queue_age_micros =', 'if completed >= deadline',
'observation.status = NeuronFeatureTerminalStatusV1::Cancelled;',
'build_neuron_feature_receipt_v1(','.settle_generation('],
'All four original samples reject MAX: the first three through >= a u64 deadline, the last through the added explicit disjunct. Completion rejection happens after actual worker contact but before new queue/status/receipt/settle work.')
assert feature.count('(self.clock)()')==4
assert feature.replace('completed == u64::MAX || ','',1)==before[N+'feature_control.rs']
assert len(feature.encode())-len(before[N+'feature_control.rs'].encode())==25

flow('original Root pump selects only remote Cell method',P+'circuit_task_root_lane.rs',[
'impl<O, P, E, C> OriginalRootCellPump for OriginalPump<O, P, E, C>',
'fn clock(&mut self) -> CircuitCellTimeV1 { (self.clock)() }',
'fn execute(&mut self, admission: OriginalRemoteAdmission',
'self.cells.execute_original_remote(admission, input, &mut self.clock)'],
'The fixed remote Root service reaches the strengthened remote method, not the old local execute method.')
flow('original daemon Cell port pre/post samples',P+'circuit_task_cell_port.rs',[
'impl OriginalCellPort for super::remote::DaemonCellPort',
'let before = clock();','let result = self.original_execute(admission, input, before);',
'let after = clock();','after.circuit_millis == u64::MAX || after.cell_micros == u64::MAX',
'return Err(CircuitCellErrorV1::ReconciliationRequired);','result'],
'Existing remote client rejects its before sample prior to retaining/sending Execute; original post sample rejection does not assert Execute was unperformed.')
flow('original Task Driver first error remains retained',P+'circuit_task_driver.rs',[
'let mut clock_error = None;','let execution = self.cells.execute(',
'if clock_error.is_none()', 'Err(error) => clock_error = Some(error)',
'circuit_millis: u64::MAX','cell_micros: u64::MAX',
'if let Some(error) = clock_error','return Err(error);','let execution = execution?;'],
'The existing Driver retains its first fallible current-run/clock error and propagates it after the synchronous Cell return. This does not prove a future new producer retains its own error.')

MAX=2**64-1
values=[0,1,10,11,12,99,100,101,MAX-1,MAX]
samples=[]
for kind in ['initial','inference','decide','commit','wire','merged']:
    rows=[]
    for a,b in itertools.product(values,repeat=2):
        old=(a<11) if kind=='initial' else ((a<11 or b<11 or a>=100) if kind=='inference' else (a<11 or b<11) if kind in ['decide','commit'] else False)
        new=old or a==MAX or b==MAX
        if a!=MAX and b!=MAX:assert new==old
        if a==MAX or b==MAX:assert new
        rows.append({'a':a,'b':b,'old_reject':old,'new_reject':new})
    samples.append({'boundary':kind,'cases':len(rows),'finite_cases_unchanged':True,'either_max_rejects':True,'cases_sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()})
completion=[]
for t,entered,indeterminate in itertools.product(values,[0,11,100,MAX-1,MAX],[False,True]):
    old=t<entered or indeterminate
    new=t==MAX or old
    if t!=MAX:assert new==old
    else:assert new
    completion.append([t,entered,indeterminate,old,new])
for d in values:assert MAX>=d

test=after[N+'feature_control_tests.rs'];oldtest=before[N+'feature_control_tests.rs']
assert test.startswith(oldtest)
newtest=test[len(oldtest):]
assert newtest.count('#[test]')==1
name='feature_control_invalid_completion_clock_retains_original_unresolved_dispatch'
assert re.findall(r'^fn (\w+)\(',newtest,re.M)==[name]
test_anchors=anchors(newtest,[
'let worker_calls = Arc::clone(&calls);','let clock_samples = Arc::clone(&samples);',
'clock_samples.fetch_add(1, Ordering::SeqCst);','if worker_calls.load(Ordering::SeqCst) == 0 { 11 } else { u64::MAX }',
'port.execute_feature(&request),','Err(NeuronModelError::Indeterminate)',
'assert_eq!(calls.load(Ordering::SeqCst), 1);','assert_eq!(samples.load(Ordering::SeqCst), 4);',
'assert!(checked(port.owner.generation_has_unresolved()));',
'assert_eq!(record.and_then(|value| value.dispatched_at_micros), Some(11));',
'assert_eq!(checked(port.read_feature(&request)), None);',
'let pending_bytes = checked(fs::read(fixture.path()));',
'port.execute_feature(&request),','Err(NeuronModelError::Indeterminate)',
'assert_eq!(calls.load(Ordering::SeqCst), 1);','assert_eq!(samples.load(Ordering::SeqCst), 4);',
'assert_eq!(checked(fs::read(fixture.path())), pending_bytes);','drop(port);',
'let mut reopened = fixture.port(',
'Arc::new(|| panic!("unresolved completion sampled a replacement clock"))',
'assert!(checked(reopened.owner.generation_has_unresolved()));',
'assert_eq!(checked(reopened.read_feature(&request)), None);',
'reopened.execute_feature(&request),','Err(NeuronModelError::Indeterminate)',
'assert_eq!(calls.load(Ordering::SeqCst), 1);','assert_eq!(checked(fs::read(fixture.path())), pending_bytes);',
])
assert oldtest.count('#[test]')==5
assert 'fn feature_control_dispatch_fsync_deadline_and_late_result_keep_original_cost()' in oldtest
assert 'assert_eq!(receipt.status, NeuronFeatureTerminalStatusV1::Cancelled);' in oldtest
assert '(13, 17, 23)' in oldtest and 'assert!(receipt.queue_age_micros >= 19);' in oldtest

proof={'format':'independent-clock-rejection-source-proof-v1','state':'STATIC_ONLY',
'layers':layerproof,'files':allfiles,'references':refs,
'baseline_composition':{'local':str(cr),'pin':pin(rd(cr))},'baseline_inventory':pin(rd(I)),
'manual_consumer_flow_witnesses':flows,
'predicate_reasoning':{'explanation':'Reviewer-owned finite boundary arithmetic only, not execution of Rust/project tests. Whole-byte inverse establishes unchanged predicates for every non-MAX input; the enumerated finite sample grid is an additional sanity check.',
'u64_max':MAX,'two_field_grids':samples,'feature_completion_cases':len(completion),
'feature_completion_cases_sha256':hashlib.sha256(json.dumps(completion,separators=(',',':')).encode()).hexdigest(),
'every_u64_deadline_is_lte_MAX':'Mathematical domain property; existing >= deadline rejects MAX at the first three Feature samples and original inference admission/dispatch.'},
'regression_test':{'name':name,'original_test_count':5,'new_test_count':1,
'old_prefix_bytes_equal':True,'appended_bytes':len(newtest.encode()),'source_anchors_relative_to_append':test_anchors,
'original_worker_calls_before_success_observation':True,'executed':False},
'explicit_scope_limits':[
'The old local circuit_cell::execute and local runtime path are not modified or proved universally MAX-safe.',
'A future protected task-clock producer must separately retain its first real error and remain poisoned. Its implementation and final full consumer graph were not frozen in these layers.',
'The source rejects a synthetic clock value, not prior durable inference/admission costs. A post-worker Indeterminate is Unknown, not NotExecuted or retry authorization.',
'No Rust, QA, compiler, collector, H, source Git/ref, owner construction or fixture execution occurred.'],
'H_calls':0,'project_code_executed':False,'qualification':False,
'new_report_Git_objects_created_or_fetched':False}
out=save('BYTE_AND_CONSUMER_PROOF.json',proof)
print(json.dumps({'status':'STATIC_PROOF_COMPLETE','proof':out,'files':6,'production_files':5,'test_files':1,'splices':9,'H_calls':0},sort_keys=True))
