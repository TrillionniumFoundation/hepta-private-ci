# Additional original Evaluator host and material-export seams

Status: source-bound audit and review preparation only. No production Rust,
reference, permission, wire format, verifier, deadline, or running diagnostic input
was changed. This report does not claim a successful ordinary learning loop or a
complete caller gate.

## Frozen source and observed failure

The inspected upstream is `b29869e856d08db1bfb066116a9c443376ccc57d`.
Both newly reported caller files were independently fetched at the published
`e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd` and at that upstream; each pair
is byte-for-byte identical. They are existing behavior, not behavior introduced
by a new registration.

The original all-boundary diagnostic uses frozen **v2** CALLERS blob
`317da5f28fbc1cf2556fa5935bb846dce8c7c2cb` and its unchanged complete
6,597-file Rust projection. Its SDK chunk
`0856c09b820e7c5f56c5086e8f1c8b272ff4f098` was decoded and verified:
18,769 raw bytes, SHA256
`fd3bb4e1e4f5e6421f781d104329f5fe93962512acecd9ceba0208cfd5d42125`.
The three completed records have `status=failed`, empty missing sets, and only
the following unexpected member each. These are observations of those records,
not a statement that the full diagnostic has finished.

| Position | Exact boundary | Existing registered caller | Additional actual caller |
| --- | --- | --- | --- |
| 459 | `learning_original_evaluation_host_profile` | `neuron_cell_evaluation_host.rs` | `neuron_cell_evaluation_host_training_readback.rs` |
| 460 | `learning_original_evaluation_host_receipt_current` | `neuron_cell_evaluation_host.rs` | `neuron_cell_evaluation_model_material_export.rs` |
| 461 | `learning_original_evaluation_host_constructor` | `neuron_cell_evaluation_receipt_owner.rs` | `neuron_cell_evaluation_host_training_readback.rs` |

Every path in the table is under `codex-rs/hepta-agentd/src/`.
None of these is an unresolved receiver or a same-name method on another type.
The calls use explicit original types and actual original objects.

## 459 and 461: consume the original receipt owner and completed panel

Source: [neuron_cell_evaluation_host_training_readback.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_training_readback.rs),
blob `6c8e5ae94ff4753a48cb92c6b46b8a7559f00793`, 3,464 bytes.

The receiver of `into_host_from_original_training_readback(self, mut panel,
trainer, dataset, training)` is the existing
`OriginalCellEvaluationReceiptOwnerV1<FileAnchorWitnessStore>`. Its parameters
are an actual owned Panel, opaque original Dataset and Training results, and an
already established purpose-fixed original Trainer readback connection.

The function reconstructs the actual Dataset cut, records the exact Training
receipt at its original observation time, and borrows the same receipt owner's
configuration via
`OriginalCellEvaluationReceiptOwnerV1::original_host_profile(&self)`.
It refuses a fenced panel or a different complete Training cut. It then checks
**every** member, including primary and every retention member, for the same
complete Training snapshot and Training attestation, scope, and verifier trust,
scope and objective digests. The check is over the real private qualification
configuration, not a caller-supplied replacement digest.

Only after those checks does it consume
`OriginalCellQ24TrainingReadbackConnectionV1::bind_original_training`.
That previously audited original binder authenticates its fixed initial
context, original peer/currentness and opaque Dataset/Training chain; this new
function does not build another connection or introduce a new purpose. One
`Arc` to the resulting original readonly Trainer capability is installed in the
primary and every retention member. It changes the transport retained by those
members during consuming host assembly; it does not replace their Cell,
qualification, execution, cohort, journal, witness, registration, or retained
result.

The final call moves the **same** `self` and panel into
`OriginalCellEvaluationHostV1::from_original_receipt_owner(self, panel)`.

### Why ignoring the borrowed profile's Boolean does not create Fresh authority

The getter in
[neuron_cell_evaluation_receipt_owner.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/neuron_cell_evaluation_receipt_owner.rs)
returns `(&self.config, matches!(self.host_origin, HostOrigin::ReadbackOnly))`.
It neither writes the private origin nor exposes the key or journal. The caller
uses only the borrowed configuration; the original owner is not cloned.

The final host constructor in
[neuron_cell_evaluation_host.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/neuron_cell_evaluation_host.rs)
calls that getter again on the moved original owner. It checks the original
receipt configuration against the primary's exact Training, scope, plan, Product
plan, execution namespace, Evaluator principal, trust, scope and objective. It
constructs the original Context from the actual Training signature and panel
registration, authenticates its binding with the current clock, and initializes
`execution_requested: AtomicBool::new(readback_only)` from that owner's actual
private history.

This constructor creates an original effect-capable Evaluator command host when
the existing owner really has its Fresh brand. Recovered or attempted owners
remain readback-only. It would be incorrect to describe the resulting host as
universally readonly. Its original receipt signing capability remains in the
original owner, and no signature or evaluation is produced by this assembly
function itself.

## 460: physical original receipt read after actual material projection

Source: [neuron_cell_evaluation_model_material_export.rs](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b29869e856d08db1bfb066116a9c443376ccc57d/codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_export.rs),
blob `8768614e0da009a3ea5deba932c4a62e6694d79b`, 7,347 bytes.

`Owners::original_model_material(&mut self, context)` first records its own
current clock and calls `completion(context, wire::Action::Readback)`. The
original host's protected completion path chooses the receipt owner's actual
readback method; it cannot sign on this action. Missing and Pending remain
incomplete outcomes, and uncertainty does not become NoUpdate.

