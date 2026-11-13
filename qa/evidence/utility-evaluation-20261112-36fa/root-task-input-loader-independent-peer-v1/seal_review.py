#!/usr/bin/env python3
"""Seal this reviewer's local static findings; no source or remote mutation."""
import hashlib
import json
from pathlib import Path

O=Path('/tmp/hepta-36fa-root-task-input-loader-independent-review-v1')
D=Path('/tmp/hepta-36fa-root-task-cli-loader-proposal-v1/task-inputs-layer-v1')
P='codex-rs/hepta-agentd/src/'
def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def emit(name,v):
    b=(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n').encode()
    with (O/name).open('xb') as f: f.write(b)
    return pin(b)
def original(path):
    p=Path(path)
    return {'local':str(p),**pin(p.read_bytes())}

proof=json.loads((O/'BYTE_AND_CONTRACT_PROOF.json').read_bytes())
packet=json.loads((D/'SOURCE_PACKET.json').read_bytes())
entries={r['path']:r for r in packet['entries']}
def source(name):
    e=entries[P+name]
    return {'path':P+name,'local':str(D/'after'/(P+name)),**e['after']}
def support(names): return [source(n) for n in names]

review={
 'format':'hepta-independent-root-task-input-loader-review-v1',
 'reviewer':'/root/native_ci_audit',
 'state':'STATIC_REVIEW_COMPLETED_NO_NEW_CONCRETE_BLOCKER_IN_FIXED_LAYER',
 'execution_approval':False,
 'source_or_ref_write':False,
 'project_execution':False,
 'native_h_calls':0,
 'qualification_pass':False,
 'candidate':original(D/'SOURCE_PACKET.json'),
 'manifest':original(D/'MANIFEST.json'),
 'pure_proof':original(O/'BYTE_AND_CONTRACT_PROOF.json'),
 'scope':{
   'frozen_layer':'Second task-input layer 77b05d5e only, with exact original/v6 dependencies and first loader e78f already separately reviewed.',
   'files':13,'new_production_modules':6,'existing_mount_files':7,'exact_insertions':8,
   'new_tests':0,'execution_count':0,
   'required_production_refusal_layers':{'remote':'9f780f963b0e9585b5b85a83f87de593f604bfa5','feature':'ade9282388680285416c7829000b7081e22550ef'},
   'independent_clock_review':original('/tmp/hepta-36fa-clock-rejection-independent-review-v1/REVIEW.json'),
   'prior_generation_loader_review':original('/tmp/hepta-36fa-root-generation-input-loader-independent-review-v1/REVIEW.json'),
   'baseline_b608_inventory':proof['baseline_inventory'],
   'exact_v6_composition':proof['composition_v6'],
   'not_in_scope':['Not the later normal CLI or full same-session orchestration; it is not present in this layer.','Not a compiler or Rust name-resolution proof; no tests or collectors were executed.','Not a qualification or permission for H, a daemon start, source publication or runtime owner actions.','Not a statement that arbitrary future crate consumers or old local execution are MAX-safe.'],
 },
 'result':{
   'concrete_blockers':[],
   'acceptance_boundary':'The fixed source is suitable for the next static integration review with its required clock-rejection dependencies. No new concrete static blocker was found in this layer. It does not yet provide a normal serving entry and is not represented as an executable/qualified path.',
   'key_conclusion':'The callback exits its private loader only in crate-private inputs, whose sole actual consumer consumes the original Ready into the original Config-free factory and seals the result. The returned non-Clone wrapper has no task/runtime/clock extraction API; its only public method is checked readback. The first retained clock failure is a non-resetting shared CAS state.',
 },
 'findings':[
  {
   'id':'F01_EXACT_LAYER_AND_MOUNTS','status':'VERIFIED_STATIC',
   'detail':['All 13 before/after payloads, local files and manifest pins were independently recomputed. The seven old preimages equal both frozen v5 and v6 bytes; all six new paths are absent from the canonical b608 inventory and v6 changed view.','The final splice contract is FINAL_MOUNT_SPLICES.json, 5,935 B / 9df2125591031c389e55a3983e731129668ea1d7. Its seven records contain exactly eight additions; every complete forward and reverse replacement equals the packet bytes. SOURCE_DELTA.patch was independently reconstructed completely.','The older MOUNT_SPLICES.json remains an intermediate artifact. It was not mistaken for the final eight-addition contract. The manifest correctly binds the final table.','Existing functions remain byte-for-byte unchanged after removal of these mount/reexport additions. Both new lib exports each retain their own Linux cfg; no old export loses its prior cfg scope.'],
   'evidence':['BYTE_AND_CONTRACT_PROOF.json:files','BYTE_AND_CONTRACT_PROOF.json:metadata_complete_byte_bindings','BYTE_AND_CONTRACT_PROOF.json:source_delta_exact'],
  },
  {
   'id':'F02_PUBLIC_AND_INTERNAL_CLOCK_CLOSURE','status':'VERIFIED_FIXED_SOURCE_CHAIN',
   'detail':['Public RootHostQ24TaskFilesV1 is a set of owned File inputs, not a publication or receipt. The public prepare/recover methods consume the actual PreparedRootHostInitialGenerationV1 and return only PreparedRootHostLoadedQ24TaskV1.','The loaded wrapper has private task and clock_status fields. It has no Clone implementation or derive, Deref/AsRef, into_inner, owner getter, runtime getter, clock getter, caller callback or local Config installation entry. Its only current public method is read_loaded_original_root_task_generation.','The crate-private HostAuthorityService::load_original_root_q24_task_inputs has exactly one actual call site in the fixed source chain: the private load_original_task_files helper. Its crate-private LoadedOriginalTaskInputs is immediately consumed by PreparedRootHostInitialGenerationV1::prepare_original_root_task; only the sealed wrapper leaves that helper.','All references to the new type/helper names were enumerated across the complete 100-file frozen changed view plus six new modules. Existing original construction and private custody methods were also read. This is a source closure argument for these fixed files, not a general claim against future source changes.','The old into_original_q24_task(config, inputs) and local runtime owner loop remain available to their original callers and remain unmodified. The new loader has no path to return the inner inputs, Task or runtime to those APIs.'],
   'sources':support(['authority_host_generation_task_input_loader.rs','authority_host_session_generation_task_loader.rs','authority_host_session_generation_task.rs']),
   'evidence':['BYTE_AND_CONTRACT_PROOF.json:public_methods','BYTE_AND_CONTRACT_PROOF.json:new_symbol_references'],
  },
  {
   'id':'F03_PERMANENT_FIRST_CLOCK_CAUSE','status':'VERIFIED_STATIC_WITH_PURE_TRANSITION_CHECK',
   'detail':['The callback clones the same original HostAuthorityService clock Arc; callers cannot choose a replacement clock. Same callback and wrapper share one AtomicU8 through Arc and the unchanged absolute end.','The only state mutation is compare_exchange(0, code, AcqRel, Acquire). Codes 1/2/3 preserve original AuthorityTrustError Invalid/Conflict/Unavailable; 4 denotes checked microsecond overflow and 5 absolute-end expiry. No store, swap, reset, setter, new deadline or success token exists.','First failure means the first successful CAS among observed contenders, not a separately measured wall-clock ordering of racing failures. Later failures, recovery of the underlying clock or end expiry cannot replace it.','Every later callback starts with require_healthy and returns fenced MAX without consulting a recovered clock after failure. Successful time conversion checks healthy again before returning the sample. Millis-to-micros uses checked_mul(1000); failure is retained and fenced.','The wrapper checks clock health before original readback and again after it. A successful original result is withheld on clock failure. If both original operation and clock fail, Protocol text retains both errors rather than substituting success.','The independent Python proof checks 120 order permutations of the inspected first-write transition; it does not run Rust atomics or constitute a concurrency test.'],
   'sources':support(['authority_host_generation_task_clock.rs','authority_host_generation_task_input_loader.rs','authority_host_session_generation_task_loader.rs']),
   'evidence':['BYTE_AND_CONTRACT_PROOF.json:clock_callback_order','BYTE_AND_CONTRACT_PROOF.json:clock_first_failure'],
  },
  {
   'id':'F04_CONSTRUCTOR_DOES_NOT_RUN_LOCAL_OWNER_LOOP','status':'VERIFIED_STATIC',
   'detail':['The exact original Ready factory delegates to into_original_root_task_channel and circuit_q24_task_channel_v1. The profile stores the clock for the root lane and for the original feature-control adapter.','PublishedCircuitFeatureTaskV1::control builds its guarded clock closure but does not invoke it. ControlledNeuronFeaturePortV1::new stores the closure after original definition/runtime/unresolved checks; circuit_task_channel_v1 stores the clock in OriginalOwners and an unpolled owner-loop closure.','Thus the callback is not sampled in these constructor bodies. A later factory failure can follow journal/Source/Cell changes, but no callback failure is silently dropped by the inspected constructor path. Initial direct original clock errors during loading return the original failure immediately before the wrapper is constructed.','There is currently no public serving method on the loaded wrapper. The next assembly must remain in its private module subtree, consume the fixed Root remote lane, and preserve retained-error checks. This layer cannot be treated as completed CLI wiring.'],
   'references':[
    {'path':P+'authority_host_session_generation_root_task.rs','git_blob':'86bf9f8ca4a51bb1e60499bbfd4a89a1a23d0153'},
    {'path':P+'neuron_generation_initial_root_task_channel.rs','git_blob':'38d3dfc7ce99e4f36bdb7369d877a14c98be4ddf'},
    {'path':P+'circuit_q24_task_profile.rs','git_blob':'90962d888c43b96e4a8e6bd44b9b3b73b52eff4c'},
    {'path':P+'circuit_task_runtime.rs','git_blob':'3aa3bf5bcb437f2b283209a7066a69a6892097de'},
    {'path':'codex-rs/hepta-neuron/src/feature_control.rs','git_blob':'78ce92d31e0fbf9c4955f25c5629ba67eb4911b2'},
   ],
  },
  {
   'id':'F05_MAX_CONSUMERS_REQUIRE_THE_TWO_FROZEN_STRENGTHENINGS','status':'VERIFIED_DEPENDENCY_NOT_UNIVERSAL_SENTINEL_CLAIM',
   'detail':['A MAX pair is invalid-time fencing, not a successful sample or authority grant. This review relies on actual v6 afterimages of the two separately reviewed refusal layers; it does not rely on the numeric value alone.','Root remote execute rejects either MAX before initial recovery/lookup, the inference admission sample, decide and commit. Root CLOCK encode, daemon decode and daemon runtime merging independently reject MAX.','The original feature-control adapter already rejects admitted/dispatch/entered >= deadline. The new completion disjunct returns Indeterminate after a worker may have run and before receipt/outcome settlement; old finite late Cancelled and its costs are unchanged.','The original Driver and Cell-port adapters remain fallible/guarded at their reviewed boundaries. Source readback and completion require the original authenticated same task/Cell receipts; a clock error does not manufacture them.','Old local Cell/runtime are not MAX-safe merely because these remote checks exist. The loader wrapper must not be opened in later integration to feed its clock into the old local execute/Config path.'],
   'evidence':['BYTE_AND_CONTRACT_PROOF.json:clock_consumer_v6_bindings','/tmp/hepta-36fa-clock-rejection-independent-review-v1/REVIEW.json'],
  },
  {
   'id':'F06_READY_SESSION_OPERATION_AND_FIXED_END','status':'VERIFIED_STATIC',
   'detail':['Before reading task deployment or opening original journals, the public method checks the actual session and absolute end, matches InitialHostPhase::Ready, and validates the actual custody readback against the same retained OriginalHostInitialOperation.','The private service loader receives that same service and self.end. After loading, the operation and session are checked again; the original factory then repeats actual Ready/registered identity/current-operation/session checks.','Create and Recover are separate named consuming public methods. The deployment source_mode must exactly match that selected purpose and maps only to the corresponding original CircuitQ24TaskOpenModeV1 variant.','On loading failure the original Ready is consumed; only the original same-operation error/readback wrapper is returned. There is no Create fallback, new Ready, replacement operation, retries or renewed deadline.'],
   'sources':support(['authority_host_session_generation_task_loader.rs','authority_host_generation_task_input_loader.rs']),
   'evidence':['BYTE_AND_CONTRACT_PROOF.json:guards:ready_precedes_all_input_opening'],
  },
  {
   'id':'F07_PROTECTED_FILES_AND_NO_PATH_SUBSTITUTION','status':'VERIFIED_STATIC_CONTRACT',
   'detail':['Deployment uses the existing read_root_json boundary: Root-owned single-link 0600 regular file, no-follow open and 64 KiB content cap. The exact schema version, purpose, source_mode and clock_epoch strings are checked. All new DTO structs deny unknown fields.','The eight mandatory descriptors plus zero, one or two optional adapter descriptors must be pairwise distinct by dev/inode, regular, uid 0, nlink 1 and mode exactly 0600 including rejection of special bits.','Source and Cell journal/witness descriptors require O_RDWR without O_APPEND; inference-control requires O_RDWR|O_APPEND; model descriptors require O_RDONLY without append. No pathname is opened by the descriptor checker.','Recover rejects empty Source/Cell journals and witness files shorter than the existing 112-byte header before original opens. An existing empty inference-control journal is not automatically a failure: original replay and actual receipts govern whether work/readback is allowed.','DurableInferenceControl::open_file uses only the consumed descriptor and original bounded replay/lock path. The diagnostic PathBuf is retained for diagnostics and does not select or reopen another store.','Pairwise checks cover this input set. They do not establish global absence of duplicated descriptors held elsewhere, immutable metadata after the check, or physical termination of blocking I/O exactly at end. These stronger claims are not made.'],
   'sources':support(['authority_host_generation_task_input_files.rs','authority_host_generation_task_input_loader.rs']),
   'evidence':['BYTE_AND_CONTRACT_PROOF.json:original_references'],
  },
  {
   'id':'F08_FULL_ORIGINAL_DATA_AND_REAL_MODEL','status':'VERIFIED_STATIC_COMPLETE_FIELD_BINDING',
   'detail':['The independent review matches all 14 original record declarations, all 109 explicit constructor fields and the frozen field map exactly. No result/receipt/publication is substituted with a digest-only record.','Definition retains all runtime, calibration, resource, sparse mechanism, candidate and memory/input/queue fields and invokes the original semantic_digest. Bundle retains all 13 components, complete lineage and rollback predecessor and invokes original digest. IDs/generations use original checked constructors.','Source retains all scope fields, full observation bytes and candidate masks, frontier/objective/NDU/time/lease values. Routes retain the original candidate/outcome/selected edge list. Circuit uses the original BoundedCircuitDefinitionV2 and fence uses the original TaskFlowFence::new.','The original protected clock supplies the epoch comparison. Source monotonic cannot be in the future; deadline must exceed monotonic, and Create must still be before that deadline. Recover preserves original history rather than rewriting time to make it fresh.','The actual model files are consumed by LoadedCellQ24ModelV1::open_files. Original codec bounds each file to 32,780 bytes, validates exact matrix/adapter layout and dimensions, computes actual byte component digests, and constructs immutable parsed matrices. Every resulting component must equal the full declared bundle.','Witness scope/generation/max records are full provisioned input values checked by the original witness opener and then bound by the original Source/Cell factory. They are not selected from fixture constants. The original publication/current/bundle/registry/Cell/model checks remain in the unchanged factory.'],
   'sources':support(['authority_host_generation_task_input_types.rs','authority_host_generation_task_model_types.rs','authority_host_generation_task_input_loader.rs']),
   'evidence':['BYTE_AND_CONTRACT_PROOF.json:records','BYTE_AND_CONTRACT_PROOF.json:guards:protected_data_and_materials'],
  },
  {
   'id':'F09_ERROR_AND_SIDE_EFFECT_BOUNDARY','status':'REQUIRED_PRECISE_INTERPRETATION',
   'detail':['FileAnchorWitnessStore::open and original Source/Cell creation/recovery can establish or advance original durable state before a later failure. The result is not described as no-effect or a rollback proof.','An inference worker can already have run before completion clock failure; Indeterminate retains unresolved original journal state and forbids treating the operation as NotApplied or retryable.','No extra installer, Config, AutomationStore, signer, owner, runtime, reset, deadline extension, test bypass or channel clone is introduced in this layer.','Absolute-end checks are repeated before/after protected stages and on callback/readback. They withhold late success; they are not a proof of physical cancellation of arbitrary blocking OS work.'],
  },
 ],
 'reviewer_execution':{
   'first_attempt':original(O/'EXECUTION_01.original.json'),
   'initial_script':original(O/'verify_task_inputs.py'),
   'correction':'The initial reviewer field regex matched the word result: in a pre-existing CellTrainingLineageV1 doc comment. It was corrected to match declaration field lines only. Original candidate, source packet and source references were unchanged.',
   'second_attempt':original(O/'EXECUTION_02.original.json'),
   'final_script':original(O/'verify_task_inputs_v2.py'),
   'final_exit':0,
   'result':'13 paths, 8 complete inverse insertions, 14/109 original fields, 38 exact original references, fixed 106-file changed view and exact clock dependencies all matched.',
   'limits':'Both attempts used reviewer-owned Python standard library for fixed-byte and schema checks only; neither imported nor executed project, author preparation, Rust, QA or H code.',
 },
 'remaining_integration_obligations':[
  'Keep remote 9f780f and feature ade928 refusal layers in the same exact source view.',
  'Later loaded-task serving must remain private and purpose-fixed; preserve pre/post retained clock checks and expose no Task/runtime/clock/local Config extraction.',
  'Finish real normal CLI and same-session construction with concrete protected inputs; this layer alone supplies no serving entry or executable full-chain proof.',
  'Register the three new public methods, two public types and eight original owner/helper call sites using the unchanged typed collector/protection workflow against final exact bytes.',
  'Run required compile/format/tests/native qualification only under the later exact engineering contract; none occurred here.',
 ],
 'storage':{'all_pins_are_computed_content_identities':True,'this_reviewer_performed_git_create_or_get':False,'root_owns_later_archival':True,'original_frozen_inputs_modified':False},
}
print(json.dumps({'REVIEW.json':emit('REVIEW.json',review)},ensure_ascii=False))
names=['BYTE_AND_CONTRACT_PROOF.json','EXECUTION_01.original.json','EXECUTION_02.original.json','verify_task_inputs.py','verify_task_inputs_v2.py','seal_review.py','REVIEW.json']
index={'format':'hepta-static-review-closed-index-v1','state':'LOCAL_COMPUTED_IDENTITIES_ONLY_NO_GIT_UPLOAD_BY_REVIEWER','root':str(O),'payload_count':len(names),'entries':[{'name':n,**pin((O/n).read_bytes())} for n in names],'source_modified':False,'native_h_calls':0,'project_execution':False}
assert all(e['bytes']<=512000 for e in index['entries'])
print(json.dumps({'CLOSED_FILE_INDEX.json':emit('CLOSED_FILE_INDEX.json',index)},ensure_ascii=False))
