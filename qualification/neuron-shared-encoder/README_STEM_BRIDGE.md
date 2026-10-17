# Shared Encoder Stem bridge (research-only)

`neuron_shared_encoder.stem_bridge` is the next adapter layer after the
`StemManifestV1` / `CellArtifactV1` contracts. It converts a qualified harness
receipt into a frozen Stem transfer case, a Cell parameter ledger, and a
generation-bound feature key.

The bridge does not run a model, select a model, activate a Cell, or grant
feature-cache admission. It must be used after the existing harness has
verified the exact local checkpoint bundle, tokenizer/preprocessor identities,
dataset digest, split boundaries, and runtime receipt.

`FeatureKeyV1` requires a positive run generation, authority epoch, Stem and
Cell generation, source/input/preprocessor digests, and readonly scope. A
caller-supplied `admitted=True` flag is intentionally absent; final-use
admission remains outside this bridge.

`QualificationReceiptV1` includes projector parameters and both resident and
active Cell counts. Synthetic smoke and historical replay remain diagnostic
only. `ReaderGateReceiptV1` converts to a split gate only for real shadow
evidence with independent new source, full citation coverage, and model-hidden
gold. This is a contract for the prospective blinded evaluation; it is not a
result from a real checkpoint.

The bridge is intended to be stacked with the existing qualification harness
from PR #1496 when that research line is available. It does not replace the
harness's FeatureKey/cache admission or its native Worker/Selector gates.

## Frozen Reader fixture adapter

`neuron_shared_encoder.reader_fixture_bridge` delegates the four-condition
Reader protocol directly to `scripts/hepta_sngr_reader_eval.py`. It calls that
script's `load_cases`, `evidence_for`, and `construct_request` functions rather
than reimplementing evidence strings. The adapter checks the registered
manifest digest, exact arm order (`none`, `distractor`, `withheld`, `full`),
source identity, and model-request shape. A missing script, missing manifest,
changed schema, or evaluator error is `ReaderFixtureError`; there is no
synthetic fallback.

`verify_registered_checkout()` delegates the source-byte check to the same
evaluator and therefore verifies each registered Git blob, quoted line, and
withheld control before a model request can be bound. This is still an input
integrity check, not evidence that a model answered correctly.

`ReaderRequestV1` contains only the evaluator-generated `state` and
`questions` payloads accepted by the Reader API. It recursively rejects
evaluator-only gold fields before a caller can pass the request to a model. The
adapter does not invoke a model or score answers. The registered fixture still
requires a real source checkout and the pinned local checkpoint before any
efficacy claim could be made.

## Prospective equal-budget transfer plan

`neuron_shared_encoder.prospective_plan` is the P1 experiment boundary after
the fixture bridge. It requires the frozen shared Stem arms (`shared_head`,
`split_head`, and LoRA ranks 2/4/8), a full-fork control, strong-cheap and
zero-feature/type-prior controls, and a reference-only no-change teacher. All
gate-eligible arms must bind the same Stem, objective, budget digest, Reader
manifest, and independent source policy. A different Stem can remain a
reference control but cannot enter the same System2 interval gate.

Each candidate must receive the same number of Reader calls across
`none`/`distractor`/`withheld`/`full`; measured token, FLOP, memory, latency,
and energy receipts must stay under the matched caps. A `ProspectiveCaseV1`
also binds the task, Reader arm, source split, Git blob SHA-1, request digest,
manifest digest, model digest, held-label digest, and resident/active
parameter counts. P1 deliberately fixes one four-arm presentation per task;
a future schema must add an explicit presentation index before repeated
presentations can increase the call budget. Missing, synthetic, historical,
or model-gold-visible records cannot enter a transfer matrix. The plan is
`SHADOW_ONLY`, has no selection authority, and cannot mutate the current run.

`build_system2_interval_gate()` first requires the complete validated case
matrix and equal, bounded real-shadow resource receipts. It then consumes only
caller-supplied intervals and fully charged `ResourceCostV1` receipts that
have already passed independent real-shadow verification. It returns the
existing #2672 `DENY_ALL` advisory:
interval overlap is `NO_GO`, while strict unique interval dominance is only
`ADVISORY_SELECT`. It does not generate a selection, efficacy, or promotion
receipt and it cannot activate a Cell or mutate a snapshot.

This is still an experiment contract. It does not train a Cell, run a
checkpoint, or prove a Stem winner, NDU efficacy, multimodal generation, or
10T/100T equivalence. The real receipt must come from the pinned harness
before any System2 or split decision is considered.

## Modality tower and projector registries

