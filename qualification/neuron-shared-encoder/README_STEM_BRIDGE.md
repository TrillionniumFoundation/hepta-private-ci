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
