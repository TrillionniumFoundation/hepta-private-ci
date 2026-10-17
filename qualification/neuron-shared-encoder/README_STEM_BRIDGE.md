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

`ReaderRequestV1` contains only the evaluator-generated `state` and `questions`
payloads accepted by the Reader API. It recursively rejects evaluator-only
gold fields before a caller can pass the request to a model. The adapter does
not invoke a model or score answers. The registered fixture still requires a
real source checkout and the pinned local checkpoint before any efficacy claim
could be made.

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
