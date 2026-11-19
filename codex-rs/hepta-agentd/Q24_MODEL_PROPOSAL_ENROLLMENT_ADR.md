# Q24 Model proposal enrollment decision

**Status:** proposed; this ADR adds no runtime route, registered capability or qualification.
**Ordinary-route source reviewed:** `fd22aaaf094a7dec4e7a207821fcab9c284972a1`.
**Materializer source:** `97a1fcadbf6c6699a86cf7c68210bea3fcdfda3e`, matching local
`293adf279520d3ad71ade4abe4255a505808b4ac` at tree
`69aa60e46be91f8c10c1b0d809d72cb52b362430`; no execution result is implied.
**Additional startup audit:** `97a1fcadbf6c6699a86cf7c68210bea3fcdfda3e` and
`afd2c91b3b9ef75ab9a174e3af772ad322118f7a`; this does not attest a merged tree.
**Scope:** one ordinary learning operation and its existing Q24 material owner.

The [ordinary ports](src/learning_iteration_ports.rs) and
[dispatcher](src/learning_iteration_proposal.rs) admit Parameter/Topology;
the research payload is test-only. The
[Q24 owner](src/cell_q24_model_proposal.rs) deliberately has no ordinary Root
enrollment. Its receipt remains DENY_ALL. Proposal has no learning-signature
role: recovery must authenticate its original durable owner and anchor.

## Decision: enroll one operation-scoped factory

The original Root enrolls a factory before the learning worker starts. The
host assembles that factory from actual transferred owner capabilities.
Enrollment authorizes only the bounded proposal-owner operation. It creates
no optimizer, evaluator, Selector, CURRENT or FinalUse permission.

The initial profile fixes the operation, allowed Q24 family and resource-owner
slots. Its existing scoped update rule must already derive from an actual frozen
Dataset and materialized batch; neither a placeholder Dataset nor a guessed
candidate/evaluation digest is allowed. At the first qualified cut, the factory
binds the actual material once and opens the existing Q24 owner through its
original create/recover APIs.

Prefer this to late enrollment: the allowed proposal family and owner slots
are fixed before results are observed, and normal progression does not need
a new mid-operation authorization decision. Late enrollment would require a
separate admitted protocol, not an implicit upgrade of the current profile.

## New descriptor and field provenance

Propose a separate `HostAuthorityQ24ModelFactoryProfileV1`, schema 1, and
purpose `runtime.learning.q24-model-proposal.factory.v1`. Existing learning
schema 1/2, their purpose markers, stores and refusal behavior stay unchanged.
A new descriptor is public data, not a factory or proof of file custody.

| Field | Original derivation and required comparison |
| --- | --- |
| `schema_version`, `purpose` | Fixed new-profile constants; reject every other pairing. |
| `backend` | Closed `Q24SingleHeadSgdV1` variant selected by the original Root policy; no caller-defined backend string. |
| `operation_id` | Exact original protected initial request. |
| `initial_head` | Recompute the complete empty initial snapshot from that request and owner set; include all principal/agent/cell/run, bundle, budget, objective, evaluation and expiry inputs. |
| `scope_binding` | The actual registered `FrozenLearningScopeV2`; this first factory profile admits Cell scope and its original update rule only. No legacy-unscoped or base-release route. |
| `proposal_owner_id` | Exact `initial.owners.proposal`; it is not a new signer role. |
| `process_identity_digest` | Existing process-identity digest of the original registered Agentd identity. |
| `writer_proof_digest` | The original Root's currently retained, live writer authorization; never a supplied replacement proof. |
| `journal_slot_binding` | New Root-protected reservation record for the exclusively transferred proposal file and its fixed purpose. A pathname, inode or digest alone is insufficient. |
| `witness_enrollment_binding` | Actual registered durable witness capability and its original independent rollback domain. No fresh in-memory witness or copied journal anchor. |
| `registry_epoch` | Monotonic epoch read from that protected factory reservation; compare the current record before and after owner actions. |
| `expiry_unix_seconds` | Exact original work-envelope expiry; no new deadline. |
| `factory_binding` | Domain-separated digest of all preceding canonical typed fields under `hepta.root.learning.q24-model-proposal.factory.v1\0`. Exclude this field itself; do not hash arbitrary JSON formatting. |