The function takes the panel's last actually observed retained result, projects
the primary and each retention member, and encodes the exact original Evaluation
snapshot, full Evaluation attestation and member commitments. The private
`member` helper binds each original Cell snapshot and manifest to its signed
comparison arm and observed scope. It serializes the original Product holdout,
plan, request, decision, qualification, estimand, roles, original execution
record/signature, and original cohort/freeze commitment. It does not deserialize
or manufacture an opaque qualification seal.

After projection and encoding it performs a second actual `read_panel()`.
A different result sets the host's fence and returns CommitUncertain. It then
calls the reported boundary on the same retained Evaluator:

```rust
OriginalCellEvaluationReceiptOwnerV1::require_original_host_completed(
    &mut self.evaluator,
    evaluation.receipt(),
    evaluation.attestation(),
)?;
```

The callee reconstructs the original receipt signing payload, encodes that
payload with the **complete** supplied original attestation, and physically
reads `self.journal.read(&self.saved)` from the original owner. It requires
exact byte equality. It has no claim, signing, recovery, create, or timestamp
renewal operation.

The exporter subsequently obtains a fresh internal clock, requires
nondecreasing time, authenticates every current panel member, and runs
`super::verify::material(context, &evaluation, &bytes, current)` before returning
the bytes. Thus this is a real read of the owner whose original signature was
exported, not acceptance of another owner's journal or of an unsigned content
root.

The inspected material service retains the same host in an Arc, performs this
read under its actual Owners mutex on its existing runtime, and releases the
owner lock before writing a response. Finish performs another actual material
read and equality check across the whole paged transfer. That service is
context here; the proposed new fences below do not claim to protect every
transport or codec function.

### Read-only projection dependencies and their exact scope

`CellEvaluationRunnerV1::original_model_commitments`, in
`neuron_cell_evaluation_material_projection.rs`, takes `&self`, checks the
actual qualification comparison and Qualification timing, requires the original
signed execution, and delegates to the original Product commitment projection.

`OriginalCircuitEvaluationCohortReadbackV1::original_model_commitment`, in
`circuit_original_evaluation_cohort_readback.rs`, takes `&self`, requires
unfenced original/current state, the exact last observed cohort and its actual
commitment digest, then clones the original commitment, freeze payload and
original freeze signature. It has no release or signing operation.

Those concrete functions were read, but this report does not claim every
downstream projection implementation is newly source-fenced. In particular the
existing cohort protected row protects its original read/current/authentication
chain and authority denial, while its commitment export method is not currently
a separate function-order entry. The newly admitted privilege is the already
protected original Evaluator journal-read boundary, not a new release or sign
entry point. The original material verifier remains the final cryptographic
check; the two separately prepared retention guards remain required.

## Minimum source-fence and QA preparation

The actual newly admitted callees already have protected contracts:

- Row 344, `neuron_cell_evaluation_receipt_owner.rs`: private Fresh/ReadbackOnly
  history, profile borrow, and the final exact physical receipt check.
- Row 345, `neuron_cell_evaluation_host.rs`: same original owner/panel factory,
  private once state, action-specific completion, before/after panel reads,
  complete original receipt read and final authentication.
- Rows 335–338: original panel registration, member custody/current reads and
  binding, including the separately prepared retention condition in row 338.
- Row 389: material verification, including the separately prepared retention
  condition.

The minimal additional preparation is therefore **two new protected rows**,
covering the consuming training-readback host function and the exporter's
`original_model_material` plus `member`. All three are nongeneric and can use
the original function-scoped verifier with exact masked signature/body order;
no generic fallback is needed for these additions. The new files have no
non-error string or byte-string literals requiring a new actual-span QA rule.
All existing rows and original verifier semantics are retained.

The sibling source-mutation QA will reject omitted/reversed original Training
and full-signature checks, exclusion of retention members, a failure to install
the same Trainer Arc in every member, promotion of the exporter to Execute,
loss of its second actual panel read/equality fence, removal of the final
original receipt read, and removal/reordering of post-I/O current material
authentication. Member mutations target the signed Cell snapshot/manifest/scope
checks and original projection binding. These are source-closure assertions,
not executable forged-signature fixtures or proof of a positive-primary
negative-retention runtime branch.

A complete read-only search of all **52** fixed-upstream
`qa/b4-no-bypass/*source_closure.py` files found only
`test_original_evaluation_host_source_closure.py` declaring these three exact
boundary IDs. Its EXPECTED declarations need the three exact memberships; its
existing functions and unknown-caller injection assertions must remain intact.
The new sibling filename will match the unchanged original
`*source_closure.py` discovery. No workflow list or 600-second budget change is
needed.

## Limits and next step

This audit supports precisely the three reported memberships after their
corresponding source contracts are preserved. It is not authorization for a
wildcard caller, another original owner, a new trust context, a future receipt,
or reconnection after loss.

The source and new QA preparation still require review and eventual execution
at a newly frozen source. The running old v2 all-boundary diagnostic is not
modified, and its failures remain evidence. Its separately reported position
468 typed-receiver issue is not a membership omission and is not covered by
these findings. The actual two-boundary typed-trainer result is also not
evidence that position 468 passed.

No production Rust or Cargo test was run for this report. No ordinary
A → Training → independent B → adopted/complete-NoUpdate → C → cold-recovery
completion is asserted.


## Local preparation validation observed after the audit

The two new protected rows and the new sibling QA were materialized only in an
isolated partial-source preparation. All eight source-mutation methods actually
passed (unittest 0.210 seconds; runner exit 0). The input inventory was identical
before and after. The unchanged original verifier checked the two supplied
source files; this was not complete Rust collection or an original full gate.
Raw log: 1,998 bytes, SHA256
`24a68196dd508c6a63ab3f8d6b4b085e52b9b8674e4ebfa4ea88e6f52cb594b1`.
No runtime owner/signature test was run, and no new source head was frozen.