`neuron_shared_encoder.modality_registry` adds the next research-only
boundary for multimodal differentiation. `ModalityTowerRegistryV1` records
one immutable raw-input tower for each of `audio`, `image`, `text`, and
`video`; `ProjectorRegistryV1` records one digest-bound projector for each
Stem manifest projector ID. The projector input width must match its source
tower, its latent width must equal the frozen Stem hidden width, and its slot
capacity may not exceed the tower capacity. A registry may construct a
`ModalityEnvelopeV1` only after binding the raw and feature digests to the
registered projector and Stem.

The registries retain the harness evidence class exactly, including
`REAL_MODEL_LOCAL_QUALIFICATION`; they never relabel that receipt as
`REAL_SHADOW`. `UNVERIFIED`, synthetic, historical, local-qualification, and
real-shadow records are descriptors of receipt provenance, not multimodal
quality results. Real classes require a checkpoint receipt digest, but a
registry still carries `SHADOW_ONLY`, `selection_authority=False`, and
`current_run_mutation=False`. Towers and projectors are frozen and readonly
for the current generation; changes are future-snapshot artifacts.

These contracts do not load or train a tower, run a decoder, select a
projector, or claim text/image/video/audio generation. They only prevent a
future experiment from mixing modal widths, Stem generations, source tower
identities, mutable features, or untracked evidence while the actual frozen
checkpoint and equal-budget transfer matrix are still pending.

## Componentized resource receipts

`neuron_shared_encoder.component_resource_receipts` is the P2 accounting
boundary. A `ComponentResourceReceiptV1` records the same candidate and
budget identity while keeping nine charged components separate:

`encoder`, `tower`, `projector`, `decoder`, `cell`, `controller`,
`state`, `cache`, and `verifier`. Each component carries its own
implementation digest, device digest, calls, input tokens, FLOPs, peak memory,
p95 latency, energy, and resident/active parameters. A separate
`DeviceReceiptV1` binds the device identity, runtime digest, device kind,
precision, device count, end-to-end peak memory, and measured energy.

The receipt also binds model, tokenizer, preprocessor, runtime, source and
Git blob digests. `COMPLETE` records must contain every component, a device
receipt, all digests, and explicit Reader calls/input-token charges.
`INCOMPLETE` records preserve the exact missing field names and fail closed
before budget qualification; values are never zero-filled. The raw
`evidence_class` is preserved exactly. In particular,
`REAL_MODEL_LOCAL_QUALIFICATION` is not renamed to `REAL_SHADOW`, and
synthetic or historical receipts cannot enter the strict adapter.

`validate_against_budget()` binds both `budget_digest` and
`cost_weights_digest` and checks calls, input tokens, FLOPs, device memory,
latency, and energy against the fixed P1 caps. `to_resource_cost()` and
`to_prospective_receipt()` are available only for complete
`REAL_SHADOW` receipts. The legacy `ResourceCostV1` projection groups
tower/projector with encoder and decoder/state/cache with Cell because its
schema has fewer buckets; `AGGREGATION_POLICY` is recorded and the scalar
`total_units` remains an experiment-local accounting unit, never a claim
that unlike physical dimensions are interchangeable.

This contract still does not run a model, train a Cell, select a device,
activate a split, or grant System2 authority. A future real receipt adapter
must preserve the harness's native evidence class and independently verify the
pinned checkpoint, tokenizer/preprocessor, runtime, source bytes, and device
measurements before any receipt can be considered by the P1 transfer matrix.

## Pinned checkpoint provenance receipt

`neuron_shared_encoder.checkpoint_receipt` closes the identity gap between
the existing Stem protocol and a future real model run. `PinnedCheckpointReceiptV1`
requires one exact checkpoint digest plus model, tokenizer, preprocessor,
runtime, Reader manifest, request, held-label, source, and Git blob digests.
It also requires the harness to report that the checkpoint was actually
loaded, an independent `future` or `ood` source split, model-hidden gold,
and no current-run mutation.

The raw evidence class is preserved. `REAL_MODEL_LOCAL_QUALIFICATION` remains
local qualification and cannot be adapted to a strict `REAL_SHADOW` gate;
synthetic and historical fixtures remain diagnostic. `INCOMPLETE` receipts
carry exact missing fields and are rejected before transfer, OPE,
component-resource adaptation, System2, or Cell split. `bind_identity()`
requires the componentized resource receipt to carry the same checkpoint
bundle and source identities, so a scalar cost record cannot be detached from
the model that produced it.

This is still only a provenance contract. It does not load, run, score, train,
select, or activate any model. A later harness adapter must create the receipt
from measured bytes and runtime state before the equal-budget Reader matrix
and X/P/Y/Z OPE can be considered.