Use bounded, deny-unknown-fields decoding and existing canonical ID/digest
encodings. The new handoff separately retains the original Root and consumer
PID/boot/start-time identities, sealed descriptor, pidfd and purpose binding.
Its original Root/consumer/identity/proof must match the existing learning and
production handoffs. Public profile bytes carry no writable path, key or
constructor for a registered factory.

Root registration must reuse actual Root0600 ownership checks, required mount
binding, live writer lease, current revocations and process-lifetime checks
on both sides of the action. The new protected namespace records the slot;
it does not modify or relabel an existing learning checkpoint record.

## Material binding and transitions

After authenticating the qualified Evaluation cut, derive the material binding
from the exact Dataset prefix, original Training observation/evidence, Evaluation
head, candidate/parent bundles and the existing Q24 owner's binding. Obtain the
full manifest, evaluation-journal and qualification binding through that owner's
[admission](src/cell_q24_model_proposal_admission.rs); do not reproduce it from
caller digests. Persist the factory's one-operation binding before admitting
owner creation. The model owner retains its existing journal format and domains.

| State/input | Required action and next state |
| --- | --- |
| No registered factory | Refuse Model dispatch; do not attach a dummy plasticity owner. |
| Reserved + authenticated Training or Evaluation NoUpdate | Leave the model owner uncreated. Continue the original retained Selection and actual next-task-use path; this alone is not a completed loop. |
| Reserved + qualified original cut | Recheck current Root, Dataset/source, artifact and evidence owners; bind once, then create only the reserved original model owner. |
| Creation started / acknowledgement lost | Reopen that exact file and witness against the recorded binding. Missing, mismatched or unresolved state remains fenced/uncertain; never replace, truncate or repeat genesis. |
| Bound + same material | Call the original `commit_or_readback`. Different material or operation is refused, not rebound. |
| Pending / commit acknowledgement lost | Use original recover/readback only. Pending remains Pending; reconcile an already persisted suffix with its original witness, without creating another proposal. |
| Completed + valid current evidence | Return the exact original typed receipt and timestamp. Compare the complete operation, owners, predecessor and observation with the checkpoint. |
| Expired/revoked evidence or unresolved relevant-frontier change | Admit no new work. Historical readback still requires current original evidence; failures are not relabeled NoUpdate. |

The current dispatch footer samples a new clock. The Model branch must bypass
that restamping and return the original owner's receipt. On every restore,
including a completed snapshot, a concrete stage adapter must call the original
model owner's readback and compare the retained Proposal. A cached receipt,
checkpoint commitment or caller-controlled `validate_recovery` success is
insufficient. Whole Root/process succession remains subject to the existing
[original writer handoff](HOST_COLD_WRITER_HANDOFF.md); this profile does not
manufacture a successor authority from stored bytes.

## Required typed startup inputs

Before the worker starts, require the original learning handoff/scoped checkpoint,
the new Root-enrolled factory capability, reserved exclusive file/witness
capabilities, concrete original stage services, and pinned evidence trust. Keep
the existing Circuit/foreground readiness requirements. The actual Dataset and
batch must exist before registering this first scoped profile, as explained
below; Training and Evaluation results must come from subsequent original work.
At the Proposal boundary, those services must resolve and revalidate the following
actual typed inputs:

- The original durable Q24 trainer owner with a batch retaining the actual
  `Some(Arc<OriginalDataset>)` source capability, plus its original Dataset cut.
- The original ledger/source read capabilities and current freeze/withdrawal
  checks, the enrolled Generator evidence owner and pinned trust/revocations.
- The original independent evaluation runner, holdout CAS/execution owner,
  qualification inputs and currently valid Evaluator attestations.
- The actual artifact/selected-material owner needed to revalidate the original
  baseline and candidate frontiers.

The batch method `revalidate_source` deliberately permits legacy
`None`/HQ24T001 batches. That compatible success does not admit this factory.
Add a crate-private `require_original_dataset_provenance` gate on the durable
trainer owner itself, checking its own batch's private capability; do not accept
a Boolean, HQ24T002 tag, digest or marker supplied by the caller. Keep legacy
training/NoUpdate behavior unchanged. On recovery, the host must re-supply the
original ledger/source typed capabilities and the durable owner must revalidate
them; serialized batch bytes cannot recreate them. This structural gate does
not replace the live checks before and after owner work. Advancing model CURRENT
does not itself revoke completed experience: original Dataset authorization and
withdrawal govern reuse; the separate artifact owner governs proposal admissibility.

