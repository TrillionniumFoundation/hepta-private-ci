# Plasticity V1 rollover: conservation boundary

Source reviewed: `39e1dc390e8cde5579b28375ca8779509293b3d8` (PR1341),
2026-10-03. This is a known-gap regression and an integration blocker, not a
lifetime-budget behavior repair or qualification of V2 admission.

## What the existing owners actually prove

- `plasticity_host.rs::rollover_agentd_plasticity_writer_v1` checks the retained
  previous anchor, durably advances the fence, and enrolls a new empty registry.
  Its arguments include neither old registry bytes nor a consumption index.
- `plasticity_anchor_journal.rs` retains fence/anchor metadata and the previous
  anchor. A digest commits predecessor history but cannot reconstruct proposal
  IDs, complete batches or artifact/window membership without those records.
- `hepta-plasticity/src/durable_registry.rs` protects one scope/fence incarnation.
  Exact retries and conflicts, live-history verification, expected byte length,
  sticky atomic poison and anchored partial-tail/header recovery remain intact.
- `plasticity_process_bootstrap.rs::RegistryDescriptorV1` supports only mode,
  registry/anchor paths, scope and capacity. Its byte pin and strict decoder do
  not provision a policy owner, full policy projection or consumption lineage.
- `iteration_envelope_wire.rs::CanonicalIterationEnvelopeV1` retains fourteen
  registered fields and verifies Generator submission evidence. At the reviewed
  head, only its tests call that API; no runtime producer turns its result into
  envelope/batch admission. `VerifiedLearningEvidenceV1` is not such a capability.
- At this head the public V1 rollover likewise has no production caller. The
  newer self-iteration owner on PR1303 is a different integration source; its
  presence there does not add an owner or installation contract to PR1341.

## Executable known-gap cases

`plasticity_rollover_boundary_tests.rs` uses real durable proposal registries,
the real independent anchor journal and the public V1 rollover. It first retains
and independently acknowledges a complete no-change proposal. It verifies that
same-generation exact retry is unchanged and either changed content under the
same ID or a different ID in the same artifact/window conflicts without writes.
A fourth case keeps the proposal ID but changes the valid window, independently
exercising proposal-ID conflict rather than taking the occupied-slot branch.
After dropping handles and rolling over, it observes an empty generation with
the old anchor retained only as metadata. Raw structural insertion into that
new generation accepts all four cases as new records. The old acknowledged
registry remains byte-identical and independently verifiable.

The raw insertion is deliberately not an authenticated product admission and
its receipt remains deny-all. Passing these tests proves the V1 boundary exists;
it does not prove that lifetime envelope budgets are enforced or exhausted.

`plasticity_process_bootstrap_lineage_tests.rs` verifies that even an exactly
checksum-pinned descriptor rejects attempted lineage/reservation/policy fields
and invented conserving-rollover modes. This preserves the V1 decode boundary;
it is not an implemented missing-lineage V2 admission gate.

The architecture workflow selects exactly these six full test names, across
both actual Agentd modules, and requires at least six executed tests. Renaming,
omitting or failing to compile one cannot produce a six-test pass. The existing
scope predicate covers changes to either owner or either new test file. Existing
qualification gates are retained. Local workflow tests verify command identity
and scope selection, not Rust execution; exact-head hosted Agentd execution is
required before claiming these Rust regressions passed.

## Additive V2 prerequisites; do not reinterpret V1

There is no safe V2 admission hook to repair at this source head. A future owner
must reject an envelope when its independently provisioned full-policy projection
or retained consumption lineage is unavailable. Do not create a permissive
default, reinterpret Generator evidence or accept a caller-supplied digest as
the missing authority. Structural reconstruction alone grants no admission.

The host contract must independently bind the exact canonical envelope and
projection profile, policy-owner identity, lineage identity, initial admitted
incarnation, acknowledged lineage floor and complete consumption-index root.
Existing Git IDs and clock units must remain exact; the full compiler/executor
projection must enforce paths, checks, total candidate count including no-change,
artifact outputs and resource limits rather than discarding unsupported fields.

An admitted/reserved envelope must keep its stable batch identity across restarts,
fences, generations and trust rotation. Before a conserving rollover issues a new
fence, an independent acknowledgement must bind the old final anchor, old/new
scope and fence, and an index that reconstructs every reserved/consumed entry.
Each entry needs envelope/batch/proposal identities, complete candidate count,
original proposal digest/anchor and reservation/commit state. Missing, omitted,
duplicated, reordered, conflicting or rolled-back lineage fails closed.

Keep old history until that complete transition is independently acknowledged
and reconstructible. Capacity exhaustion is an error, never eviction. Expiry by
itself does not prove a retained obligation irrelevant; keep expired entries
until independently authorized retirement proves they can never be admitted
again. A crash or lost acknowledgement reconciles the original immutable batch,
never refunds a reservation or creates a fresh identity. Until this contract is
installed, V2 recovery across a newer fence must refuse admission, while existing
V1 histories and generation-local rollover retain their historical semantics.

No source change here adds trust, reservation/index storage, compiler policy,
activation, migration, new credentials, merge or deployment authority.

## Follow-up source review: existing integration ownership

Selected integration sources were reviewed at
`520a2d96a5dc5728eb9876ca54a597add3653246` (PR1303), 2026-10-03. Their presence
must not be confused with their installation or with this branch's source:

- `local_cpu_parameter_policy.rs::CpuNeuronParameterPolicyV2` retains the full
  canonical envelope, exact operand/check profile and a host pin; it validates
  the execution projection, original round, actual diff, current Fleet ceilings
  and remaining deadline. Its constructor accepting a digest is not itself
  independent pin provisioning.
- `self_iteration_round.rs::RoundJournal::reserve` debits aggregate canonical
  policy candidate counts across Goals and keeps one original wall deadline.
  Pending model requests preserve the exact round through restarts; candidate
  rejection does not refund that reservation. It is therefore inaccurate to
  describe that source as having no budget-owning runtime seam.
- The same journal retains only its current round and at most 32 policy windows.
  It removes expired windows during a later reservation. It is not a complete
  auditable proposal/consumption inventory, an independently acknowledged
  Plasticity generation transition or a replacement for the V2 prerequisites
  above. These observations do not establish a budget bypass: normal admission
  still rejects expired policy and regressed time.
- `local_cpu_round_materials_v3.rs` is explicitly a pure projection. Its
  self-matching canonical digest is a structural check, not a new trust source.
  It must not be repurposed as proof of independent host authorization.

The source-local follow-up on this branch closes a separate retry durability
asymmetry in both parameter and topology registries: after the final-admission
callback, an unchanged retry now revalidates live bytes before returning its
original receipt. Two real package regressions failed before the repair and
pass after it, alongside the full 80-test Plasticity package. Each covers all
seven existing file-corruption variants, including changed historical bodies
with recomputed checksums, truncation and growth. The tests deliberately use the
same out-of-contract callback-phase mutation model as the existing postwrite
tests. New append ordering and all historical V1 rollover bytes/semantics remain
unchanged. This is neither a conserving rollover implementation nor evidence
that a live Generator/Evaluator/Selector cycle has been installed.
