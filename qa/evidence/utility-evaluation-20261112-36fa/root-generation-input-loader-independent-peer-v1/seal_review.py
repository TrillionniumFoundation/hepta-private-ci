#!/usr/bin/env python3
"""Create-only static review report; no project imports or process execution."""
from pathlib import Path
import hashlib
import json

O=Path('/tmp/hepta-36fa-root-generation-input-loader-independent-review-v1')
D=Path('/tmp/hepta-36fa-root-task-cli-loader-proposal-v1/inputs-layer-v1')
P='codex-rs/hepta-agentd/src/'

def pin(b):
    return {'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()}
def save(name,obj):
    b=(json.dumps(obj,sort_keys=True,ensure_ascii=False,indent=2)+'\n').encode()
    with (O/name).open('xb') as f:f.write(b)
    return pin(b)
def read(name):return json.loads((O/name).read_bytes())
proof=read('BYTE_AND_CONTRACT_PROOF.json')
assert proof['record_mapping_field_count']==77 and len(proof['files'])==8
assert read('EXECUTION_01.original.json')['exit_code']==1
assert read('EXECUTION_02.original.json')['exit_code']==0

def source(path):
    return {'path':str(D/'after'/path),'pin':next(r['after'] for r in proof['files'] if r['path']==path)}
def ref(path):
    r=next(r for r in proof['references'] if r['path']==path)
    return {'path':r['local'],'pin':r['pin']}

review={
 'format':'independent-root-existing-generation-input-loader-review-v1',
 'reviewer':'/root/native_ci_audit',
 'status':'NO_NEW_CONCRETE_STATIC_BLOCKER_IDENTIFIED_IN_THIS_FROZEN_LAYER',
 'source_packet':{'path':str(D/'SOURCE_PACKET.json'),'pin':proof['source_packet']},
 'proof':{'path':str(O/'BYTE_AND_CONTRACT_PROOF.json'),'pin':pin((O/'BYTE_AND_CONTRACT_PROOF.json').read_bytes())},
 'scope':{
   'files':8,'new_production_modules':4,'insertion_only_parents':4,
   'exact_preimage':'Root composition-v4; not canonical b608 for the four already-composed parents',
   'base_composition':proof['basis']['v4_composition_review'],
   'canonical_reference_inventory':proof['basis']['canonical_inventory'],
   'review_of_later_composition_v5':False,
   'new_tests_in_this_layer':0,
   'project_compilation_formatting_tests_collectors_or_QA_executed':False,
   'H_calls':0,'source_Git_objects_refs_or_source_worktree_writes':False,
   'scope_of_writes':'Only these reviewer-owned local report and pure-check files.',
 },
 'method':[
   'Read all four new production modules and every parent splice, then read the original protected JSON, Artifact trust/lease/head, withdrawal snapshot, selected generation, FinalUse store/frontier/retained-use, target witness and same-Session bind/recover implementations at the exact cited source pins.',
   'Independently parse the frozen full-before/after packet and manifest as duplicate-key-rejecting JSON data; hash each complete file and compare all parent preimages to the immutable v4 composition and its file identities.',
   'Apply the four exact splices to the first matching occurrence and require complete forward and inverse byte equality. Reconstruct the complete unified patch independently. A repeated impl anchor is not presumed unique.',
   'Compare nine local DTO declaration field lists, original public-record declaration fields, and actual literal construction fields. All 77 fields align; manually inspect each conversion expression, retained signature and exact Model-kind restriction.',
   'Validate all 29 supplied reference files and three additional references against the exact b608 complete inventory. This content check is broader than the named semantic reading and is not a claim that all referenced files were semantically audited in full.',
   'Run only the reviewer-owned Python standard-library byte/schema/ordered-anchor script. Ordered source anchors supplement manual reading; no Rust AST compiler or runtime was invoked.',
 ],
 'findings':[
  {
   'id':'L1_exact_mounts_and_api',
   'result':'All four old parents remain byte-for-byte intact apart from their explicit insertions.',
   'evidence':[source(P+'authority_host_generation.rs'),source(P+'authority_host_service.rs'),source(P+'authority_host_session_generation.rs'),source(P+'lib.rs')],
   'details':[
    'The Session parent contains two occurrences of the impl anchor. The author inserts before the first; the complete expected afterimage and reverse splice match exactly. No original impl or Material private-Arc export is removed.',
    'The lib public file-container export has its own Linux cfg and does not absorb or remove the old export attribute. The existing old bodies and prior E1/E2/E3 mounts remain in the four exact preimages.',
    'The new public surface consists of the five-File transport container and two consuming Session methods. Private/crate-only loading enums and internal method carry the original owners internally; no public owner/secret getter, new generic callback or configurable authorization implementation is added.',
   ],
  },
  {
   'id':'L2_protected_json_and_full_records',
   'result':'Protected-host data is decoded into original public records, then original constructors perform validation.',
   'evidence':[source(P+'authority_host_generation_input_types.rs'),source(P+'authority_host_generation_input_loader.rs'),ref(P+'authority_host_config.rs')],
   'details':[
    'The existing unchanged read_root_json requires a private Root parent, O_NOFOLLOW/CLOEXEC/NONBLOCK opened regular file, uid 0, masked mode 0600 and link count 1. It reads at most 65,537 bytes, rejects empty or over-65,536-byte input and deserializes the complete JSON.',
    'The loader requires schema 1 and the exact existing-inputs purpose. Fourteen new DTO structs deny unknown fields; OperationFile is a closed tagged Fresh/Recover enum and ConsumerTrustModel has exactly two named variants. Existing nested FinalUse/Cell types use their original parser contracts.',
    'Nine original record types receive all 77 fields: signers, Owner trust, writer lease, Registry head witness/current head, complete withdrawal receipt, selectors/selection trust and the full 22-field signed selection. The checked source lists and actual construction lists are identical.',
    'StableId and Generation constructors remain fallible; digest bytes are passed through their original wrappers; each local signature conversion requires exactly 64 bytes. The selected artifact kind is accepted only as Model, and its generation, optional predecessor, content/objective/support/compatibility, credentials, time window and signature are preserved.',
    'SignedFinalUseGrant, FinalUseFrontier and CellGenerationConfigV2 remain their original types; the loader does not substitute an opaque VerifiedSelection/Receipt/token. The original 64 KiB outer input and original signer/record bounds remain in effect.',
    'This original JSON reader does not provide a before/after fstat stability proof. The report does not claim such a proof; later complete cryptographic/current-state checks are independently required.',
   ],
  },
  {
   'id':'L3_five_descriptor_roles_and_existing_paths',
   'result':'All five retained file roles and existing owner paths have explicit restrictions before original opening.',
   'evidence':[source(P+'authority_host_generation_input_files.rs'),ref('codex-rs/hepta-contracts/src/authority_host_store.rs')],
   'details':[
    'Registry, selected payload and withdrawal snapshot must be read-only; target journal and target witness must be read-write. F_GETFL rejects incorrect access and O_APPEND; all five fstat identities must be distinct dev/inode pairs and all are Root0600 single-link regular files.',
    'Artifact and consumer paths must be different absolute private child paths under the same Session state path, without parent or special components. RootAuthorityDirectory validates them. Every one of the six original Artifact subdirectories and existing writer/owner.lock is required.',
    'FinalUse requires the original authority.lock, authority.claims and nonempty authority.json; the bounded 8 MiB header observation compares dev/inode/size/mtime/ctime including nanoseconds and requires schema 3. Complete trust, head and nonce replay are still delegated to the original store.',
    'Recover additionally rejects an empty target journal or witness shorter than its original 112-byte header before opening the witness. It does not treat an empty consumer journal as proof of a valid recovery: the original nonce replay and published CURRENT chain remain mandatory.',
    'These are protected-path/precondition observations, not a cross-owner atomic lease. They do not prove all files are unchanged on failure or prevent a privileged concurrent Root actor from changing a path between two original constructors.',
   ],
  },
  {
   'id':'L4_actual_artifact_withdrawal_and_selection',
   'result':'The owner, withdrawal history and selected generation are produced by the original verification path.',
   'evidence':[source(P+'authority_host_generation_input_loader.rs'),ref('codex-rs/hepta-learning-artifacts/src/owner_service.rs'),ref('codex-rs/hepta-learning-artifacts/src/owner_host.rs'),ref('codex-rs/hepta-learning-artifacts/src/durable_snapshots.rs'),ref(P+'neuron_generation_update_selection.rs'),ref('codex-rs/hepta-learning-artifacts/src/selection.rs')],
   'details':[
    'Complete Owner trust and signed writer lease are constructed without changing their fields. required_current_head is mandatory and always passed as Some; the exact storage binding and original protected clock are supplied to LearningArtifactOwnerService::open.',
    'The withdrawal snapshot consumes the real supplied file and complete receipt through read_dataset_withdrawal_snapshot. The original reader enforces nonzero bindings, size/count bounds, digest, scope/head, record replay and canonical byte reconstruction; no empty replacement history is fabricated.',
    'The original independent selection verifier receives selection trust and Owner trust. AgentdSelectedGenerationV1::load uses the actual owner CURRENT plus actual registry and payload files, the full signed selection and current original time. Its original payload/canonical manifest/compatibility/withdrawal checks stay intact.',
    'The original owner constructor may perform its original directory/lock/recovery work. Candidate prechecks are intended to require existing state but do not replace that constructor with a read-only fake or a new owner implementation.',
   ],
  },
  {
   'id':'L5_final_use_exact_existing_owner',
   'result':'The original issuer, existing consumer nonce state and independently durable frontier are retained and checked.',
   'evidence':[source(P+'authority_host_generation_input_loader.rs'),ref(P+'deployment_signed_grant.rs'),ref('codex-rs/hepta-contracts/src/final_use.rs'),ref('codex-rs/hepta-contracts/src/final_use_store.rs'),ref('codex-rs/hepta-contracts/src/final_use_retained.rs'),ref('codex-rs/hepta-contracts/src/authority_host_store.rs')],
   'details':[
    'The only Root directory used for the external frontier is the retained private resident_store_root Arc on this same service; a retained original lease Registry is required. No new Root registry, issuer, policy, Config or AutomationStore is constructed here.',
    'The explicit consumer owner_id must equal the retained issuer trust_key.key_id. Fresh additionally requires signed.grant.signer_id to equal that same owner id. This matches the original issuer full-grant verifier and FinalUse claim signer check, rather than relying on a test convention.',
    'HostAuthorityFrontierStore::open opens the existing frontier under that Root directory. The complete protected FinalUseFrontier is compared before the original consumer open. No initialize/for_initial_head or head-update call is introduced.',
    'SingleCurrentIssuer uses the original open_state_dir_with_trust; CurrentIssuerKeyRing uses original open_state_dir_with_issuer_keys with only the retained current issuer key. A preexisting incompatible rotation key set refuses rather than being migrated by this loader.',
    'Both original factories use exact original store/trust/head validation and original nonce replay. current_external_frontier then checks current effect state; the complete frontier, consumer revocation head and a new original issuer-head read must still agree before continuing.',
    'No nonce is refunded, cleared or synthesized. Recover obtains its actual signed grant through the original protected CURRENT/recovery chain; the loader supplies only the exact protected operation id/intent and real selected target.',
   ],
  },
  {
   'id':'L6_target_and_same_session_phase',
   'result':'Target binding and original Fresh/Recover phase transitions share one absolute end per public entry.',
   'evidence':[source(P+'authority_host_generation_input_loader.rs'),source(P+'authority_host_session_generation_input_loader.rs'),source(P+'authority_host_generation.rs'),source(P+'authority_host_session_generation.rs'),ref('codex-rs/hepta-neuron/src/witness.rs'),ref('codex-rs/hepta-neuron/src/cell_generation_context.rs')],
   'details':[
    'CellGenerationOwnerBindingV1::new receives the unchanged original configuration and record bound. Its digest, actual task digest and initial generation are passed to the original FileAnchorWitnessStore with the original witness bound and actual retained file.',
    'Fresh can initialize the original witness header in its explicitly supplied empty witness. This is disclosed behavior, not proof that this loader is globally read-only. Original constructors and later recovery may perform their normal durable effects.',
    'Each consuming public Session entry creates one end from the original timeout, verifies the actual pinned Session before loading, passes the same end to the loader and original bind/recover factory, rechecks the Session and stores exactly that end in the returned carrier.',
    'Fresh accepts only the Fresh DTO and returns InitialHostPhase::Fresh after the original bind operation. It does not publish CURRENT, sign a grant or return a Ready carrier merely from decoded data.',
    'Recover accepts only the Recover DTO, invokes the original recovery factory and returns Ready only with actual original recovered custody. The prior original code requires exact operation/intent and protected Published state, target/selection, consumed FinalUse, lease/issuer/head/frontier and current witness; no Fresh fallback exists.',
    'The same non-Clone Session is moved into the returned object. No additional public wrapper is used to reset the end. Local require_before checks actual real/effective uid 0 and the same Instant before/intermediate/after work.',
    'The end is a result-admission bound, not a proof that every synchronous filesystem/owner operation physically terminates at that Instant. No new per-stage extension, queue, network budget, role identity exception or process cancellation behavior is introduced by this layer.',
   ],
  },
 ],
 'specific_limitations_and_remaining_work':[
   'No Rust compilation, formatting, unit test, positive original owner run, IPC fixture or H/native qualification was performed; static field coverage is not a type-check result.',
   'The four-module layer does not connect the ordinary Root CLI, create the actual task/model files or factory, orchestrate Material Source lending, or complete V3 enrollment. Later source layers must preserve this same Session and actual owner/cut bindings.',
   'It intentionally supports existing consumer schema 3 and the retained current issuer key only. A different historical key-ring/schema is a refused deployment input, not a reason to reset or broaden trust.',
   'Recovery requires existing target state and actual original Published evidence. It is not a generic recovery-to-fresh or missing-state repair facility.',
   'Only fixed opened file identities are checked here. Original full data verification and owner locking remain mandatory. The report makes no claim of a fresh native observation or global filesystem immutability.',
   'Root0600 protected input is supplied by the trusted deployment context, not authenticated peer JSON. The loader does not transfer permission based solely on these decoded records.',
   'New public methods/modules still require eventual exact combined CALLERS/protection/source registration and real compilation/test coverage. This layer has no new tests and is not a final union registration review.',
 ],
 'reviewer_check_correction':{
   'v1_script':pin((O/'verify_inputs_layer.py').read_bytes()),
   'v1_raw_result':pin((O/'EXECUTION_01.original.json').read_bytes()),
   'original_failure':'The reviewer literal locator counted the receipt factory return type followed by a function body as a second record literal. The candidate itself was not changed.',
   'v2_script':pin((O/'verify_inputs_layer_v2.py').read_bytes()),
   'v2_raw_result':pin((O/'EXECUTION_02.original.json').read_bytes()),
   'narrow_correction':'Exclude only the source-line occurrence preceded by -> when locating these fixed record literals. All record declaration and construction fields are still compared completely.',
   'v2_exit_code':0,
 },
 'conclusion':{
   'concrete_static_blockers':[],
   'may_be_considered_for_further_prequalification_source_integration':True,
   'is_execution_approval':False,'is_runtime_authority':False,'qualification':False,
   'H_remains_stopped':True,'prior_unknown_source_dispatch_not_reclassified':True,
 },
 'storage_boundary':'All pins in this local report are computed full-byte content identities. This reviewer did not create or full-GET Git objects for these new report artifacts. Root owns subsequent durable evidence publication.',
}
rp=save('REVIEW.json',review)
names=['verify_inputs_layer.py','verify_inputs_layer_v2.py','EXECUTION_01.original.json','EXECUTION_02.original.json','BYTE_AND_CONTRACT_PROOF.json','seal_review.py','REVIEW.json']
entries=[]
for name in names:
 b=(O/name).read_bytes()
 assert len(b)<=512000
 entries.append({'relative_path':name,'local_path':str(O/name),'pin':pin(b),'actual_Git_create_or_full_GET_claim':False})
ip=save('CLOSED_FILE_INDEX.json',{'format':'fixed-reviewer-closed-files-v1','status':'LOCAL_COMPUTED_PINS_ONLY','entries':entries,'payload_count':len(entries),'with_index_count':len(entries)+1,'H_calls':0,'project_code_executed':False,'source_writes':False,'qualification':False})
print(json.dumps({'review':rp,'index':ip,'payload_count':len(entries),'scope':'pure-static-existing-generation-loader-review','H_calls':0},sort_keys=True))