## Reviewable implementation slices

1. **Descriptor and provenance boundary.** Design private descriptor/context/error
   types, canonical binding checks and the trainer-owned provenance gate, with
   dedicated sibling test modules. The proposed test interface is
   `validate_q24_model_factory_descriptor_v1(bytes, original_context)`, returning
   a validated data description only. The provenance gate returns a result, not
   a Root capability. Do not land unused helper code before its registered
   consumer is reviewed.
2. **Real enrollment and assembly.** Add the new protected registration, slot and
   purpose-specific handoff beside `authority_host_learning_profile.rs` and
   `authority_host_learning_registration.rs`. Carry only its privately
   constructed capability through `root_production_learning_inputs.rs`,
   `config_root_learning.rs` and Agentd configuration. Register the concrete
   consumers in the existing caller-closure inventory.
3. **Ordinary dispatch and recovery.** Add the explicit Model-owner startup branch
   in `runtime.rs`/state, then the typed route in
   `learning_iteration_ports.rs`/`learning_iteration_proposal.rs` and a concrete
   recovery adapter. Retain Running/AppServer/unfenced lifecycle checks. Preserve
   the Parameter/Topology requirement when their original route is selected.
   Do not weaken a global startup check or change DENY_ALL.

Necessary controls: old-purpose/schema rejection; full-context and cross-Root
substitution; duplicate enrollment; wrong file/witness/epoch; legacy or
fabricated-tag provenance refusal; capability retained by a real clone;
withdrawal/revocation/artifact drift during admission; missing or rolled-back
stores; lost-ACK byte/timestamp equality; Pending without retry; expired evidence;
NoUpdate without Model creation; absent enrolled owner at ordinary startup.
Use real owner fixtures for component tests and label their scope. Pure parsing
tests cannot certify custody, ordinary execution or cold recovery.

## Concrete unassembled inputs

This source does not supply an actual Root factory reservation/protected epoch,
a purpose-bound factory handoff, registered file/witness capabilities, or the
ordinary concrete Model stage adapter. The materializer supplies a Dataset
consumption mechanism; no ordinary host is established here that supplies all
of its original ledger/source captures and stage inputs. Independent evaluator
keys/holdout ownership, live artifact owner connections and original Root
succession receipts must come from their actual owners. Test keys, Memory
witnesses, JSON pins and historical component passes cannot fill these slots.

## Actual startup prerequisite gaps

The additional read-only audit found an earlier installation gap. At the fixed
source above, [`AgentdProductionStartup::receive`](src/production_launcher.rs)
connects the original Root lanes and retains learning inputs in
`AgentdConfig::with_root_learning_inputs`. It returns the configuration to the
caller, so explicit host assembly is possible. However,
`AgentdProductionLaunch::run` first calls
[`require_root_learning_assembled`](src/config_root_learning.rs) and refuses a
retained checkpoint with no stage assembly. A received checkpoint is not an
installed learner.

The [closed caller inventory](../../CALLERS.toml) records these product edges
at `97a1fcadbf6c6699a86cf7c68210bea3fcdfda3e`:

| Existing boundary | Registered product caller at this source |
| --- | --- |
| `AgentdConfig::with_root_learning_stage_owners` | None. This is the missing host installation call before `launch.run(config, ...)`. |
| `AgentdRootLearningInputsV1::into_learning_runtime` | Only `config_root_learning.rs`; it still requires actual `Arc<dyn LearningIterationStageOwnerPortsV1>` and pinned `LearningEvidenceVerifierV1`. |
| `CellQ24DatasetTaskV1::capture`; `CellQ24TrainingBatchV1::from_original_dataset` | None. The materializer does not obtain original source/ledger capabilities on ordinary startup. |
| `OriginalCellQ24TrainingStageV1::from_original_owners`; `execute_training` | None. The adapter can consume a durable trainer and Generator receipt owner, but does not assemble other stages or Root startup. |
| `CellEvaluationRunnerV1::evaluate_or_readback`; `OriginalCellEvaluationReceiptOwnerV1::create/recover` | None. Original evaluator machinery exists, without this ordinary host composition. |
| `CellQ24ModelProposalOwnerV1::create/recover/commit_or_readback/readback` | None. An enum variant alone would not connect the material owner to ordinary work. |
| `read_generation_learning_stage_v1` | None. Its authenticated Selection/NextUse readback is not an installed ordinary consumer. |

