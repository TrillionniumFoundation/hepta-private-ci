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

`ReaderRequestV1` contains only the evaluator-generated `state` and `questions`
payloads accepted by the Reader API. It recursively rejects evaluator-only
gold fields before a caller can pass the request to a model. The adapter does
not invoke a model or score answers. The registered fixture still requires a
real source checkout and the pinned local checkpoint before any efficacy claim
could be made.
