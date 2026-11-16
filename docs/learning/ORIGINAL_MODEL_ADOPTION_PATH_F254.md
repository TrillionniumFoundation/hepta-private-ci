# Original Model publication and adoption: fixed-source engineering trace

## Scope and source identity

This is an internal implementation tracking record, dated 2026-11-12. It records
what the inspected source implements, the remaining producer and protocol work,
and the original capabilities a concrete implementation must consume. It does
not register a new caller, change policy, confer authority, or certify acceptance.

| Field | Fixed value |
| --- | --- |
| Repository | `TrillionniumFoundation/hepta-private-ci` |
| Inspected commit | [`f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7) |
| Inspected tree | `51361a51fe1ed38f36ebe3bdd9267a8f6b0773b6` |
| First parent | `bf210cfcde3c9278eb3687a051e1757da93cbb4f` |
| Second parent | `5329441a9f97ca63225fc03de2732f474b98d11a` |
| Method | Read fixed source, concrete APIs, and the fixed caller registry |
| New runtime or native acceptance supplied by this record | None |

Every source link below is pinned to that commit unless explicitly marked as a
later, separate change. The conclusions about missing producers refer to the
inspected production interfaces and caller entries. A default-branch code search
is not evidence that no implementation exists elsewhere or on another branch.
The learning directory's [existing scope](README.md) also separates documentation
closure from implementation, activation, acceptance, and release.

## Finding

The repository has original Trainer Model journals, artifact publication
machinery, independent artifact selection verification, version publication,
and an actual FinalUse issuer. Those components do not yet form one ordinary
positive-adoption route at this source. Several gaps are concrete implementation
work: a purpose-fixed Model command, live evaluator material delivery, a Model
artifact producer, original signed-head and artifact-choice producers, and
positive version/learning-receipt transport. They cannot all be described as
merely waiting for an external grant.

The existing Model and candidate receipts deliberately carry
`AuthorityPosture::DENY_ALL`. They can bind material and audit decisions; they
cannot become a writer lease, an original artifact selection, or a FinalUse grant.
The three separate actions remain: publishing candidate material, choosing an
artifact, and authorizing a particular generation transition. See the exact
[Model receipt](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/cell_q24_model_proposal.rs#L85),
[candidate material](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/cell_q24_candidate_material.rs#L69),
[artifact signatures](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/owner_host.rs#L85),
[artifact selection](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/selection.rs#L60),
and [generation binding](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/neuron_generation_current_types.rs#L65).

## Ten implementation locations

| # | Existing source and API | Implemented boundary | Remaining ordinary-route work |
| --- | --- | --- | --- |
| 1 | [OriginalCellQ24CandidateReadbackClientV1::readback](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/cell_q24_training_candidate_readback.rs#L109); [OriginalCellQ24CandidateMaterialV1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/cell_q24_candidate_material.rs#L49) | Reads the original Trainer's bounded pages and full original Training evidence, reconstructs the actual model, and exposes sealed model/bundle/heads. Material has no publication authority. | Transfer this actual material to the authorized Model/version hosts. Do not synthesize future model bytes from a receipt digest or assume publishing a manifest supplies weights to C. |
| 2 | [SourceBoundCellQ24TrainingStageV1::{create_model_owner,recover_model_owner,commit_model_or_readback,read_model_proposal}](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/cell_q24_source_bound_stage.rs#L102); [in_model_lane](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/cell_q24_training_model_lane.rs#L105) | Uses the same original SourceBound Trainer lane and original files/witness. Actual source, native Training completion, and original Generator evidence are checked around Model work. | Add a concrete original Trainer Model command host and initially bound, keyless client. Create/recover/commit have no product caller at this source. A second trainer or caller-supplied callback is not a substitute. |
| 3 | [CellQ24ModelProposalInputsV1 / CellQ24ModelProposalOwnerV1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/cell_q24_model_proposal.rs#L71); [Model admission](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/cell_q24_model_proposal_admission.rs) | Original Model claim/complete/readback validates actual T, the concrete runner, raw evaluation, Qualification, Product signatures, and candidate/baseline compatibility. Pending and uncertain work remain distinct from completion. | Supply current, original Evaluator/Panel material to this exact boundary. A standalone opaque Evaluation receipt does not supply the concrete runner/Qualification inputs the current API requires. |
| 4 | [LearningIterationProposalPayloadV1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/learning_iteration_ports.rs#L21); [submit_iteration_proposal_v1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/learning_iteration_proposal.rs#L16); [ResidentStages::require_stage](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/authority_host_learning_resident_stages.rs#L60) | The production proposal payload has Parameter and Topology variants. ResearchExternalTrainedArtifact is test-only. Resident Proposal is refused. | Add a closed, original Model route and its actual owner protocol. Do not promote a test variant, add an authority-bearing Model(receipt) shortcut, or relabel Q24 heads as the existing Parameter product protocol. |
| 5 | [LearningArtifactManifestV2](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/closure_v2.rs#L42); [admit_manifest_at_withdrawal_head_v3](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/admission_v3.rs#L31); [Model payload loading](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/neuron_generation_update_selection.rs#L91) | Full provenance and the original withdrawal head can be validated. Model loading requires canonical CellBackendManifestV2 bytes and compatibility. Admission itself is pure and DENY_ALL. | Build the exact manifest and canonical payload from actual material and host provenance. Training-code, runtime/device, schema, normalization, lineage, size, and content fields need real values; nonzero placeholders are not evidence. |
| 6 | [LearningArtifactPublishRequestV1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/owner_service.rs#L44); [LearningArtifactOwnerService::publish](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/owner_service.rs#L166); [original artifact host](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/owner_host.rs) | Existing publication advances Prepared, PayloadDurable, RegistryDurable, WitnessDurable, and Acknowledged under the original lease/checkpoint. It supports original recovery. | Implement a fixed-candidate Model publisher consuming the existing service and original signatures. Calling publish after an unknown result may resume writes; it is not a read-only recovery operation. |
| 7 | [SignedArtifactWriterLeaseV1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/owner_host.rs#L85); [SignedCurrentArtifactHeadV1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/owner_host.rs#L122) | Signing bytes, trust, epoch/floor, expiry, current-head verification, and durable publication binding exist. | An actual original head-signing purpose/producer or an externally supplied exact original signed head is still needed. The inspected production artifact modules verify these signatures; test signing helpers do not establish a deployed producer. Keep keys with their original enrolled hosts. |
| 8 | [ArtifactSelectionVerifierV1::verify](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/selection.rs#L260); [record_verified_selection](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/selection.rs#L352); [load_selected_candidate](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/selection.rs#L389) | Verifies a separately signed choice against actual artifact CURRENT and records an original lifecycle choice. The lifecycle path includes OperatorAccepted then Selected. | Provide the independent original Artifact Selector's actual choice/signature and required prior lifecycle state. These APIs verify/record a choice; they do not manufacture its signer or prior acceptance. |
| 9 | [AgentdSelectedGenerationV1::load](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/neuron_generation_update_selection.rs#L91); [prepare_agentd_generation_cold_drained_update_v1](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/neuron_generation_update_cold.rs#L69); [final_use_binding / publish](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/neuron_generation_update.rs#L218) | Loads the selected Model from original files/CURRENT; prepares a drained predecessor and exact target; publishes only under the exact original FinalUse binding. Actual Control state and original journal/witness participate. | Bind positive Candidate/Model evidence to this concrete host and the actual C worker. The independent artifact choice and FinalUse remain required. NoUpdate's same-model route cannot be relabeled as positive adoption. |
| 10 | [DeploymentFinalUseIssuer::issue](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/deployment_issuer.rs#L330); [serve_next](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/deployment_issuer.rs#L490); [AgentdUnixFinalUseGrantProvider::from_root_stream](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/root_issuer_client.rs#L76); [request_grant](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/final_use_issuer.rs#L102) | A real original issuer and keyless, protected client already exist. Issuance uses persisted original policy, durable sequence, original signer, and expiry checks. | Reuse this exact issuer once for the retained prepared generation binding, under an already applicable policy. Do not add an alternate issuer, substitute the Resident grant, change policy, or retry an uncertain request. |

### Caller evidence at the fixed source

The fixed [CALLERS.toml](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/CALLERS.toml) explicitly has empty product
caller sets for:

- `learning_source_bound_training_stage_model_create`;
- `learning_source_bound_training_stage_model_recover`;
- `learning_source_bound_training_stage_model_commit`;
- `learning_original_circuit_model_selection_receipt_create`;
- `learning_original_circuit_model_selection_receipt_recover`;
- `learning_original_circuit_model_selection_receipt_attest`;
- `learning_original_circuit_model_selection_receipt_readback`.

The Model readback entry,
`learning_source_bound_training_stage_model_readback`, has the concrete caller
`codex-rs/hepta-agentd/src/circuit_model_selection_receipt_sources.rs`.
This is a real readback edge, not evidence that the Model producer has been
assembled into the ordinary route. Subsequent implementation must register only
its actual new callers and keep the original closed boundaries and negative
source controls.

## Original Model input and ownership boundaries

The existing Model input is a borrowed, concrete combination:

```text
CellQ24ModelProposalInputsV1 {
    training_cut,
    training_attestation,
    runner,
    evaluation,
    qualification,
    request,
}
```

The [definition and admission](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/cell_q24_model_proposal.rs#L71)
matter: a digest of Evaluation, a detached signed receipt, or a caller-built
future snapshot does not replace a live runner, its original completed execution,
and a qualifying Product result. Model admission recomputes the matching
Evaluation stage using the original Evaluator window; it does not obtain a new
window by treating current time as a new signature time. The
[learning-evaluation bridge](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/neuron_cell_learning_evaluation.rs)
and [Model admission](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/cell_q24_model_proposal_admission.rs)
are the relevant existing checks.

| Original holder | Concrete custody/material needed | What this holder does not obtain from another receipt |
| --- | --- | --- |
| Trainer / Model host | Same SourceBound stage, original Model File/witness, original T and current Evaluator/Panel material | Artifact writer/head/Selector keys or generation FinalUse |
| Evaluator / Panel host | Actual B and retention sources, original runner/execution/Qualification/Product owners and signatures | Permission to select or activate a model |
| Artifact writer host | Original service, writer lease, provenance admission, payload, signed current head and original durable state | Selector choice or generation activation |
| Original artifact head signer | Existing enrolled signing custody and exact registry/head context | A general signing payload supplied by Agentd |
| Original Artifact Selector | Existing enrolled Selector custody, actual artifact CURRENT and required lifecycle predecessor | Authority inferred from the later LEARN Selection receipt |
| Version / C host | Selected original Model, previous and target journal/witness, original Control owner, actual C source/model, exact FinalUse | A new grant inferred from Resident registration |

These custody distinctions follow the concrete constructors in
[Model](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/cell_q24_model_proposal.rs),
[artifact owner service](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/owner_service.rs),
[artifact selection](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/selection.rs),
and [generation publication](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/neuron_generation_update.rs).
A new command protocol should move the existing capability into a purpose-fixed
host; it should not place all role keys in Agentd or add a public callback
factory.

### Artifact selection is earlier than the LEARN Selection receipt

`OriginalCircuitModelSelectionReceiptOwnerV1` observes an actual Model proposal,
original evaluation/execution evidence, and an already published Cell selection.
Its [sources](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/circuit_model_selection_receipt_sources.rs)
and [owner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/circuit_model_selection_receipt_owner.rs)
do not publish an artifact or choose an unpublished candidate. Using this receipt
owner as the upstream Artifact Selector would reverse the dependency and erase
the independent choice boundary.

## Existing FinalUse: exact legal reuse

The protected client is already concrete:

```text
AgentdUnixFinalUseGrantProvider::from_root_stream(
    stream: UnixStream,
    root_pid: u32,
    root_pidfd: OwnedFd,
    timeout: Duration,
    lifetime: Duration,
) -> Result<Self, AgentdFinalUseIssuerError>;

provider.request_grant(
    binding: &FinalUseBinding,
) -> Result<SignedFinalUseGrant, AgentdFinalUseIssuerError>;
```

See [constructor](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/root_issuer_client.rs#L76)
and [request/exchange](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/final_use_issuer.rs#L102).
The protected constructor pins the original UID 0 peer, held pidfd, and original
absolute lifetime. The request consumes the socket while in flight; actual peer
lifetime and deadlines are checked around the exchange. An I/O, framing, binding,
or peer-lifetime error shuts the socket down and does not restore it. A valid
explicit denial is different: the exchange returns `Ok(None)`, restores the
transport, and `request_grant` maps that value to `Denied`. Therefore the new
host must enforce its own shared once/admission state; transport availability
after denial is not permission to request again or obtain a new window.

The existing issuer's
[policy match and durable issuance](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/deployment_issuer.rs#L348)
match the original subject, destination, and scope. Sequence persistence precedes
signature production, and a late or backwards clock discards the reply without
refunding the persisted sequence. A parsed returned grant still requires the
existing original FinalUse authority verification at publication. The response's
unsigned revocation field must not replace the authenticated authority head.

The generation owner derives the exact binding in
[UpdateIntent::binding](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/neuron_generation_current_types.rs#L65):

| Field | Actual source |
| --- | --- |
| `subject_id` | Previous generation scope's agent ID |
| `request_sha256` | Full original generation update intent digest |
| `scope_sha256` | Original previous generation scope digest |
| `payload_sha256` | Actual target generation configuration digest |
| `destination_id`, stopped predecessor | `agentd.cell-generation.replace` |
| `destination_id`, drained predecessor | `agentd.cell-generation.replace-drained` |
| `destination_id`, drained same-model task | `agentd.cell-generation.next-task-same-model` |

The original Resident admission purpose is different; its
[registration/profile binding](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/authority_host_learning_resident_profile.rs)
does not grant any of the generation destinations above. The narrow reusable
edge is: retain one real Prepared generation, derive its binding, make one
original keyless issuer request under the existing applicable policy, and pass
that exact returned signature to the original Prepared publication method.
Denied, missing, expired, or uncertain issuance must not create an alternate
policy, key, nonce, or replacement authorization.

## Concrete implementation work that remains

The following are implementation slices, not assertions that this fixed source
already exposes the proposed APIs.

1. **Original Trainer Model command.** Consume the same original SourceBound
   stage and transferred Model File/witness. At initial handoff, consume the
   original peer/pidfd and start the existing absolute session deadline. Bind
   actual T and E only after their original owners produce them. Execute the
   existing create/commit path once; recovery uses the original readback path.
   Never create another trainer, accept a future snapshot/batch/signing body, or
   retry unknown work.

2. **Current Evaluator material delivery.** Add a sealed, purpose-fixed read from
   the original Evaluator/Panel host supplying exactly the material the Model
   admission verifies. It must preserve actual B/retention CURRENT and the full
   original Training, Evaluation, Product, and execution signatures/windows.
   Preserve actual reads before and after Model work and final authentication
   after all relevant I/O. A cached Panel digest is not this capability.

3. **Model artifact preparation and publication.** Derive the canonical Model
   payload and full provenance manifest from the actual candidate. Consume the
   original artifact writer service, lease, withdrawal registry, and exact
   signed head. Fix one operation/intent and use true readback after unknown
   outcomes. No caller-supplied arbitrary artifact bytes may bypass actual
   candidate binding.

4. **Original head and independent choice producers.** Implement narrow
   producer purposes in the original enrolled hosts, or consume their already
   available exact original outputs. Each must bind its actual durable state,
   epoch, expiry, and independent role; neither may sign a caller-selected
   opaque preimage. Do not manufacture OperatorAccepted from a Model or E
   receipt. These are distinct from obtaining an external deployment grant.

5. **Positive version and completed-C route.** Use the actual independent
   selection, existing original FinalUse edge, and original generation owner to
   publish the target. Supply the actual candidate model to C. Bind the
   subsequent learning Selection and NextUse receipt owners to these original
   results, with initial transport lifetimes preserved across late binding.
   The local
   [PublishedCircuit read](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/circuit_feature_current_learning.rs#L43)
   and [NextUse owner](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/circuit_next_use_receipt_owner.rs)
   provide relevant mechanisms; the current NoUpdate-specific remote command
   profile is not automatically a positive-adoption command.

6. **Ordinary entry assembly.** Add only the concrete, closed Candidate route to
   the original Resident registration/continuation, sharing the actual E/D/T
   chain. Keep original request/role/current authorization at effect boundaries.
   Candidate failure or unsupported B data must not be rewritten as NoUpdate.
   The fixed Resident Proposal refusal remains correct until that route and
   original capabilities are implemented.

### Inputs that implementation must not fabricate

Real independent B/retention observations, original Outcome signatures,
historical training cohorts, complete qualifying Product signatures, provenance
metadata, writer/head/Selector custody, and an applicable original FinalUse
policy are required inputs. Their absence is a concrete refusal or pending
condition. It does not authorize test Product signing, treating predictions as
labels, copying old signatures into a new time window, or replacing a missing
producer with a generic callback. Relevant existing checks are in
[Model admission](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/cell_q24_model_proposal_admission.rs),
[artifact provenance admission](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/admission_v3.rs),
[selection verification](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-learning-artifacts/src/selection.rs),
and [original issuer policy](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/f254a014e7f5d0b85706d61d62b0e5e29b0aa9c7/codex-rs/hepta-agentd/src/deployment_issuer.rs#L348).

## Later separate Artifact readback work

The separately reviewed commit
[`8b38d4eecc893d3601b3ebdf409df191a81cd9ab`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/8b38d4eecc893d3601b3ebdf409df191a81cd9ab)
adds `LearningArtifactOwnerService::read_original_publication_current` and
bounded original registry receipt scanning. Its
[readback implementation](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8b38d4eecc893d3601b3ebdf409df191a81cd9ab/codex-rs/hepta-learning-artifacts/src/owner_service_readback.rs)
and [bounded host scan](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/8b38d4eecc893d3601b3ebdf409df191a81cd9ab/codex-rs/hepta-learning-artifacts/src/owner_host_readback.rs)
are useful for the unknown-outcome boundary in slice 3.

That change is not part of the f254 tree audited above. Its source review does
not establish runtime/native success, prove that a historical acknowledgement
equals the latest selected CURRENT, or complete Model publication/adoption.
Any integrated Version review must name its own coherent fixed commit and
retain the actual parent graph.

## Acceptance accounting

| Claim | Credit from this document |
| --- | --- |
| Existing source/API and missing-edge trace | Fixed-source inspection only |
| New Model command or artifact producer implemented | 0 |
| New Rust build, native test, or source-guard run | 0 |
| Ordinary A → actual Training → independent B/retention → adoption → fresh C | 0 |
| Correct ordinary NoUpdate/rollback instance | 0 |
| Whole daemon/Root cold restart with version/private-state/uncertain-effect checks | 0 |
| Sustained benefit across time windows | 0 |

A later candidate must record its exact commit/tree, original raw logs and
fresh test reports, actual owner signatures and current state, and the observed
ordinary task sequence. A source trace or component mechanism must not inherit
acceptance from a different branch, source tree, or synthetic fixture.