The reviewed `afd2c91b3b9ef75ab9a174e3af772ad322118f7a` has byte-identical
`config_root_learning.rs`, `root_production_learning_inputs.rs` and
`production_launcher.rs`. Its LocalDecision additions do not fill these
installation edges. This is a source audit, not an execution result or a claim
about an unreviewed successor.

### Scope timing is already defined

[`CellQ24SgdRuleV1::digest(batch)`](src/cell_composed_q24_training.rs) commits
the batch digest. The single-head update rule commits that optimizer digest,
and [`CellQ24SingleHeadTrainingPlanV1::from_dataset_cut`](src/cell_composed_q24_training_plan.rs)
requires exact equality with the original `FrozenLearningScopeV2`.
[`HostAuthorityLearningProfileV1::new_scoped_v2`](src/authority_host_learning_profile.rs)
requires that update rule when it creates the original profile.

Consequently, this first factory can be enrolled after an actual task/Dataset
has been frozen and materialized, before training and evaluation. It cannot use
the existing scoped profile to promise a still-unknown Dataset from a future
task. Automatic creation from a new completed task needs an explicit protocol
that hands the actual admitted Dataset/scope to the same original Root before
starting that learning operation. Silently replacing the update rule, switching
to the legacy unscoped profile, or computing a placeholder digest is invalid.

### The concrete installation unit

A connected implementation must include all of the following in the same
reviewed owner lifecycle:

1. Implement the new Root reservation, register/open/seal operations and
   purpose-specific handoff beside the existing learning registration. Extend
   the authority-host entry point and original handoff consumer; retain the
   actual Root/consumer pidfds, live writer proof, lease, revocation and protected
   witness checks. These are implementable delivery mechanisms, not facts
   established by this ADR.
2. Install a concrete stage-owner aggregate between
   `AgentdProductionStartup::receive` and `AgentdProductionLaunch::run`, then
   call `with_root_learning_stage_owners`. It must own the actual source and
   ledger capture, Dataset freeze, trainer/Generator receipt owner, independent
   evaluator services and real selection/use readers. A delegating wrapper
   around an otherwise unprovided stage trait does not complete this edge.
3. Place Model creation/readback inside that aggregate's original bounded owner
   lane. `OriginalCellQ24TrainingStageV1` retains its trainer privately; expose
   a narrow admitted operation in that lane, not a general mutable trainer
   getter. Apply the trainer-owned provenance gate and revalidate live evidence
   before and after Model work. Add the new dispatcher route and concrete
   recovery validation together, preserving original receipt timestamps.
4. Give the Model route an explicit enrolled startup admission. The current
   `runtime.rs` rejects any learner without a governed plasticity bootstrap;
   retain the Parameter/Topology contract and the Running/AppServer/unfenced
   lifecycle checks. A dummy plasticity owner or removal of the global check
   is not Model registration. Update the closed caller inventory for every
   newly installed production edge.

The inputs cannot be reconstructed from the initial owner IDs or trust digest.
[`AgentdRootProductionInputs`](src/root_production_inputs.rs) currently carries
the Root session, protected checkpoint, device/Notes authorities and grants;
[`AgentdRootLearningInputsV1`](src/root_production_learning_inputs.rs) adds the
learning checkpoint, identity and scope. Neither contains a learning
Generator/Evaluator signing owner, original Dataset writer, independent holdout
CAS/execution owner, Model file/witness reservation, or adopted C owner.

This session has not established an ordinary deployment providing those
original task/Dataset capabilities, an independently held B holdout and its
actual execution evidence, a real successor C consuming the selected owner,
or whole daemon/Root exit and succession. Component fixtures may exercise real
mechanisms, but cannot supply those deployment facts. The next implementation
unit is therefore original stage-owner installation plus its actual Root
delivery, with Model factory/routing inside that unit. A Model-only patch
would remain unreachable or depend on invented inputs; it is not the selected
implementation.

No interface in this ADR is asserted to be implemented or tested. Selector
publication/withdrawal, independent consumer FinalUse and whole daemon/Root cold
recovery remain separate work and qualification.
