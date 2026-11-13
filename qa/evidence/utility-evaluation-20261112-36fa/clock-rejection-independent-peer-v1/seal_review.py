#!/usr/bin/env python3
from pathlib import Path
import json
import hashlib

D=Path('/tmp/hepta-36fa-root-product-e2-proposal-v1')
O=Path('/tmp/hepta-36fa-clock-rejection-independent-review-v1')
def pin(b):return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def save(n,x):
 b=(json.dumps(x,sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode()
 with (O/n).open('xb') as f:f.write(b)
 return pin(b)
p=json.loads((O/'BYTE_AND_CONSUMER_PROOF.json').read_bytes())
assert json.loads((O/'EXECUTION_01.original.json').read_bytes())['exit_code']==0

review={
 'format':'independent-remote-and-feature-clock-rejection-review-v1',
 'reviewer':'/root/native_ci_audit',
 'status':'NO_NEW_CONCRETE_STATIC_BLOCKER_IN_FIXED_FIVE_PRODUCTION_FILES_AND_ONE_TEST_FILE',
 'scope':{'production_files':5,'test_files':1,'splices':9,'new_test_methods':1,
          'frozen_input_layers':[{'name':r['name'],'packet':r['packet'],'manifest':r['manifest']} for r in p['layers']],
          'original_base':'Four remote files are exact Root composition-v5 beforeimages; feature_control and its tests match complete original b608 beforeimages.',
          'old_local_Cell_or_local_runtime_changed':False,
          'new_protected_task_clock_producer_reviewed_here':False,
          'new_protected_task_clock_final_consumer_closure_reviewed_here':False,
          'source_Git_or_ref_writes':False,'H_calls':0,'compiler_formatter_QA_collector_or_Rust_tests_executed':False},
 'inputs_and_reproducer':{
   'proof':{'path':str(O/'BYTE_AND_CONSUMER_PROOF.json'),'pin':pin((O/'BYTE_AND_CONSUMER_PROOF.json').read_bytes())},
   'pure_script':{'path':str(O/'verify_clock_layers.py'),'pin':pin((O/'verify_clock_layers.py').read_bytes())},
   'raw_pure_script_result':{'path':str(O/'EXECUTION_01.original.json'),'pin':pin((O/'EXECUTION_01.original.json').read_bytes())},
   'exit_code':0,'meaning':'Only full bytes, JSON schemas, fixed source anchors and reviewer-written integer predicates were evaluated. No project code was imported or executed.'},
 'original_finding':{
   'path':'/tmp/hepta-36fa-root-clock-failure-static-finding-v1/FINDING.json',
   'pin':pin(Path('/tmp/hepta-36fa-root-clock-failure-static-finding-v1/FINDING.json').read_bytes()),
   'confirmed':'In the old remote Cell path, MAX passed the initial nonregression guard and could reach pending readback, decide_cell and commit_cell_step before a final loan error. MAX at the old Feature completion sample could be treated as a finite overdue completion and produce/settle a Cancelled receipt.',
   'boundary':'This is a source/control-flow finding. It is not evidence of an actual affected run, observed state mutation, model invocation or forged cost.',
   'historical_preservation':'Original source packets and earlier time-scoped reviews remain intact. This finding and these corrective layers do not rewrite their contents or reclassify prior H Unknown.'},
 'byte_results':{
   'files':p['files'],'all_three_manifest_and_metadata_sets_fully_hashed':True,
   'all_nine_splices_unique_old_new_full_forward_inverse_equal':True,
   'all_three_complete_patches_independently_reconstructed':True,
   'feature_production_exact_delta_bytes':25,
   'feature_original_test_prefix_bytes':12439,'feature_new_append_bytes':2011,
   'all_unchanged_original_statements_preserved':True,
   'reference_files_bound_to_v5_or_b608':p['references']},
 'rejection_boundaries':[
  {'location':'circuit_cell_remote.rs: initial sample',
   'check':'Either time.circuit_millis or time.cell_micros equal to u64::MAX now returns the existing CircuitCellErrorV1::ReconciliationRequired.',
   'before':'State-owner lookup, pending inference recovery, acceptance of a committed replay and fresh enter_cell_step.',
   'retained':'Input/registry binding and original live-admission checks still occur in their original order. The check is not a claim of zero earlier IPC/currentness observations.'},
  {'location':'circuit_cell_remote.rs: infer_cell_with_clock callback',
   'check':'Either MAX field sets the existing invalid_clock flag and returns the original rejected numeric marker, without sampled.set.',
   'before':'The marker cannot become a valid recorded Circuit sample or reach the control port as an accepted dispatch time.',
   'original_consumer_proof':'infer_cell_with_clock first calls admission_for_step, which rejects >= the u64 input deadline before owner.admit_inference. Its second sample is rejected before execute_feature and before record_host_queue_age. Since u64::MAX is at least every u64 deadline, both original boundaries reject it.',
   'retained':'A first admission may already have become durable before a later invalid sample. Pending state remains; no refund, retry or zero-cost substitute is introduced.'},
  {'location':'circuit_cell_remote.rs: decision and commit samples',
   'check':'Each new sample rejects either MAX field in addition to the original backwards-clock conditions.',
   'before':'decide_cell numerical/policy/proposal work and commit_cell_step owner mutation, respectively.',
   'retained':'The same pending/replay/final require_current logic remains. Prior actual inference work is not erased by a later ReconciliationRequired.'},
  {'location':'circuit_task_remote_service.rs: CLOCK response',
   'check':'The original Root pump clock is sampled once; either MAX field refuses before encoding the 16-byte payload.',
   'before':'Response framing/delivery as an accepted clock.',
   'retained':'Original record/loan, same Source binding, actual Root current-state and Lane deadline checks still surround handling. At transport boundaries the original error mapping may be CommitUncertain/Unavailable; this report does not promise the local ReconciliationRequired enum reaches the daemon verbatim.'},
  {'location':'circuit_task_remote_client.rs: CLOCK decoding',
   'check':'A complete authenticated 16-byte response is decoded; either MAX field returns ReconciliationRequired before Ok(clock).',
   'before':'Exposure of a valid time value to the runtime.',
   'retained':'The original Lane exchange has already consumed its request and may have restored the channel before this higher-level body validation. This check does not refund the request or independently promise permanent transport poison; the producer-specific permanent failure contract is separate.'},
  {'location':'circuit_task_remote_runtime.rs: merged current RunStart sample',
   'check':'After max(sampled.circuit_millis, actual current RunStart time), either MAX field is rejected before the fallible Driver clock closure returns Ok.',
   'before':'The Driver consumes time for run creation, recovery, claim, completion or Advance.',
   'retained':'Cancellation, actual RunStart authentication, original reverse-channel ownership and cleanup remain byte-identical. The merge itself cannot reintroduce an accepted MAX.'},
  {'location':'feature_control.rs: completed sample',
   'check':'The exact added 25-byte completed == u64::MAX || disjunct returns original NeuronModelError::Indeterminate.',
   'before':'Updating queue cost, converting status to Cancelled, clearing outputs, building or encoding a receipt and settle_generation.',
   'retained':'The real worker and durable admission/dispatch may already have executed. The record stays unresolved. The source does not assert NotExecuted, zero effects, permission to retry, or replacement of measured costs.',
   'other_samples':'Admitted, dispatch and entered already reject >= their original u64 deadline. The completed sample was the missing check because a finite late completion is intentionally settled as Cancelled.'},
 ],
 'known_consumer_graph':[
   'The private one-shot original Root factory creates OriginalPump. Its clock method reaches Root CLOCK encoding, and its execute method calls the strengthened execute_original_remote with the same original clock.',
   'CLOCK decoding returns Result. The remote runtime revalidates the post-merge sample, and each original Driver call propagates Err before its associated next work. The original Driver also preserves its first fallible error while its Cell adapter runs and reports it afterward.',
   'The original daemon Cell port samples before and after the actual remote operation. original_execution already rejects MAX before retaining/sending its admission; the existing post-sample guard rejects MAX after the operation without asserting no operation happened.',
   'Inside the strengthened remote Cell, all four actual clock() sites were enumerated. The original inference and GuardedCellDispatch boundaries receive only the accepted sample or the explicit refused marker.',
   'Inside the original Feature port, all four self.clock calls were enumerated. Readback and already-present-record branches do not sample a replacement live clock.',
 ],
 'normal_semantics_preserved':[
   'For every non-MAX input, each new predicate reduces exactly to the old predicate; all surrounding bytes are identical. Reviewer integer grids cover single-field MAX, both-field MAX, backward, equal, finite-late and adjacent-boundary examples, not project behavior.',
   'Finite expired/read-only pending recovery retains its original branch structure when the other original currentness guards permit it. No fresh inference is authorized by the new condition.',
   'Finite late Feature success continues to preserve real native cost and settle its original Cancelled receipt. Only the invalid sentinel is distinguished from finite lateness.',
   'The same original 128-request shared task/loan counter, 500 ms exchange timeout, per-session absolute end, sequence, nonce, actual peer lifetime and no-restoration-on-transport-failure remain in the unchanged wire module.',
   'No new queue, retry, deadline extension, grant, owner, state reset, remote fallback, test-only production bypass or changed policy calculation is introduced.',
 ],
 'regression_source_review':{
   'new_method':p['regression_test']['name'],
   'old_tests_retained':5,'new_tests':1,'executed':False,
   'positive_control':'The entire old finite-late Cancelled/cost test remains byte-identical, including measured memory 13, transient 17, latency 23, original queue lower bound and exact readback.',
   'mechanism':[
    'Uses the original Fixture, its real DurableInferenceControl journal, original binding/definition and existing explicit Worker lifecycle fixture. It does not fabricate a terminal record or call settle directly.',
    'The new clock returns 11 until the existing Worker increments its atomic call count, then MAX. The test demands exact Indeterminate after one worker call and four samples, unresolved original state, original dispatch timestamp 11 and no terminal readback.',
    'Same-port reentry must not call either worker or clock again, and the journal bytes must equal the saved pending bytes.',
    'The first port is dropped before reopening the same original journal. Reopened readback remains None, execute remains Indeterminate, the worker count remains one and original bytes remain equal. Its supplied clock panics if a replacement sample is incorrectly requested.',
    'This is a meaningful source-level regression for the old completion-sentinel path, not numerical correctness, real Root authority, authenticated IPC, process cold recovery or a test PASS.'
   ],
   'cleanup':'The unchanged synchronous Fixture Drop owns its temporary directory cleanup; no async task/join or physical process-exit claim is made.'},
 'remaining_dependencies':[
   'The new protected Root task-clock producer was not part of these three immutable packets. It must retain its first real AuthorityClock/overflow/deadline error permanently and cannot rely on a transient MAX alone.',
   'The original local circuit_cell::execute and local runtime are deliberately unmodified and are not proved universally MAX-safe. A later private task-loader wrapper must prevent its new sentinel-producing clock from escaping into those old local paths, or obtain a separate explicit correction. This report is not acceptance of that later consumer closure.',
   'These source changes and their later composition need exact registration/protection refresh plus the actual original formatter/compiler/source/native gates when separately authorized. None ran here.',
   'A rejected post-dispatch or post-worker sample keeps execution uncertainty and original cost records. No new H or retry is authorized by this review.'
 ],
 'conclusion':{'concrete_blockers_in_these_fixed_layers':[],
               'known_remote_and_feature_completion_source_defect_addressed_statically':True,
               'complete_new_clock_producer_and_all_product_consumers_accepted':False,
               'may_integrate_for_further_prequalification_review':True,
               'is_execution_approval':False,'qualification':False,'H_remains_stopped':True},
 'storage_boundary':'Local complete-byte computed pins only. No new reviewer artifact was uploaded or full-GET through Git by this agent; Root owns evidence publication.'
}
rp=save('REVIEW.json',review)
names=['verify_clock_layers.py','BYTE_AND_CONSUMER_PROOF.json','EXECUTION_01.original.json','seal_review.py','REVIEW.json']
rows=[]
for n in names:
 b=(O/n).read_bytes();assert len(b)<=512000
 rows.append({'relative_path':n,'local_path':str(O/n),'pin':pin(b),'actual_Git_create_or_full_GET_claim':False})
ip=save('CLOSED_FILE_INDEX.json',{'format':'fixed-independent-review-files-v1','status':'LOCAL_COMPUTED_PINS_ONLY','entries':rows,'payload_count':len(rows),'with_index_count':len(rows)+1,'H_calls':0,'project_code_executed':False,'qualification':False})
print(json.dumps({'review':rp,'index':ip,'payload_count':len(rows),'with_index_count':len(rows)+1},sort_keys=True))
